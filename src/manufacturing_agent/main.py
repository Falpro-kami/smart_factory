import asyncio
import os
from functools import lru_cache
from pathlib import Path
import queue
import tempfile
import threading
import wave

from agent_core import AgentRuntime, load_project_env


VOICE_COMMAND_PREFIXES = ("/voice", "/stt")
RECORD_COMMAND_PREFIXES = ("/record", "/mic")


def _strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return float(value)


@lru_cache(maxsize=4)
def _get_whisper_model(model_name: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Run `python -m pip install faster-whisper` first."
        ) from exc

    model_kwargs = {
        "device": os.environ.get("STT_DEVICE", "cpu"),
        "compute_type": os.environ.get("STT_COMPUTE_TYPE", "int8"),
    }

    download_root = os.environ.get("STT_DOWNLOAD_ROOT")
    if download_root:
        model_kwargs["download_root"] = download_root

    cpu_threads = os.environ.get("STT_CPU_THREADS")
    if cpu_threads:
        model_kwargs["cpu_threads"] = int(cpu_threads)

    return WhisperModel(model_name, **model_kwargs)


def _get_model_name(mode: str) -> str:
    if mode == "live":
        return os.environ.get("STT_LIVE_MODEL") or os.environ.get("STT_MODEL", "small")
    if mode == "final":
        return os.environ.get("STT_FINAL_MODEL") or os.environ.get("STT_MODEL", "small")
    return os.environ.get("STT_MODEL", "small")


def _build_transcribe_kwargs(mode: str) -> dict[str, object]:
    transcribe_kwargs: dict[str, object] = {
        "beam_size": int(os.environ.get("STT_BEAM_SIZE", "8")),
        "best_of": int(os.environ.get("STT_BEST_OF", "5")),
        "patience": _parse_float_env("STT_PATIENCE", 1.2),
        "temperature": _parse_float_env("STT_TEMPERATURE", 0.0),
        "vad_filter": _parse_bool_env("STT_VAD_FILTER", True),
        "task": "transcribe",
        "condition_on_previous_text": mode != "live",
        "initial_prompt": os.environ.get(
            "STT_INITIAL_PROMPT",
            "以下内容是普通话的简体中文指令，请使用简体中文输出识别结果。",
        ),
        "compression_ratio_threshold": _parse_float_env("STT_COMPRESSION_RATIO_THRESHOLD", 2.4),
        "log_prob_threshold": _parse_float_env("STT_LOG_PROB_THRESHOLD", -1.0),
        "no_speech_threshold": _parse_float_env("STT_NO_SPEECH_THRESHOLD", 0.45),
    }

    transcribe_kwargs["vad_parameters"] = {
        "min_silence_duration_ms": int(os.environ.get("STT_MIN_SILENCE_MS", "400")),
        "speech_pad_ms": int(os.environ.get("STT_SPEECH_PAD_MS", "200")),
    }

    language = os.environ.get("STT_LANGUAGE", "zh").strip()
    if language:
        transcribe_kwargs["language"] = language

    return transcribe_kwargs


def _resolve_audio_path(audio_path: str) -> Path:
    raw_path = _strip_matching_quotes(audio_path.strip())
    if not raw_path:
        raise ValueError("用法: /voice <音频文件路径>")

    resolved_path = Path(raw_path).expanduser()
    if not resolved_path.is_absolute():
        resolved_path = Path.cwd() / resolved_path
    resolved_path = resolved_path.resolve()

    if not resolved_path.exists():
        raise FileNotFoundError(f"音频文件不存在: {resolved_path}")
    if not resolved_path.is_file():
        raise ValueError(f"音频路径不是文件: {resolved_path}")

    return resolved_path


def _transcribe_path(audio_path: Path, *, allow_empty: bool, mode: str) -> str:
    model = _get_whisper_model(_get_model_name(mode))
    transcribe_kwargs = _build_transcribe_kwargs(mode)

    segments, _info = model.transcribe(str(audio_path), **transcribe_kwargs)
    transcript = "".join(segment.text for segment in segments).strip()
    if not transcript and not allow_empty:
        raise RuntimeError("语音转文字结果为空")

    return transcript


def transcribe_audio_file(audio_path: str) -> str:
    load_project_env()
    return _transcribe_path(_resolve_audio_path(audio_path), allow_empty=False, mode="final")


def _write_temp_wav(audio_frames, sample_rate: int) -> str:
    import numpy as np

    audio_array = np.concatenate(audio_frames, axis=0)
    audio_array = np.squeeze(audio_array)
    peak = float(np.max(np.abs(audio_array))) if audio_array.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(audio_array)))) if audio_array.size else 0.0
    target_rms = _parse_float_env("STT_TARGET_RMS", 0.18)
    max_gain = _parse_float_env("STT_MAX_GAIN", 8.0)
    if rms > 1e-6 and peak > 1e-6:
        gain = min(target_rms / rms, max_gain, 0.98 / peak)
        if gain > 1.0:
            audio_array = audio_array * gain
    audio_array = np.clip(audio_array, -1.0, 1.0)
    pcm16 = (audio_array * 32767.0).astype(np.int16)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
        temp_path = temp_file.name

    with wave.open(temp_path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm16.tobytes())

    return temp_path


def _transcribe_audio_frames(audio_frames, sample_rate: int) -> str:
    temp_path = _write_temp_wav(audio_frames, sample_rate)
    try:
        return _transcribe_path(Path(temp_path), allow_empty=True, mode="live")
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def record_and_transcribe_live() -> str:
    load_project_env()

    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError(
            "sounddevice is not installed. Run `python -m pip install sounddevice` first."
        ) from exc

    sample_rate = int(os.environ.get("STT_SAMPLE_RATE", "16000"))
    chunk_seconds = float(os.environ.get("STT_CHUNK_SECONDS", "3"))
    chunk_frames = max(1, int(sample_rate * chunk_seconds))
    audio_queue: queue.Queue = queue.Queue()
    stop_event = threading.Event()
    transcript_parts: list[str] = []
    all_frames = []
    pending_frames = []
    pending_count = 0

    def _on_audio(indata, frames, _time, status) -> None:
        if status:
            print(f"[Record Warning] {status}")
        audio_queue.put(indata.copy())

    def _wait_for_stop() -> None:
        input()
        stop_event.set()

    print("开始录音，直接说话；按回车结束。")
    print("[Live STT] ", end="", flush=True)

    stopper = threading.Thread(target=_wait_for_stop, daemon=True)
    stopper.start()

    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        callback=_on_audio,
    ):
        while not stop_event.is_set() or not audio_queue.empty():
            try:
                chunk = audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            pending_frames.append(chunk)
            all_frames.append(chunk)
            pending_count += len(chunk)
            if pending_count < chunk_frames:
                continue

            text = _transcribe_audio_frames(pending_frames, sample_rate)
            if text:
                transcript_parts.append(text)
                print(text, end="", flush=True)
            pending_frames = []
            pending_count = 0

    if pending_frames:
        text = _transcribe_audio_frames(pending_frames, sample_rate)
        if text:
            transcript_parts.append(text)
            print(text, end="", flush=True)

    print()
    full_text = ""
    if all_frames:
        temp_path = _write_temp_wav(all_frames, sample_rate)
        try:
            full_text = _transcribe_path(Path(temp_path), allow_empty=True, mode="final").strip()
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass
    if not full_text:
        full_text = "".join(transcript_parts).strip()
    if not full_text:
        raise RuntimeError("麦克风录音未识别到有效文字")
    return full_text


def normalize_user_input(user_input: str) -> str:
    lowered = user_input.lower()
    for prefix in VOICE_COMMAND_PREFIXES:
        command_prefix = f"{prefix} "
        if lowered.startswith(command_prefix):
            transcript = transcribe_audio_file(user_input[len(command_prefix):])
            print(f"[Voice -> Text] {transcript}")
            return transcript

    if lowered in RECORD_COMMAND_PREFIXES:
        transcript = record_and_transcribe_live()
        print(f"[Voice Final] {transcript}")
        return transcript

    if lowered in VOICE_COMMAND_PREFIXES:
        raise ValueError("用法: /voice <音频文件路径>")

    return user_input


async def main():
    load_project_env()
    runtime = AgentRuntime()
    await runtime.initialize()
    thread_id = os.environ.get("CLI_THREAD_ID", "1")

    while True:
        user_input = input("用户: ").strip()
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("系统退出。")
            break

        try:
            user_input = normalize_user_input(user_input)
        except Exception as exc:
            print(f"[Voice Error] {exc}")
            continue

        async for chunk in runtime.stream_reply(user_input, thread_id=thread_id):
            print(chunk, end="", flush=True)

        print()


if __name__ == "__main__":
    asyncio.run(main())
