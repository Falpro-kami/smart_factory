param(
    [switch]$NoAgent,
    [switch]$NoBackend,
    [switch]$NoFrontend,
    [switch]$NoRocketMQ,
    [switch]$NoRocketMQServer,
    [switch]$NoRocketMQConsumer,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = if ($env:PYTHON_EXE) { $env:PYTHON_EXE } else { "python" }
$RuntimeDir = Join-Path $Root ".runtime"
$LogDir = Join-Path $RuntimeDir "logs"
$ProcessFile = Join-Path $RuntimeDir "system-processes.json"
$StartedProcesses = @()
$ServiceTitles = @(
    "manufacturing_agent RocketMQ NameServer",
    "manufacturing_agent RocketMQ Broker",
    "manufacturing_agent Backend",
    "manufacturing_agent Digital Twin Frontend",
    "manufacturing_agent Scheduler Service",
    "manufacturing_agent Interactive Agent"
)

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Quote-PsString {
    param([string]$Value)
    return "'" + ($Value -replace "'", "''") + "'"
}

function Start-SystemProcess {
    param(
        [string]$Title,
        [string]$WorkingDirectory,
        [string]$Command,
        [switch]$Visible
    )

    $quotedTitle = Quote-PsString $Title
    $quotedWorkdir = Quote-PsString $WorkingDirectory
    $logBase = ($Title -replace "[^A-Za-z0-9_-]", "_").Trim("_")
    if (-not $logBase) {
        $logBase = "service"
    }
    $stdoutLog = Join-Path $LogDir "$logBase.out.log"
    $stderrLog = Join-Path $LogDir "$logBase.err.log"
    $quotedStdoutLog = Quote-PsString $stdoutLog
    $quotedStderrLog = Quote-PsString $stderrLog
    $fullCommand = "`$Host.UI.RawUI.WindowTitle = $quotedTitle; Set-Location -LiteralPath $quotedWorkdir; $Command"

    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        $fullCommand
    )
    if ($Visible) {
        $arguments = @("-NoExit") + $arguments
        $process = Start-Process -FilePath "powershell.exe" -PassThru -ArgumentList $arguments
    } else {
        $process = Start-Process -FilePath "powershell.exe" `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutLog `
            -RedirectStandardError $stderrLog `
            -PassThru `
            -ArgumentList $arguments
    }

    $script:StartedProcesses += [pscustomobject]@{
        title = $Title
        pid = $process.Id
        visible = [bool]$Visible
        stdout_log = $stdoutLog
        stderr_log = $stderrLog
        started_at = (Get-Date).ToString("s")
    }
}

function Stop-ProcessTree {
    param([int]$ProcessId)

    if ($ProcessId -eq $PID) {
        return
    }

    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-ProcessTree -ProcessId ([int]$_.ProcessId) }

    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Stop-RecordedProcesses {
    if (-not (Test-Path -LiteralPath $ProcessFile)) {
        return
    }

    $raw = Get-Content -LiteralPath $ProcessFile -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
    if (-not $raw -or -not $raw.Trim()) {
        return
    }

    $loaded = $raw | ConvertFrom-Json
    $records = if ($loaded -is [array]) { $loaded } else { @($loaded) }
    foreach ($record in $records) {
        if ($record.pid) {
            Stop-ProcessTree -ProcessId ([int]$record.pid)
        }
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

function Stop-StaleSystemProcesses {
    Stop-RecordedProcesses
    Stop-ProjectCommandProcesses
    Stop-ProjectPortProcess -Port 8000 -CommandPattern "agent_backend_adapter\.app"
    Stop-ProjectPortProcess -Port 5175 -CommandPattern "http\.server 5175|serve\.py"
    Remove-Item -LiteralPath $ProcessFile -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
}

function Wait-HttpEndpoint {
    param(
        [string]$Name,
        [string]$Url,
        [int]$TimeoutSeconds = 60,
        [string]$ErrorLog = ""
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                Write-Host "$Name ready: $Url"
                return $true
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline)

    Write-Warning "$Name did not become ready within $TimeoutSeconds seconds: $Url"
    if ($ErrorLog -and (Test-Path -LiteralPath $ErrorLog)) {
        Write-Warning "$Name stderr tail:"
        Get-Content -LiteralPath $ErrorLog -Tail 40 -ErrorAction SilentlyContinue | ForEach-Object { Write-Warning $_ }
    }
    return $false
}

Stop-StaleSystemProcesses

$pythonPathParts = @(
    $Root,
    (Join-Path $Root "mcp-neo4j-cypher\src"),
    (Join-Path $Root "mysql_mcp_server_pro\src"),
    (Join-Path $Root "split_mcp_server\src")
)
if ($env:PYTHONPATH) {
    $pythonPathParts += $env:PYTHONPATH
}
$pythonPath = [string]::Join([System.IO.Path]::PathSeparator, $pythonPathParts)
$setPythonPath = "`$env:PYTHONPATH = " + (Quote-PsString $pythonPath) + "; "

$rocketMqDir = Join-Path $Root "rocketmq"

if (-not $NoRocketMQ -and -not $NoRocketMQServer) {
    Start-SystemProcess `
        -Title "manufacturing_agent RocketMQ NameServer" `
        -WorkingDirectory $rocketMqDir `
        -Command "& .\start-namesrv.ps1"

    Start-Sleep -Seconds 3

    Start-SystemProcess `
        -Title "manufacturing_agent RocketMQ Broker" `
        -WorkingDirectory $rocketMqDir `
        -Command "& .\start-broker.ps1"

    Start-Sleep -Seconds 5
}

if (-not $NoBackend) {
    Start-SystemProcess `
        -Title "manufacturing_agent Backend" `
        -WorkingDirectory $Root `
        -Command ($setPythonPath + "& " + (Quote-PsString $Python) + " -m agent_backend_adapter.app")
}

if (-not $NoFrontend) {
    Start-SystemProcess `
        -Title "manufacturing_agent Digital Twin Frontend" `
        -WorkingDirectory (Join-Path $Root "digital-twin-frontend") `
        -Command ("& " + (Quote-PsString $Python) + " .\serve.py")
}

if (-not $NoRocketMQ -and -not $NoRocketMQConsumer) {
    Start-SystemProcess `
        -Title "manufacturing_agent Scheduler Service" `
        -WorkingDirectory $Root `
        -Command ($setPythonPath + "& " + (Quote-PsString $Python) + " .\split_mcp_server\src\split_mcp_server\scheduler_service.py")
}

if (-not $NoAgent) {
    Start-SystemProcess `
        -Title "manufacturing_agent Interactive Agent" `
        -WorkingDirectory $Root `
        -Command ($setPythonPath + "& " + (Quote-PsString $Python) + " .\main.py") `
        -Visible
}

if ($OpenBrowser -and -not $NoFrontend) {
    Start-Process "http://127.0.0.1:5175" | Out-Null
}

$StartedProcesses | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ProcessFile -Encoding UTF8

$backendReady = $true
$frontendReady = $true
if (-not $NoBackend) {
    $backendReady = Wait-HttpEndpoint `
        -Name "Backend" `
        -Url "http://127.0.0.1:8000/health" `
        -TimeoutSeconds 75 `
        -ErrorLog (Join-Path $LogDir "manufacturing_agent_Backend.err.log")
}
if (-not $NoFrontend) {
    $frontendReady = Wait-HttpEndpoint `
        -Name "Frontend" `
        -Url "http://127.0.0.1:5175/app.mjs" `
        -TimeoutSeconds 30 `
        -ErrorLog (Join-Path $LogDir "manufacturing_agent_Digital_Twin_Frontend.err.log")
}

Write-Host "Started manufacturing_agent system components."
Write-Host "Backend:  http://127.0.0.1:8000"
Write-Host "Frontend: http://127.0.0.1:5175"
Write-Host "Background logs: $LogDir"
Write-Host "Stop all: .\stop_system.ps1"

if (-not $backendReady -or -not $frontendReady) {
    exit 1
}
