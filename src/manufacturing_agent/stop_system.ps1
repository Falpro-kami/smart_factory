param(
    [switch]$Force
)

$ErrorActionPreference = "SilentlyContinue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeDir = Join-Path $Root ".runtime"
$ProcessFile = Join-Path $RuntimeDir "system-processes.json"
$RocketMqHome = Join-Path $Root "rocketmq\rocketmq-all-5.3.2-bin-release"
$MqShutdown = Join-Path $RocketMqHome "bin\mqshutdown.cmd"
$ServiceTitles = @(
    "SIMENS RocketMQ NameServer",
    "SIMENS RocketMQ Broker",
    "SIMENS Backend",
    "SIMENS Digital Twin Frontend",
    "SIMENS Scheduler Service",
    "SIMENS Interactive Agent"
)

function Stop-ProcessTree {
    param([int]$ProcessId)

    if ($ProcessId -eq $PID) {
        return
    }

    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-ProcessTree -ProcessId ([int]$_.ProcessId) }

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process) {
        return
    }

    if ($Force) {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    } else {
        Stop-Process -Id $ProcessId -ErrorAction SilentlyContinue
    }
}

function Stop-ProjectCommandProcesses {
    $projectRoot = [regex]::Escape($Root)
    $titlePattern = ($ServiceTitles | ForEach-Object { [regex]::Escape($_) }) -join "|"
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ProcessId -ne $PID -and
            $_.CommandLine -and
            $_.CommandLine -match $projectRoot -and
            ($_.CommandLine -match $titlePattern -or $_.CommandLine -match "agent_backend_adapter\.app|http\.server 5175|digital-twin-frontend.*serve\.py|scheduler_service\.py|main\.py")
        } |
        ForEach-Object { Stop-ProcessTree -ProcessId ([int]$_.ProcessId) }
}

function Stop-ProjectPortProcess {
    param(
        [int]$Port,
        [string]$CommandPattern
    )

    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object {
            $processId = [int]$_
            if ($processId -eq $PID) {
                return
            }
            $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
            if ($process -and $process.CommandLine -match $CommandPattern) {
                Stop-ProcessTree -ProcessId $processId
            }
        }
}

if (Test-Path -LiteralPath $MqShutdown) {
    $env:ROCKETMQ_HOME = $RocketMqHome
    & $MqShutdown broker | Out-Null
    & $MqShutdown namesrv | Out-Null
}

$records = @()
if (Test-Path -LiteralPath $ProcessFile) {
    $raw = Get-Content -LiteralPath $ProcessFile -Raw -Encoding UTF8
    if ($raw.Trim()) {
        $loaded = $raw | ConvertFrom-Json
        if ($loaded -is [array]) {
            $records = $loaded
        } else {
            $records = @($loaded)
        }
    }
}

foreach ($record in $records) {
    if ($record.pid) {
        Stop-ProcessTree -ProcessId ([int]$record.pid)
    }
}

foreach ($title in $ServiceTitles) {
    Get-Process -Name powershell -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -eq $title } |
        ForEach-Object { Stop-ProcessTree -ProcessId $_.Id }
}

Stop-ProjectCommandProcesses
Stop-ProjectPortProcess -Port 8000 -CommandPattern "agent_backend_adapter\.app"
Stop-ProjectPortProcess -Port 5175 -CommandPattern "http\.server 5175|serve\.py"

Remove-Item -LiteralPath $ProcessFile -Force -ErrorAction SilentlyContinue
Write-Host "Stopped SIMENS system components."
