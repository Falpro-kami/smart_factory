#!/usr/bin/env python3
import json
import subprocess


def main():
    process = subprocess.Popen(
        ["python3", "src/moveitpy_tools/moveitpy_server.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )

    print(process.stdout.readline().strip())

    for command in (
        {"command": "ping"},
        {"command": "HOME"},
        {"command": "execute_last"},
        {"command": "quit"},
    ):
        process.stdin.write(json.dumps(command) + "\n")
        process.stdin.flush()
        print(process.stdout.readline().strip())


if __name__ == "__main__":
    main()
