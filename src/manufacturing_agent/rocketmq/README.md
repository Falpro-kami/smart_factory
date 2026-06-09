# RocketMQ Local Server

This directory contains a native Windows RocketMQ setup for local minimum validation.

## Layout

```text
rocketmq/
├─ rocketmq-all-5.3.2-bin-release/      # ignored binary package directory
├─ rocketmq-all-5.3.2-bin-release.zip   # ignored downloaded package
├─ broker.conf
├─ start-namesrv.ps1
├─ start-broker.ps1
└─ stop-rocketmq.ps1
```

## Current Host

The broker is configured for the current upper PC WLAN address:

```text
192.168.1.10
```

If the upper PC IP changes, update these fields:

```text
broker.conf: brokerIP1
broker.conf: namesrvAddr
start-broker.ps1: $NameServer
```

## Start

Open terminal 1:

```powershell
cd E:\codenew\smart_factory\src\manufacturing_agent\rocketmq
.\start-namesrv.ps1
```

Open terminal 2:

```powershell
cd E:\codenew\smart_factory\src\manufacturing_agent\rocketmq
.\start-broker.ps1
```

## Check

On the upper PC:

```powershell
Test-NetConnection 192.168.1.10 -Port 9876
Test-NetConnection 192.168.1.10 -Port 10911
```

On each device PC:

```powershell
Test-NetConnection 192.168.1.10 -Port 9876
Test-NetConnection 192.168.1.10 -Port 10911
```

Both checks must return `TcpTestSucceeded: True`.

## Stop

```powershell
.\stop-rocketmq.ps1
```

