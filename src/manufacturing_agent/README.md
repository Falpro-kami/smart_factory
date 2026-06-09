# manufacturing_agent

`manufacturing_agent/` 是面向智能产线的 Agent 与数字孪生演示项目。项目把产线 ontology、MySQL 业务数据、Neo4j 图数据、MCP 工具、FastAPI 后端和前端控制台组合在一起，用于展示设备、订单、物料、产品、工艺、AGV 运输任务、推理规则、生产报告和产线管控 Agent 会话。

## 项目组成

```text
manufacturing_agent/
├─ agent_core.py                 # Agent 核心逻辑，CLI 和后端共同复用
├─ main.py                       # 终端版 Agent 入口
├─ agent_backend_adapter/        # FastAPI 后端适配层
├─ digital-twin-frontend/        # 数字孪生 ontology 前端控制台
├─ mcp-neo4j-cypher/             # Neo4j MCP 服务
├─ mysql_mcp_server/             # MySQL MCP 服务
├─ mysql_mcp_server_pro/         # MySQL MCP 增强服务
├─ split_mcp_server/             # 订单拆分和推理相关 MCP 工具
├─ skills/                       # Agent 技能目录
├─ .env.example                  # 环境变量模板
├─ requirements.txt              # Python 依赖
└─ pyproject.toml                # 项目元数据
```

## 当前目录状态

- 当前项目根目录为 `E:\codenew\smart_factory\src\manufacturing_agent`。
- 旧嵌套目录 `E:\codenew\mujoko_ur5e` 已删除，后续不要再引用旧路径。
- 旧机械臂/MuJoCo/UR10e 控制相关目录和工具已从当前项目链路移除，Agent 只加载智能产线相关 MCP 工具和 skills。
- `.history`、`.runtime`、`__pycache__`、RocketMQ 运行时 store/logs 不属于源码，不应纳入搜索、提交或上下文交接。

## 技术栈

- Agent：`LangChain`、`LangGraph`、`langchain-openai`、`langchain-mcp-adapters`
- 后端：`FastAPI`、`uvicorn`、`pymysql`
- 前端：原生 `HTML`、`CSS`、`JavaScript`、ES Modules
- 数据：`MySQL`、`Neo4j`
- 工具协议：`MCP`

## 开发约定

本项目已移除 `vexp` 代码索引工具，后续开发、排查和维护不再依赖 `run_pipeline` 或 vexp MCP。需要定位代码时，直接使用仓库内文件、`rg`、Git 和项目本地脚本进行检查。

搜索或交接上下文时，避免读取大体积或低价值目录：

```powershell
rg -n "关键词" E:\codenew\smart_factory\src\manufacturing_agent `
  -g "!**/.history/**" `
  -g "!**/.runtime/**" `
  -g "!**/__pycache__/**" `
  -g "!**/rocketmq/store/**" `
  -g "!**/rocketmq/logs/**" `
  -g "!**/uv.lock"
```

VS Code 已在 `.vscode/settings.json` 中排除上述目录，Git 已在 `.gitignore` 中忽略运行时和缓存文件。

## 环境准备

建议在项目根目录执行：

```powershell
cd E:\codenew\smart_factory\src\manufacturing_agent
python -m pip install -r requirements.txt
```

复制 `.env.example` 为 `.env`，并填写真实配置。核心变量包括：

```env
LLM_API_KEY=
AGENT_MODEL=deepseek-chat
AGENT_BASE_URL=https://api.deepseek.com
AGENT_TEMPERATURE=0.2
AGENT_BACKEND_HOST=127.0.0.1
AGENT_BACKEND_PORT=8000
AGENT_CORS_ORIGINS=*

MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=
MYSQL_PASSWORD=
MYSQL_DATABASE=

NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=
NEO4J_DATABASE=neo4j
```

`.env` 由项目根目录统一提供，`main.py`、`agent_core.py`、`agent_backend_adapter/` 和 MCP 相关模块都会优先读取这里的配置。

## 启动方式

### 一键启动整个系统

在项目根目录执行：

```powershell
cd E:\codenew\smart_factory\src\manufacturing_agent
.\start_system.ps1
```

如果 PowerShell 执行策略限制 `.ps1`，使用包装脚本：

```powershell
.\start_system.bat
```

默认会分别启动：

- RocketMQ NameServer：后台隐藏运行
- RocketMQ Broker：后台隐藏运行
- FastAPI 后端：后台隐藏运行，`http://127.0.0.1:8000`
- 数字孪生前端：后台隐藏运行，`http://127.0.0.1:5175`
- 调度器服务：后台隐藏运行，订阅 `DeviceEventReport` 并向 `WorkOrderDeliver` 下发满足条件的工单
- 终端交互智能体 `main.py`：保留唯一可见交互窗口

后台服务日志写入：

```text
.runtime/logs/
```

可选参数：

```powershell
.\start_system.ps1 -OpenBrowser
.\start_system.ps1 -NoAgent
.\start_system.ps1 -NoBackend
.\start_system.ps1 -NoFrontend
.\start_system.ps1 -NoRocketMQ
.\start_system.ps1 -NoRocketMQServer
.\start_system.ps1 -NoRocketMQConsumer
```

停止整个系统：

```powershell
.\stop_system.ps1
```

如果 PowerShell 执行策略限制 `.ps1`：

```powershell
.\stop_system.bat
```

停止脚本会优先调用 RocketMQ 自带 shutdown，并关闭一键启动脚本记录的各服务窗口。

### 1. 启动后端

```powershell
cd E:\codenew\smart_factory\src\manufacturing_agent
python -m agent_backend_adapter.app
```

默认后端地址：

```text
http://127.0.0.1:8000
```

健康检查：

```powershell
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health).Content
```

预期返回：

```json
{"ok": true, "service": "agent-backend-adapter"}
```

### 2. 启动数字孪生前端

```powershell
cd E:\codenew\smart_factory\src\manufacturing_agent\digital-twin-frontend
python -m http.server 5175 --bind 127.0.0.1
```

浏览器访问：

```text
http://127.0.0.1:5175
```

前端固定使用 `5175` 端口。审查、演示和后续开发均以该地址为准，避免多个前端服务导致缓存页面或端口访问混乱。

### 3. 运行终端版 Agent

如果只想验证 Agent 核心逻辑，可以运行：

```powershell
cd E:\codenew\smart_factory\src\manufacturing_agent
python main.py
```

输入 `exit` 可退出终端会话。

## 后端接口

`agent_backend_adapter/app.py` 提供以下主要接口：

```text
GET  /
GET  /health
POST /api/chat
POST /api/chat/stop

GET  /api/digital-twin/ontology/live
GET  /api/digital-twin/topologies
GET  /api/digital-twin/devices
GET  /api/digital-twin/store
GET  /api/digital-twin/data
GET  /api/digital-twin/agv/tasks
GET  /api/digital-twin/schema
GET  /api/digital-twin/entities/{entity_type}
GET  /api/digital-twin/entities/{entity_type}/{entity_id}
```

接口职责：

- `/api/chat`：产线管控 Agent 对话接口，支持普通 JSON 和 SSE 流式返回。
- `/api/chat/stop`：停止当前流式生成。
- `/api/digital-twin/ontology/live`：返回 ontology 元数据、类拓扑、实例图和实体目录。
- `/api/digital-twin/topologies`：返回前端拓扑视图数据。
- `/api/digital-twin/devices`：读取 MySQL `device` 数据库中的设备、工站、仓库和 AGV 实例。
- `/api/digital-twin/store`：读取 MySQL `store` 相关物料库存数据。
- `/api/digital-twin/data`：读取 MySQL `Data` 数据库中的订单工单历史、设备运行历史、质检追溯和 AGV 任务汇总，并执行 ontology 规则推理。
- `/api/digital-twin/agv/tasks`：读取 MySQL `order.work_orders` 中的 AGV 运输工单，返回 AGV 运输任务和状态统计。
- `/api/digital-twin/entities/*`：按实体类型读取列表或详情，供前端属性视图和全局搜索使用。

## 数字孪生前端

`digital-twin-frontend/` 是当前主要演示界面，使用原生 HTML、CSS 和 ES Modules 构建。入口文件为：

```text
digital-twin-frontend/index.html
digital-twin-frontend/app.mjs
digital-twin-frontend/styles.css
```

注意：当前 `index.html` 加载的是根目录 `app.mjs`，不是 `js/app.mjs`。修改主界面时优先检查 `digital-twin-frontend/app.mjs`。

主要功能：

- `Ontology / Classes`：查看智能产线本体类拓扑。
- `Ontology / Relations`：查看和维护本体类之间的关系定义。
- `Ontology / Devices`：查看设备实例和设备当前任务。
- `Ontology / Orders`：查看当前执行或等待执行的订单与拆分工单。
- `Ontology / Materials`、`Products`、`Crafts`、`Processes`：查看对应实体实例和属性。
- `Tools / Global Search`：跨设备、订单、工单、物料、产品、工序和工艺统一检索。
- `Tools / Reasoning Rules`：查看 ontology 推理规则模板和后端实时规则。
- `Tools / Reports`：查看和生成生产分析报告。
- `AI Agent / Production Agent`：通过 `/api/chat` 与产线管控 Agent 交互。
- `DATA`：查看订单工单历史、设备运行历史和质检追溯数据。

更多前端细节见：

```text
digital-twin-frontend/README.md
```

## 订单、工单与 AGV 任务流程

当前前后端按以下流程组织数据：

1. 订单下发后写入 MySQL `Data.order_work_order_history`。
2. 订单按工序拆分为多条工单，每条工单记录目标工站、开始/结束时间和执行状态。
3. 后端根据工单顺序生成 AGV 小车运输任务，并写入 MySQL `order.work_orders` 中的 AGV 运输工单。
4. 前端读取 `/api/digital-twin/agv/tasks` 后，将等待中、运输中的 AGV 任务同步到 `Ontology / Devices` 的设备当前任务。
5. 已完成、已取消的 AGV 任务从设备当前任务移出，并归并到 `DATA / Devices` 的设备运行历史中。

AGV 任务生成规则：

- 首道工序：从仓库将物料输送到目标工站。
- 中间工序：上一道工序完成后，将半成品从上一工站运输到下一工站。
- 末道工序：工站完成后，将产品运输到成品仓库。

## Ontology 推理规则

后端在 `agent_backend_adapter/reasoning_service/` 中维护推理模块：

```text
reasoning_service/
├─ product_reasoner.py
├─ order_reasoner.py
├─ device_reasoner.py
├─ agv_reasoner.py
├─ material_reasoner.py
├─ quality_reasoner.py
└─ rule_result.py
```

当前规则覆盖：

- 产品工艺推理：产品通过 `HAS_STEP` 找到工艺流程和工艺步骤。
- 工单拆分推理：订单按产品工艺流程拆分为多个工单。
- 设备匹配推理：工艺根据 `CAN_EXECUTE` 匹配可执行设备。
- AGV 任务推理：首道工序、相邻工单设备不同或末道入库时生成运输任务。
- 库存约束推理：需求数量大于库存或缺少物料批次时不允许执行。
- 质量规则推理：质检不合格进入返工或异常判断。
- 状态约束推理：设备必须存在于 ontology 设备目录，且非故障、离线、维护才可分配。

推理结果会写入 MySQL `Data.reasoning_results`，并通过 `/api/digital-twin/data` 返回给前端和 Agent 使用。

## MCP 工具

项目包含多类 MCP 服务：

- `mcp-neo4j-cypher/`：向 Agent 暴露 Neo4j schema 和 Cypher 查询能力。
- `mysql_mcp_server/`、`mysql_mcp_server_pro/`：向 Agent 暴露 MySQL 查询、表结构和健康检查能力。
- `split_mcp_server/`：暴露订单拆分和推理相关工具。

`split_mcp_server` 中与推理相关的工具包括：

- `split_product_order`
- `check_order_feasibility`
- `infer_agv_tasks`
- `check_material_availability`
- `check_device_assignment`

常规工单下发优先走 `WorkOrderScheduler`，只有明确需要绕过调度时才使用底层 `WorkOrderDelivery`。

## 验证流程

推荐按以下顺序验证完整链路：

1. 启动后端：`python -m agent_backend_adapter.app`。
2. 访问 `http://127.0.0.1:8000/health`，确认后端正常。
3. 启动前端：`python -m http.server 5175 --bind 127.0.0.1`。
4. 打开 `http://127.0.0.1:5175`。
5. 确认右上角 `API Base` 为 `http://127.0.0.1:8000`。
6. 进入 `Ontology / Devices`，确认设备实例和设备当前任务正常。
7. 进入 `DATA / Devices`，确认已完成或已取消任务按设备聚合到运行历史。
8. 进入 `Tools / Reasoning Rules`，确认推理规则卡片正常展示。
9. 进入 `Tools / Global Search`，用设备、订单、工单、物料、产品、工序或工艺关键词验证检索。
10. 进入 `AI Agent / Production Agent`，通过 `/api/chat` 验证 Agent 对话。

常用检查命令：

```powershell
node --check .\digital-twin-frontend\app.mjs
node --check .\digital-twin-frontend\js\config\navigation.mjs
Get-NetTCPConnection -LocalPort 5175 -ErrorAction SilentlyContinue
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/digital-twin/agv/tasks).Content
```

`/api/digital-twin/agv/tasks` 预期包含：

```text
ok: true
database: AGV
table: tasks
tasks: [...]
summary: { total, waiting, transporting, completed, cancelled }
```

## 修改注意事项

- Agent 核心逻辑优先修改 `agent_core.py`，CLI 和后端都会复用它。
- 后端接口、端口、数据结构、推理规则或前端展示规则变化时，同步更新本 README 和 `digital-twin-frontend/README.md`。
- 数字孪生前端端口统一保持 `5175`。
- 前端文案以中文为主，保留必要技术名词，如 `Ontology`、`Neo4j`、`MySQL`、`Agent`、`API Base`。
- 设备属性视图只展示设备资产数据；任务、运输、时间和负载信息应放在设备当前任务或设备运行历史中。
- 修改前端模板字符串后，执行 `node --check` 做语法检查。
- 不要恢复旧 `mujoko_ur5e` 路径、`robotcontrol`、`ur10e_2f85` 或机械臂抓取 skill；这些内容已从当前智能产线演示范围移除。


