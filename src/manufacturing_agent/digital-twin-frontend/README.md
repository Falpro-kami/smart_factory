# 数字孪生 Ontology 前端

`digital-twin-frontend/` 是 manufacturing_agent 的轻量前端控制台，使用原生 HTML、CSS 和 ES Modules 构建。页面用于展示智能产线 ontology、本体类拓扑、设备/订单/物料/产品/工艺实例、设备状态、历史数据、报告模板以及产线管控 Agent 会话。

## 端口约定

前端固定使用：

```text
http://127.0.0.1:5175
```

前端只维护这一个本地访问端口。审查、演示和后续开发时均以该地址为准，避免出现多个前端服务、缓存页面不一致或访问错端口的问题。

## 启动方式

先启动后端服务：

```powershell
cd E:\codenew\smart_factory\src\manufacturing_agent
python -m agent_backend_adapter.app
```

默认后端地址：

```text
http://127.0.0.1:8000
```

再启动前端静态服务：

```powershell
cd E:\codenew\smart_factory\src\manufacturing_agent\digital-twin-frontend
python -m http.server 5175 --bind 127.0.0.1
```

浏览器访问：

```text
http://127.0.0.1:5175
```

## 功能概览

- `Ontology / Classes`：查看智能产线本体类拓扑，支持本体类、产品-工序、设备-工艺等视图。
- `Ontology / Relations`：查看和维护本体类之间的关系定义；推理规则不在 Relations 中展示。
- `Ontology / Devices`：查看设备实例和设备当前任务；当前任务只包含正在执行或等待执行的工站工单与 AGV 运输任务。
- `Ontology / Orders`：查看未整单结束的订单与拆分工单；部分工单已完成时仍保留在该订单下并更新工单状态。
- `Ontology / Materials`、`Products`、`Crafts`、`Processes`：查看对应实体实例列表和属性视图。
- `Tools / Global Search`：跨设备、订单、工单、物料、产品、工序和工艺统一检索，支持关键词、ID 或部分名称模糊匹配，并可按对象类型、状态、所属工站或工序过滤；结果可跳转到对应属性视图或拓扑图，查询行为会保存在页面 History 区域。
- `Tools / Reasoning Rules`：查看 ontology 推理规则参考模板和后端 `reasoning_service` 返回的实时规则，供产线管控 Agent 解释工单拆分、设备匹配、AGV 任务和异常判断时参考。
- `Tools / Reports`：查看和生成生产分析报告。
- `AI Agent / Production Agent`：打开全局底部 Agent 控制台，通过后端 `POST /api/chat` 与产线管控 Agent 交互；控制台浮在当前模块上方，不替换主内容页面，Agent 可参考 `Tools / Reasoning Rules` 的推理规则和 `Tools / Reports` 的报告模板。
- `DATA` 页面：查看整单已完成或已取消的订单工单历史、设备运行历史和质检追溯数据；设备运行历史按设备归档，点击设备卡片查看该设备运行条目，点击运行条目查看对应任务和相关订单信息。

## 订单到 AGV 任务流程

当前前后端按照以下工作流组织数据：

1. 订单下发后写入 MySQL `Data.order_work_order_history`。
2. 订单按工序拆分为多条工单，每条工单记录目标工站、开始/结束时间和执行状态。
3. 后端根据工单顺序生成 AGV 小车运输任务，并写入 MySQL `AGV.tasks`。
4. 前端读取 `/api/digital-twin/agv/tasks` 后，将等待中、运输中的 AGV 任务同步到 `Ontology / Devices` 的设备当前任务。
5. 已完成、已取消的 AGV 任务从设备当前任务移出，并归并到 `DATA / Devices` 的设备运行历史中，按 AGV 设备编号聚合。

`AGV.tasks` 表字段：

```text
运输编号
任务类型：仓库到工站 / 工站间转运 / 工站到仓库
任务状态：等待中 / 运输中 / 已完成 / 已取消
起始工站/仓库
目标工站/仓库
创建时间
实际开始时间
结束时间
AGV编号
订单编号
工单编号
```

AGV 任务生成规则：

- 首道工序：从仓库将物料输送到目标工站。
- 中间工序：上一道工序完成后，将半成品从上一工站运输到下一工站。
- 末道工序：工站完成后，将产品运输到成品仓库。

设备属性视图只展示设备数据：

- 设备数据：ID、类型、编号、名称、来源等相对静态信息。
- 设备当前执行或等待执行的任务统一在 `Ontology / Devices` 页面上方的 `设备当前任务` 中查看。
- 运输任务、执行任务、开始/结束时间和负载等动态任务信息不在 device 属性视图中展示。

## 关键接口

前端主要读取以下后端接口：

```text
GET /health
GET /api/digital-twin/ontology/live
GET /api/digital-twin/topologies
GET /api/digital-twin/devices
GET /api/digital-twin/store
GET /api/digital-twin/data
GET /api/digital-twin/agv/tasks
GET /api/digital-twin/entities/{entity_type}
GET /api/digital-twin/entities/{entity_type}/{entity_id}
POST /api/chat
POST /api/chat/stop
```

接口职责：

- `/api/digital-twin/ontology/live`：返回 ontology 元数据、类拓扑、实例图和实体目录。
- `/api/digital-twin/devices`：读取 MySQL `device` 数据库中的设备、工站、仓库和 AGV 实例。
- `/api/digital-twin/data`：读取 MySQL `Data` 数据库中的订单工单历史、设备运行历史、质检追溯和 AGV 任务汇总；前端会将设备历史按设备聚合并关联任务、订单信息。
- `/api/digital-twin/data`：同时执行后端 ontology 规则推理。设备运行历史会按 ontology 设备目录过滤，不存在的设备不会进入 `DATA / Devices`；每次推理结果会写入 MySQL `Data.reasoning_results`。
- `/api/digital-twin/agv/tasks`：读取 MySQL `AGV.tasks`，返回 AGV 运输任务和状态统计。
- `/api/chat`：产线管控 Agent 对话接口，前端通过 SSE 流式显示结果。

## Ontology 推理规则

后端在 `agent_backend_adapter/reasoning_service/` 中维护规则推理模块：

```text
reasoning_service/
├─ product_reasoner.py   # 产品与工艺流程推理
├─ order_reasoner.py     # 订单与工单拆分规则
├─ device_reasoner.py    # 设备能力与状态规则
├─ agv_reasoner.py       # AGV 运输任务规则
├─ material_reasoner.py  # 物料与库存规则
├─ quality_reasoner.py   # 质量规则
└─ rule_result.py        # 标准化推理结果结构
```

当前规则覆盖：

- 产品工艺推理：产品通过 `HAS_STEP` 找到工艺流程和工艺步骤。
- 工单拆分推理：订单按产品工艺流程拆分为多个工单。
- 设备匹配推理：工艺根据 `CAN_EXECUTE` 匹配可执行设备。
- AGV 任务推理：首道工序、相邻工单设备不同或末道入库时生成运输任务。
- 库存约束推理：需求数量大于库存或缺少物料批次时不允许执行。
- 质量规则推理：质检不合格进入返工或异常判断。
- 状态约束推理：设备必须存在于 ontology 设备目录，且非故障/离线/维护才可分配；不存在设备的运行历史会被过滤。

MySQL `Data.reasoning_results` 保存每次推理结果：

```text
reasoning_id
trigger_source
status
rule_count
violation_count
summary_json
result_json
created_at
```

`/api/digital-twin/data` 返回 `inference`、`reasoningResults` 和 `persistedReasoning` 字段，供前端和 Agent 使用。

前端将推理规则集中展示在 `Tools / Reasoning Rules`，展示方式与 `Tools / Reports` 中的报告模板类似：优先使用后端返回的实时规则，后端未返回时使用内置规则模板作为 Agent 参考。`Ontology / Relations` 只展示本体类关系和自定义关系，不再混入推理规则。

推理能力也通过 `split_mcp_server` 暴露为 MCP tools：

- `split_product_order`：原有产品订单拆分工具。
- `check_order_feasibility`：执行订单可行性推理并落库。
- `infer_agv_tasks`：返回 AGV 运输任务推理结果。
- `check_material_availability`：返回库存约束规则注册状态，预留物料需求清单校验。
- `check_device_assignment`：执行设备能力与状态约束检查，识别不存在于 ontology 的设备历史。

## 交互验证流程

用于修改审查时的人工验证顺序：

1. 打开 `http://127.0.0.1:5175`。
2. 确认右上角 `API Base` 为 `http://127.0.0.1:8000`。
3. 进入 `Ontology / Devices`。
4. 页面上方只应显示设备当前任务和设备实例列表，设备当前任务只包含执行中或等待执行的任务。
5. 在实例列表中点击任意设备行，包括 `AGV小车`。
6. 下方 `属性视图` 应只显示该设备的图像化设备数据摘要和 `设备数据`，不显示运输任务、执行任务或 `AGV 运输任务视图`。
7. 进入 `DATA / Devices`，已完成或已取消的工站工单与 AGV 运输任务应按设备卡片聚合。
8. 点击任意设备卡片，右侧或下方应显示该设备的运行条目列表。
9. 点击任意运行条目，详情区应显示运行时间、负载、运输路径或来源，并显示对应任务与相关订单信息。
10. 进入 `Tools / Reasoning Rules`，应显示推理规则参考卡片，包含触发条件、推理结论和规则来源。
11. 进入 `Tools / Global Search`，输入设备、订单、工单、物料、产品、工序或工艺关键词，确认结果表按名称、编号、类型、状态展示；切换对象类型、状态、工站或工序筛选后结果应实时更新。
12. 点击任意搜索结果的 `属性视图`，应跳转到对应模块并打开实例属性；点击 `拓扑图`，应跳转到 `Ontology / Classes` 的相关拓扑视图。
13. 在 `Tools / Global Search` 提交检索后，页面右侧 `History` 区域应记录查询词、对象类型和结果数量；点击历史记录应恢复查询条件。
14. 进入 `Tools / Reports`，应显示报告模板与生成报告；Tools 中不再显示 `Device Status` 和 `History`。
15. 点击 `AI Agent / Production Agent`，当前模块页面应保持不变，底部应展开产线管控 Agent 控制台；再次点击控制台栏或关闭按钮可收起控制台。

## 数据展示规则

- `Ontology / Devices` 默认用于设备资产、当前任务和实例选择，不直接铺开 AGV 全量任务。
- `Ontology / Devices` 的设备当前任务只保留正在执行或等待执行的任务。
- 已完成或已取消的工站工单、AGV 运输任务必须进入 `DATA / Devices` 设备运行历史。
- `DATA / Orders` 只归档整单已完成或已取消的订单；单个工单完成但订单未结束时，不进入订单历史，继续在 `Ontology / Orders` 中展示并更新工单状态。
- `DATA / Devices` 设备运行历史必须先按设备编号或设备名称聚合，再展示该设备下的运行条目。
- `DATA / Devices` 只展示通过 ontology 设备目录校验的设备运行历史；MySQL 中不存在于 ontology 的旧设备记录会进入 `reasoning_results` 违规结果，不进入设备历史视图。
- 运行条目详情必须展示对应任务信息；若能从订单工单历史或 ontology 目录匹配到订单，还应展示相关订单信息。
- `Ontology / Orders` 会根据订单编号关联工单，兼容 MySQL 工单表中的 `所属订单`、`所属订单号`、`所属订单编号`、`source_order_id`、`order_id` 等父订单字段。
- 设备属性视图只保留“设备数据”，不展示运输信息或执行任务；执行任务统一在设备当前任务中查看。
- AGV 任务状态颜色跟随通用状态规则：`已完成` 为在线/正常，`运输中` 为执行态，`已取消` 为闲置/取消态，异常或预警进入告警态。
- 前端不会在浏览器中创建数据，AGV 任务表由后端根据订单工单历史初始化或读取 MySQL 现有数据。

## 文件说明

- `index.html`：前端入口，加载 `styles.css` 和根目录 `app.mjs`。
- `app.mjs`：当前主前端逻辑文件，负责路由、渲染、数据请求、列表页、拓扑页、Agent 页面和工具页。
- `styles.css`：页面布局、侧栏、表格、拓扑、卡片和响应式样式。
- `js/config/navigation.mjs`：导航结构与页面标题/说明配置。
- `js/utils/html.mjs`：HTML 转义工具。
- `js/utils/text.mjs`：文本规范化、字段选择和行文本拼接工具。
- `../agent_backend_adapter/reasoning_service/`：后端 ontology 推理规则模块，负责规则定义、状态约束、质检判断和标准化结果。

注意：当前 `index.html` 加载的是根目录 `app.mjs`，不是 `js/app.mjs`。修改前端主界面时请优先检查根目录 `app.mjs`。

## 修改注意事项

- 后续每次修改前端功能、页面文案、端口、接口、数据结构、展示规则或验证流程时，都必须同步更新本 README，确保审查者只读文档也能理解当前前端状态。
- 前端端口统一保持 `5175`，不要在文档、脚本或说明中引入其他前端端口。
- UI 文案以中文为主；保留必要的技术名词，如 `Ontology`、`Neo4j`、`MySQL`、`Agent`、`API Base`。
- 侧栏导航只显示图标和主标题，不显示每个条目的小字说明。
- `AI Agent / Production Agent` 是全局底部控制台开关，不作为独占主内容页面；打开后不应阻止查看当前 Ontology、Tools 或 DATA 模块内容。
- 属性视图、列表页说明和空状态文案应保持完整中文，避免出现残缺词组，例如“无属性数”“运行状”“状态信”。
- `AGV 运输任务视图` 不应放在 Devices 页面默认区域或 AGV 属性视图作为完整列表默认展开。
- 若新增设备相关字段，设备资产字段归类到 `设备数据`；任务、运输、时间和负载字段归入设备当前任务或设备运行历史。
- 修改模板字符串时，注意反引号、`${...}` 插值和 HTML 标签闭合，改完后执行语法检查。
- 尽量保持现有 DOM 结构和 CSS 类名稳定，审查时主要通过页面文案、功能区和路由结构理解前端内容。

## 检查命令

修改后可运行：

```powershell
node --check .\app.mjs
node --check .\js\config\navigation.mjs
```

确认 5175 正常：

```powershell
Get-NetTCPConnection -LocalPort 5175 -ErrorAction SilentlyContinue
```

确认后端和 AGV 任务接口正常：

```powershell
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health).Content
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/digital-twin/agv/tasks).Content
```

预期 `/api/digital-twin/agv/tasks` 返回：

```text
ok: true
database: AGV
table: tasks
tasks: [...]
summary: { total, waiting, transporting, completed, cancelled }
```

