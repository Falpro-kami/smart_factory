$ErrorActionPreference = "Stop"

$RocketMqHome = Join-Path $PSScriptRoot "rocketmq-all-5.3.2-bin-release"
$env:ROCKETMQ_HOME = $RocketMqHome

if (-not $env:JAVA_HOME) {
    $env:JAVA_HOME = "E:\Java_JDK17\jdk-17"
}

Write-Host "ROCKETMQ_HOME=$RocketMqHome"
Write-Host "JAVA_HOME=$env:JAVA_HOME"
Write-Host "Starting RocketMQ NameServer on 0.0.0.0:9876 ..."

& (Join-Path $RocketMqHome "bin\mqnamesrv.cmd")
