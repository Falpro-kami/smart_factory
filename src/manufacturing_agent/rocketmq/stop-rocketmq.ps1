$ErrorActionPreference = "Continue"

$RocketMqHome = Join-Path $PSScriptRoot "rocketmq-all-5.3.2-bin-release"
$env:ROCKETMQ_HOME = $RocketMqHome

if (-not $env:JAVA_HOME) {
    $env:JAVA_HOME = "E:\Java_JDK17\jdk-17"
}

& (Join-Path $RocketMqHome "bin\mqshutdown.cmd") broker
& (Join-Path $RocketMqHome "bin\mqshutdown.cmd") namesrv
