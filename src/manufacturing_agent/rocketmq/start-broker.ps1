$ErrorActionPreference = "Stop"

$RocketMqHome = Join-Path $PSScriptRoot "rocketmq-all-5.3.2-bin-release"
$BrokerConf = Join-Path $PSScriptRoot "broker.conf"
$RuntimeDir = Join-Path (Split-Path $PSScriptRoot -Parent) ".runtime"
$RuntimeBrokerConf = Join-Path $RuntimeDir "rocketmq-broker.conf"
$NameServer = if ($env:ROCKETMQ_NAMESRV_ADDR) { $env:ROCKETMQ_NAMESRV_ADDR } else { "127.0.0.1:9876" }
$env:ROCKETMQ_HOME = $RocketMqHome
$env:NAMESRV_ADDR = $NameServer

if (-not $env:JAVA_HOME) {
    $env:JAVA_HOME = "E:\Java_JDK17\jdk-17"
}

$BaseConfigText = Get-Content -LiteralPath $BrokerConf -Raw
$ConfiguredBrokerIp = ""
if ($BaseConfigText -match "(?m)^brokerIP1=(.+)$") {
    $ConfiguredBrokerIp = $Matches[1].Trim()
}

$BrokerIp = $env:ROCKETMQ_BROKER_IP
if (-not $BrokerIp -and $ConfiguredBrokerIp) {
    $ConfiguredAddress = Get-NetIPAddress -AddressFamily IPv4 -IPAddress $ConfiguredBrokerIp -ErrorAction SilentlyContinue
    if ($ConfiguredAddress) {
        $BrokerIp = $ConfiguredBrokerIp
    }
}
if (-not $BrokerIp) {
    $BrokerIp = Get-NetIPConfiguration |
        Where-Object {
            $_.IPv4Address.IPAddress -and
            $_.IPv4DefaultGateway -and
            $_.IPv4Address.IPAddress -notlike "127.*" -and
            $_.IPv4Address.IPAddress -notlike "169.254.*" -and
            $_.IPv4Address.IPAddress -notlike "172.1[6-9].*" -and
            $_.IPv4Address.IPAddress -notlike "172.2[0-9].*" -and
            $_.IPv4Address.IPAddress -notlike "172.3[0-1].*"
        } |
        Select-Object -ExpandProperty IPv4Address -First 1 |
        Select-Object -ExpandProperty IPAddress -First 1
}
if (-not $BrokerIp) {
    $BrokerIp = Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.IPAddress -notlike "172.1[6-9].*" -and
            $_.IPAddress -notlike "172.2[0-9].*" -and
            $_.IPAddress -notlike "172.3[0-1].*"
        } |
        Select-Object -ExpandProperty IPAddress -First 1
}
if (-not $BrokerIp) {
    $BrokerIp = "127.0.0.1"
}

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
$configText = $BaseConfigText
$configText = $configText -replace "(?m)^brokerIP1=.*$", "brokerIP1=$BrokerIp"
$configText = $configText -replace "(?m)^namesrvAddr=.*$", "namesrvAddr=$NameServer"
Set-Content -LiteralPath $RuntimeBrokerConf -Value $configText -Encoding ASCII

Write-Host "ROCKETMQ_HOME=$RocketMqHome"
Write-Host "JAVA_HOME=$env:JAVA_HOME"
Write-Host "NAMESRV_ADDR=$NameServer"
Write-Host "BROKER_IP=$BrokerIp"
Write-Host "Starting RocketMQ Broker with config $RuntimeBrokerConf ..."

& (Join-Path $RocketMqHome "bin\mqbroker.cmd") -n $NameServer -c $RuntimeBrokerConf
