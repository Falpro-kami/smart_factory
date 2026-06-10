import {
  REPORT_TEMPLATES,
  GENERATED_REPORTS,
} from "./js/data/mock-data.mjs?v=20260602-agent-console-v1";
import { adaptPayload } from "./js/data/api.mjs?v=20260602-agent-console-v1";
import { flattenRows } from "./js/data/adapters/mysql-tables.mjs?v=20260602-agent-console-v1";
import { NAVIGATION, ROUTE_META } from "./js/config/navigation.mjs?v=20260602-agent-console-v1";
import { escapeHtml } from "./js/utils/html.mjs?v=20260602-agent-console-v1";
import { firstField, rowText, normalizeText } from "./js/utils/text.mjs?v=20260602-agent-console-v1";

const STORAGE_KEY = "digitalTwinApiBase";
const AGENT_STORAGE_KEY = "digitalTwinAgentMessages";
const REPORT_STORAGE_KEY = "digitalTwinGeneratedReports";
const SIDEBAR_STORAGE_KEY = "digitalTwinSidebarCollapsed";
const NAV_STORAGE_KEY = "digitalTwinNavExpanded";
const CLASS_STORAGE_KEY = "digitalTwinClassState";
const SEARCH_HISTORY_STORAGE_KEY = "digitalTwinGlobalSearchHistory";
const THEME_STORAGE_KEY = "digitalTwinTheme";
const API_BASE = "http://127.0.0.1:8000";
const AGENT_SESSION_ID = "digital-twin-ontology-only";
const CLASS_NODE_WIDTH = 220;
const CLASS_NODE_HEIGHT = 116;
const MYSQL_ENTITY_TYPES = new Set(["device", "material", "order", "work_order"]);
const ENTITY_LIST_REFRESH_TYPES = ["order", "work_order", "product", "process", "craft"];
const GLOBAL_SEARCH_ENTITY_TYPES = ["device", "order", "work_order", "material", "product", "process", "craft"];
const DEVICE_STATUS_NAME_ALIASES = new Map();
const TOPOLOGY_MODES = [
  { key: "production", label: "本体类拓扑", description: "查看智能产线本体类之间的完整拓扑关系。" },
  { key: "product-process", label: "产品 - 工序", description: "查看产品、工序、输入物料和输出部件之间的拓扑关系。" },
  { key: "device-craft", label: "设备 - 工艺", description: "查看设备与工艺能力之间的拓扑关系。" },
];
const REASONING_RULE_TEMPLATES = [
  {
    id: "RULE-PRODUCT-PROCESS",
    title: "产品工艺推理",
    summary: "产品通过 HAS_STEP 找到工艺流程和工艺步骤，形成产品到工序的执行链路。",
    condition: "Product HAS_STEP Process",
    conclusion: "生成产品-工序拓扑和可执行工序清单",
    source: "product_reasoner.py",
  },
  {
    id: "RULE-ORDER-SPLIT",
    title: "工单拆分推理",
    summary: "订单按产品工艺流程拆分为多个工单，并保留工序顺序、目标工站和执行状态。",
    condition: "Order produces Product，Product 具备工艺步骤",
    conclusion: "生成拆分工单和订单树",
    source: "order_reasoner.py",
  },
  {
    id: "RULE-DEVICE-ASSIGNMENT",
    title: "设备匹配推理",
    summary: "工艺根据 CAN_EXECUTE 匹配可执行设备，并检查设备是否存在于 ontology 设备目录。",
    condition: "Craft CAN_EXECUTE Device，Device 在线且非故障/维护",
    conclusion: "返回可分配设备或违规原因",
    source: "device_reasoner.py",
  },
  {
    id: "RULE-AGV-TASK",
    title: "AGV 任务推理",
    summary: "首道工序、跨工站转运和末道入库时生成 AGV 运输任务。",
    condition: "工单顺序变化或工站位置变化",
    conclusion: "生成仓库到工站、工站间转运、工站到仓库任务",
    source: "agv_reasoner.py",
  },
  {
    id: "RULE-MATERIAL-INVENTORY",
    title: "库存约束推理",
    summary: "需求数量大于库存或缺少物料批次时，不允许订单继续执行。",
    condition: "需求物料数量 > 可用库存，或缺少物料批次",
    conclusion: "生成库存违规结果和预警摘要",
    source: "material_reasoner.py",
  },
  {
    id: "RULE-QUALITY",
    title: "质量规则推理",
    summary: "质检不合格时进入返工或异常判断，并关联产品、工单和物料追溯信息。",
    condition: "Quality result = 不合格",
    conclusion: "生成返工、异常和追溯判断",
    source: "quality_reasoner.py",
  },
  {
    id: "RULE-DEVICE-STATE",
    title: "状态约束推理",
    summary: "设备必须存在于 ontology 设备目录，且非故障、离线或维护状态才可参与任务分配。",
    condition: "Device in ontology directory，status 可执行",
    conclusion: "过滤无效设备历史并写入 reasoning_results",
    source: "device_reasoner.py",
  },
];
const AGENT_CALL_SCOPE = [
  "Frontend scope: this request belongs only to the manufacturing_agent smart production-line ontology project.",
  "Use only the current backend ontology, MySQL, Neo4j, split MCP, skills, and project data.",
  "Do not call, infer, or require tools outside this smart production-line project.",
  "When the user mentions equipment or workstations, treat them as ontology production-line entities.",
].join("\n");
const ENTITY_META = {
  device: { title: "设备", route: "/ontology/devices", entityType: "device" },
  order: { title: "订单", route: "/ontology/orders", entityType: "order" },
  work_order: { title: "工单", route: "/ontology/work-orders", entityType: "work_order" },
  material: { title: "物料", route: "/ontology/materials", entityType: "material" },
  product: { title: "产品", route: "/ontology/products", entityType: "product" },
  process: { title: "工序", route: "/ontology/processes", entityType: "process" },
  craft: { title: "工艺", route: "/ontology/crafts", entityType: "craft" },
};
const ENTITY_LIST_COPY = {
  device: "查看设备实例列表，选择任意行后可在下方查看完整属性。",
  material: "查看物料与库存实例，选择任意行后可在下方查看完整属性。",
  product: "查看产品定义与工艺模板实例，选择任意行后可在下方查看完整属性。",
  process: "查看产品工序节点、物料使用和部件产出实例，选择任意行后可在下方查看完整属性。",
  craft: "查看工艺流程、能力关系和工艺属性实例，选择任意行后可在下方查看完整属性。",
};
const PROPERTY_FIELD_LABELS = {
  id: "ID",
  label: "名称",
  subtitle: "说明",
  entityType: "类型",
  status: "状态",
  source: "来源",
};
const TYPE_ICON_META = {
  ontology: { label: "ON", tone: "violet" },
  device: { label: "EQ", tone: "cyan" },
  workstation: { label: "ST", tone: "cyan" },
  warehouse: { label: "WH", tone: "green" },
  agv: { label: "AGV", tone: "pink" },
  order: { label: "OD", tone: "pink" },
  work_order: { label: "WO", tone: "red" },
  material: { label: "MT", tone: "amber" },
  store_product: { label: "PR", tone: "green" },
  product: { label: "PD", tone: "yellow" },
  process: { label: "PR", tone: "green" },
  craft: { label: "CF", tone: "violet" },
  part: { label: "PT", tone: "amber" },
  class: { label: "CL", tone: "violet" },
  relation: { label: "RL", tone: "blue" },
  search: { label: "SR", tone: "blue" },
  data: { label: "DT", tone: "green" },
  report: { label: "RP", tone: "amber" },
  reasoning: { label: "RR", tone: "blue" },
  alert: { label: "AL", tone: "red" },
  agent: { label: "AI", tone: "green" },
};

const EMPTY_CATALOGS = { device: [], order: [], work_order: [], material: [], product: [], process: [], craft: [] };
const LIST_CLASS_NODE_IDS = new Set(["user", "order", "work-order", "workstation", "product", "craft", "process", "warehouse", "material", "agv"]);
const CLASS_TOPOLOGY_NODES = [
  { id: "user", entityType: "class", label: "User", en: "User", tone: "violet", x: 25, y: 55 },
  { id: "order", entityType: "order", label: "Order", moduleType: "order", tone: "pink", x: 360, y: 55 },
  { id: "work-order", entityType: "work_order", label: "Work_order", moduleType: "work_order", tone: "red", x: 800, y: 55 },
    { id: "workstation", entityType: "device", label: "Workstation", moduleType: "device", keywords: ["workstation", "station"], tone: "cyan", x: 1330, y: 55 },
  { id: "product", entityType: "product", label: "Product", moduleType: "product", tone: "yellow", x: 360, y: 330 },
  { id: "craft", entityType: "craft", label: "Craft", en: "Craft", moduleType: "craft", tone: "violet", x: 800, y: 330 },
  { id: "process", entityType: "process", label: "Process", moduleType: "process", tone: "green", x: 1330, y: 330 },
    { id: "warehouse", entityType: "device", label: "Warehouse", moduleType: "device", keywords: ["warehouse"], tone: "cyan", x: 760, y: 575 },
    { id: "material", entityType: "material", label: "Material", moduleType: "material", keywords: ["material"], tone: "yellow", x: 1330, y: 575 },
    { id: "agv", entityType: "device", label: "AGV", moduleType: "device", keywords: ["AGV", "agv"], tone: "pink", x: 360, y: 670 },
];
const CLASS_TOPOLOGY_EDGES = [
  { source: "user", target: "order", label: "create" },
  { source: "order", target: "work-order", label: "split into" },
  { source: "work-order", target: "workstation", label: "assigned to" },
  { source: "order", target: "product", label: "produces" },
  { source: "product", target: "process", label: "has_step" },
  { source: "workstation", target: "craft", label: "can_execute" },
  { source: "warehouse", target: "material", label: "stores" },
  { source: "agv", target: "material", label: "transports" },
  { source: "material", target: "workstation", label: "supplied to" },
];

const state = {
  route: normalizeRoute(location.hash),
  sidebarCollapsed: readStoredSidebarCollapsed(),
  navExpanded: readStoredNavExpanded(),
  ontology: null,
  classGraph: { nodes: [], edges: [] },
  instanceGraph: { nodes: [], edges: [] },
  neoTopologies: {},
  catalogs: { ...EMPTY_CATALOGS },
  ontologySearch: { device: "", order: "", work_order: "", material: "", product: "", process: "", craft: "", classes: "", relations: "" },
  globalSearch: {
    query: "",
    entityType: "all",
    status: "all",
    stationProcess: "all",
    history: readStoredSearchHistory(),
  },
  topologyView: { scale: 0.78, x: 0, y: 0 },
  topologyNodePositions: {},
  classTopologyMode: "production",
  classViewMode: "topology",
  classInstanceViewMode: "list",
  productProcessExpanded: {},
  orderTreeExpanded: {},
  deviceTreeExpanded: {},
  classRecycleOpen: false,
  classState: readStoredClassState(),
  selectedEntity: null,
  selectedEntityType: "product",
  selectedEntityId: "",
  devices: { ok: false, source: "api", error: "", tables: [] },
  store: { ok: false, source: "api", error: "", tables: [] },
  data: { ok: false, database: "Data", orderTree: [], deviceHistory: [], qualityTrace: [], reasoningResults: [], inference: { rules: [], applied: [], violations: [], summary: {} }, loadCurveModule: {}, summary: {} },
  dataDeviceHistory: { selectedDeviceId: "", selectedRunId: "" },
  agv: { ok: false, database: "AGV", error: "", tasks: [], summary: {} },
  reports: readStoredReports(),
  liveEvents: { source: null, refreshTimer: null },
  selectedReportId: "",
  theme: readStoredTheme(),
  agent: {
    messages: readStoredAgentMessages(),
    pending: false,
    requestId: "",
    abortController: null,
    threadId: "ontology-production-agent-frontend-only",
    status: "ready",
    consoleOpen: false,
  },
  loading: false,
};

const elements = {
  appShell: document.querySelector(".app-shell"),
  currentOntology: document.querySelector("#current-ontology"),
  sidebarNav: document.querySelector("#sidebar-nav"),
  sidebarToggle: document.querySelector("#sidebar-toggle"),
  breadcrumb: document.querySelector("#breadcrumb"),
  pageTitle: document.querySelector("#page-title"),
  pageDescription: document.querySelector("#page-description"),
  appRoot: document.querySelector("#app-root"),
  agentConsoleRoot: null,
  themeSwitcherRoot: null,
  apiBaseInput: document.querySelector("#api-base"),
  refreshBtn: document.querySelector("#refresh-btn"),
};

function normalizeRoute(hash) {
  const value = String(hash || "#/ontology/classes").replace(/^#/, "");
  if (value === "/ontology/topology") return "/ontology/classes";
  return value || "/ontology/classes";
}

function currentRouteMeta() {
  return ROUTE_META[state.route] || ROUTE_META["/ontology/classes"];
}

function readStoredApiBase() {
  try {
    return localStorage.getItem(STORAGE_KEY) || API_BASE;
  } catch {
    return API_BASE;
  }
}

function storeApiBase(value) {
  try {
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    return;
  }
}

function readStoredAgentMessages() {
  try {
    const messages = JSON.parse(localStorage.getItem(AGENT_STORAGE_KEY) || "[]");
    return Array.isArray(messages) ? messages : [];
  } catch {
    return [];
  }
}

function storeAgentMessages() {
  try {
    localStorage.setItem(AGENT_STORAGE_KEY, JSON.stringify(state.agent.messages.slice(-30)));
  } catch {
    return;
  }
}

function readStoredReports() {
  try {
    const reports = JSON.parse(localStorage.getItem(REPORT_STORAGE_KEY) || "[]");
    return Array.isArray(reports) ? reports : [];
  } catch {
    return [];
  }
}

function storeReports() {
  try {
    localStorage.setItem(REPORT_STORAGE_KEY, JSON.stringify(state.reports.slice(0, 20)));
  } catch {
    return;
  }
}

function readStoredSearchHistory() {
  try {
    const history = JSON.parse(localStorage.getItem(SEARCH_HISTORY_STORAGE_KEY) || "[]");
    return Array.isArray(history) ? history : [];
  } catch {
    return [];
  }
}

function storeSearchHistory() {
  try {
    localStorage.setItem(SEARCH_HISTORY_STORAGE_KEY, JSON.stringify(state.globalSearch.history.slice(0, 12)));
  } catch {
    return;
  }
}

function readStoredClassState() {
  try {
    const data = JSON.parse(localStorage.getItem(CLASS_STORAGE_KEY) || "{}");
    const overrides = data.overrides && typeof data.overrides === "object" ? data.overrides : {};
    if (overrides.craft?.deleted === true) {
      overrides.craft = { ...overrides.craft };
      delete overrides.craft.deleted;
      localStorage.setItem(CLASS_STORAGE_KEY, JSON.stringify({ ...data, overrides }));
    }
    return {
      customClasses: Array.isArray(data.customClasses) ? data.customClasses : [],
      customRelations: Array.isArray(data.customRelations) ? data.customRelations : [],
      overrides,
      relationOverrides: data.relationOverrides && typeof data.relationOverrides === "object" ? data.relationOverrides : {},
    };
  } catch {
    return { customClasses: [], customRelations: [], overrides: {}, relationOverrides: {} };
  }
}

function storeClassState() {
  try {
    localStorage.setItem(CLASS_STORAGE_KEY, JSON.stringify(state.classState));
  } catch {
    return;
  }
}

function readStoredTheme() {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return value === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

function storeTheme(value) {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, value);
  } catch {
    return;
  }
}

function applyTheme() {
  document.documentElement.dataset.theme = state.theme;
  document.body.dataset.theme = state.theme;
}

function setTheme(value) {
  state.theme = value === "light" ? "light" : "dark";
  storeTheme(state.theme);
  applyTheme();
  renderThemeSwitcher();
  renderAgentConsoleOverlay();
}
function apiBase() {
  const base = elements.apiBaseInput.value.trim().replace(/\/+$/, "");
  if (!base) {
    throw new Error("API base is required");
  }
  return base;
}

function setLoading(value) {
  state.loading = value;
  elements.refreshBtn.disabled = value;
  elements.refreshBtn.textContent = value ? "Refreshing..." : "Refresh";
}

function setRoute(hash) {
  const nextRoute = normalizeRoute(hash);
  if (nextRoute === "/agent/console") {
    state.agent.consoleOpen = true;
    if (state.route === "/agent/console") state.route = "/ontology/devices";
  } else {
    state.route = nextRoute;
  }
  renderShell();
  renderPage();
}

function statusBadgeText() {
  if (state.devices.ok && state.store.ok) {
    return "实时数据";
  }
  if (state.devices.ok || state.store.ok) {
    return "混合数据";
  }
  return "示例数据";
}

function entityItems(entityType) {
  return state.catalogs[entityType] || [];
}

function sourceText(source) {
  return Array.isArray(source) ? source.join(" · ") : String(source || "-");
}

function typeIconHtml(type, label = "") {
  const meta = TYPE_ICON_META[type] || TYPE_ICON_META.ontology;
  return `<span class="type-icon type-icon-${escapeHtml(meta.tone)}" aria-hidden="true" title="${escapeHtml(label || type)}">${escapeHtml(meta.label)}</span>`;
}

function navIconType(item) {
  const route = normalizeRoute(item.hash);
  if (route.includes("/devices")) return "device";
  if (route.includes("/orders")) return "order";
  if (route.includes("/work-orders")) return "work_order";
  if (route.includes("/materials")) return "material";
  if (route.includes("/products")) return "product";
  if (route.includes("/processes")) return "process";
  if (route.includes("/crafts")) return "craft";
  if (route.includes("/classes")) return "class";
  if (route.includes("/relations")) return "relation";
  if (route.includes("/search")) return "search";
  if (route.includes("/reasoning-rules")) return "reasoning";
  if (route.includes("/reports")) return "report";
  if (route.includes("/agent")) return "agent";
  return "ontology";
}

function deviceSubtype(item) {
  const text = normalizeText(rowText(item));
  if (text.includes("agv") || text.includes("小车")) return "agv";
  if (text.includes("warehouse") || text.includes("仓库") || text.includes("立体")) return "warehouse";
  if (text.includes("workstation") || text.includes("station") || text.includes("工站") || text.includes("工作")) return "workstation";
  return "device";
}

function entityIconType(entityType, item = null) {
  if (entityType === "device") return deviceSubtype(item);
  if (entityType === "material" && normalizeText(item?.properties?.__table || item?.__table || "").includes("product")) return "store_product";
  return entityType;
}

function mysqlCatalogItem(entityType, row, index) {
  const source = [`mysql:${entityType === "material" ? "store" : entityType === "device" ? "device" : "order"}.${row.__table || "unknown"}`];
  const idPrefix = entityType;
  const id =
    entityType === "device"
      ? deviceCatalogIdentity(row, index)
      : entityType === "material"
        ? firstField(row, ["物料编号", "物料编码", "产品编号", "material_code", "materialCode", "product_code", "productCode", "code"], `${row.__table}:${index}`)
        : entityType === "order"
          ? firstField(row, ["订单编号", "订单ID", "order_id", "orderId", "id", "code"], `${row.__table}:${index}`)
          : firstField(row, ["工单编号", "工单ID", "任务编号", "work_order_id", "workOrderId", "task_id", "taskId", "id", "code"], `${row.__table}:${index}`);

  const item = {
    id: `${idPrefix}:${id}`,
    entityType,
    label: "",
    subtitle: "",
    status: firstField(row, ["运行状", "设备状", "启动状", "状", "工单状", "订单状", "运输状", "任务状", "status", "state"], "live"),
    source,
    properties: row,
    runtime: row,
    relations: [],
  };
  item.label = entityDisplayLabel(item, entityType);
  item.subtitle = entityDisplaySubtitle(item, entityType);
  item.summary = item.subtitle;
  return item;
}

function deviceCatalogIdentity(row, index) {
  const subtype = deviceSubtype(row);
  if (subtype === "agv") {
    return firstField(row, ["AGV编号", "agv_id", "agvId", "小车编号", "vehicle_id", "vehicleId", "transport_device_id", "code"], `${row.__table}:${index}`);
  }
  return firstField(row, ["设备编号", "设备ID", "deviceCode", "device_code", "device_id", "deviceId", "workstation_id", "workstationId", "station_id", "stationId", "code"], `${row.__table}:${index}`);
}

function replaceCatalogItems(entityType, items) {
  state.catalogs[entityType] = Array.isArray(items) ? items : [];
}

function deviceRowsFromMysql() {
  return flattenRows(state.devices.tables).filter((row) => {
    const table = normalizeText(row.__table || "");
    return table === "devices" || table === "agv" || table === "workstation";
  });
}

function mergeCatalogItems(entityType, items) {
  if (!items.length) return;
  const existing = MYSQL_ENTITY_TYPES.has(entityType) ? [] : state.catalogs[entityType] || [];
  const seen = new Set(existing.map((item) => item.id));
  const merged = [...existing];
  items.forEach((item) => {
    if (!seen.has(item.id)) {
      seen.add(item.id);
      merged.push(item);
    }
  });
  state.catalogs[entityType] = merged;
}

function syncCatalogsFromTables() {
  replaceCatalogItems("device", deviceRowsFromMysql().map((row, index) => mysqlCatalogItem("device", row, index)));
  replaceCatalogItems("material", flattenRows(state.store.tables).map((row, index) => mysqlCatalogItem("material", row, index)));
}

async function refreshEntityCatalogs() {
  const entityTypes = ENTITY_LIST_REFRESH_TYPES;
  const results = await Promise.allSettled(
    entityTypes.map((entityType) => fetchJson(`/api/digital-twin/entities/${entityType}`))
  );

  results.forEach((result, index) => {
    if (result.status !== "fulfilled" || !result.value?.ok) return;
    const entityType = entityTypes[index];
    if (entityType === "device") return;
    const items = Array.isArray(result.value.items) ? result.value.items : [];
    replaceCatalogItems(entityType, items);
  });
}

function filterItems(items, query) {
  const q = normalizeText(query || "");
  if (!q) return items;
  return items.filter((item) => normalizeText(rowText(item)).includes(q));
}

function filterGraph(graph, query) {
  const q = normalizeText(query || "");
  if (!q) return graph;
  const nodes = (graph.nodes || []).filter((node) => normalizeText(`${node.label || ""} ${node.subtitle || ""} ${node.id || ""}`).includes(q));
  const nodeIds = new Set(nodes.map((node) => node.id));
  return {
    nodes,
    edges: (graph.edges || []).filter((edge) => {
      const labelMatches = normalizeText(edge.label || "").includes(q);
      const endpointsMatch = nodeIds.has(edge.source) && nodeIds.has(edge.target);
      return labelMatches || endpointsMatch;
    }),
  };
}

function buildFallbackOntology() {
  return {
    id: "smart-production-ontology",
    name: "智能产线 Ontology",
    version: "live",
    status: "Live",
    description: "基于 Neo4j 产品/工艺图与 MySQL 运行态数据构建的实时智能产线本体",
  };
}

async function fetchJson(path) {
  const response = await fetch(`${apiBase()}${path}`, {
    headers: { Accept: "application/json" },
  });

  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }

  if (!response.ok) {
    throw new Error(payload.error || `${response.status} ${response.statusText}`);
  }

  return payload;
}

function createAgentMessage(role, content) {
  return {
    id: crypto.randomUUID(),
    role,
    content,
    createdAt: new Date().toISOString(),
  };
}

function agentStatusText() {
  if (state.agent.status === "busy") return "运行";
  if (state.agent.status === "error") return "异常";
  return "就绪";
}

function extractAgentText(data) {
  if (typeof data === "string") return data;
  if (!data || typeof data !== "object") return "";
  if (typeof data.content === "string") return data.content;
  if (typeof data.reply === "string") return data.reply;
  if (typeof data.message === "string") return data.message;
  if (typeof data.output === "string") return data.output;
  return JSON.stringify(data, null, 2);
}

function buildScopedAgentMessage(userText) {
  const reportTemplate = productionReportTemplate();
  const reportInstruction = reportTemplate
    ? `

Product production analysis report skill reference:
- Template: ${reportTemplate.title} (${reportTemplate.id})
- Format: ${reportTemplate.format}
- Local skill: ${reportTemplate.skillPath || "skills/product-production-analysis-report/SKILL.md"}
- Required charts: ${reportTemplate.charts.join(" / ")}
- Required sections: ${reportTemplate.sections.join(" / ")}
- Use Data.orderTree, Data.deviceHistory, quality trace, product-process topology, process duration statistics, and product production-time distribution when generating reports.`
    : "";

  return `${AGENT_CALL_SCOPE}${reportInstruction}

User question: ${userText}`;
}

function normalizeAgentError(message) {
  const text = String(message || "");
  if (text.includes("removed external tool") || text.includes("external simulation tool")) {
    return "The backend routed this request to a removed external tool. The frontend scope is limited to ontology, MySQL, Neo4j, and production-line data in this project.";
  }
  return text || "Agent returned an error";
}

function parseSseChunk(rawChunk) {
  const dataLines = rawChunk
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim());

  const dataText = dataLines.join("");
  if (!dataText) return null;
  if (dataText === "[DONE]") return { done: true, text: "" };

  try {
    const data = JSON.parse(dataText);
    if (data?.error) {
      return { done: false, text: normalizeAgentError(data.error), error: true };
    }
    return { done: false, text: extractAgentText(data) };
  } catch {
    return { done: false, text: dataText };
  }
}

async function consumeAgentStream(stream, assistantMessage) {
  const reader = stream.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";

    for (const chunk of chunks) {
      const parsed = parseSseChunk(chunk);
      if (!parsed) continue;
      if (parsed.done) return;

      assistantMessage.content += parsed.text;
      if (parsed.error) {
        assistantMessage.error = true;
        throw new Error(parsed.text);
      }
      storeAgentMessages();
      renderAgentMessages();
    }
  }
}

async function requestAgentReply(userText, assistantMessage) {
  const response = await fetch(`${apiBase()}/api/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream, application/json",
    },
    signal: state.agent.abortController?.signal,
    body: JSON.stringify({
      request_id: state.agent.requestId,
      message: buildScopedAgentMessage(userText),
      thread_id: state.agent.threadId,
      session_id: AGENT_SESSION_ID,
      history: state.agent.messages
        .filter((message) => message.id !== assistantMessage.id)
        .map(({ role, content }) => ({ role, content })),
      stream: true,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => "");
    let errorMessage = errorText || `HTTP ${response.status}`;
    try {
      const errorPayload = JSON.parse(errorText);
      errorMessage = errorPayload.error || errorPayload.message || errorMessage;
    } catch {
      // Keep the raw response text when the error body is not JSON.
    }
    throw new Error(normalizeAgentError(errorMessage));
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("text/event-stream") && response.body) {
    await consumeAgentStream(response.body, assistantMessage);
    return;
  }

  if (contentType.includes("application/json")) {
    const data = await response.json();
    if (data?.error) {
      throw new Error(normalizeAgentError(data.error));
    }
    assistantMessage.content = extractAgentText(data);
    return;
  }

  assistantMessage.content = await response.text();
}

async function stopAgentRequest() {
  if (!state.agent.pending) return;

  const requestId = state.agent.requestId;
  state.agent.abortController?.abort();

  if (!requestId) return;

  await fetch(`${apiBase()}/api/chat/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ request_id: requestId }),
  }).catch(() => {});
}

async function sendAgentMessage(text) {
  const userText = String(text || "").trim();
  if (!userText || state.agent.pending) return;

  const userMessage = createAgentMessage("user", userText);
  const assistantMessage = createAgentMessage("assistant", "");
  state.agent.messages.push(userMessage, assistantMessage);
  state.agent.pending = true;
  state.agent.status = "busy";
  state.agent.requestId = crypto.randomUUID();
  state.agent.abortController = new AbortController();
  storeAgentMessages();
  renderPage();

  try {
    if (isProductionReportRequest(userText)) {
      assistantMessage.content = buildProductionAnalysisReportText();
      saveGeneratedReportFromContent(assistantMessage.content);
    } else {
      await requestAgentReply(userText, assistantMessage);
    }
    if (!assistantMessage.content.trim()) {
      assistantMessage.content = "Agent 已结束响应，但未返回内容";
    }
    state.agent.status = "ready";
  } catch (error) {
    if (error?.name === "AbortError") {
      assistantMessage.content ||= "Agent request stopped.";
      state.agent.status = "ready";
    } else {
      assistantMessage.content = `Agent request failed: ${error instanceof Error ? error.message : String(error)}`;
      assistantMessage.error = true;
      state.agent.status = "error";
    }
  } finally {
    state.agent.pending = false;
    state.agent.requestId = "";
    state.agent.abortController = null;
    storeAgentMessages();
    renderPage();
  }
}

async function refreshData() {
  setLoading(true);
  try {
    storeApiBase(apiBase());
    const [ontologyResult, topologiesResult, dataResult, devicesResult, storeResult, agvResult] = await Promise.allSettled([
      fetchJson("/api/digital-twin/ontology/live"),
      fetchJson("/api/digital-twin/topologies"),
      fetchJson("/api/digital-twin/data"),
      fetchJson("/api/digital-twin/devices"),
      fetchJson("/api/digital-twin/store"),
      fetchJson("/api/digital-twin/agv/tasks"),
    ]);

    if (ontologyResult.status === "fulfilled" && ontologyResult.value.ok) {
      state.ontology = ontologyResult.value.ontology || buildFallbackOntology();
      state.classGraph = ontologyResult.value.classGraph || { nodes: [], edges: [] };
      state.instanceGraph = ontologyResult.value.instanceGraph || { nodes: [], edges: [] };
      state.catalogs = { ...EMPTY_CATALOGS };
    } else {
      state.ontology = buildFallbackOntology();
      state.classGraph = { nodes: [], edges: [] };
      state.instanceGraph = { nodes: [], edges: [] };
      state.catalogs = { ...EMPTY_CATALOGS };
    }

    if (topologiesResult.status === "fulfilled" && topologiesResult.value.ok) {
      state.neoTopologies = Object.fromEntries(
        (topologiesResult.value.topologies || []).map((topology) => [topology.key, topology])
      );
    } else {
      state.neoTopologies = {};
    }

    state.devices =
      devicesResult.status === "fulfilled"
        ? adaptPayload(devicesResult.value)
        : { ok: false, source: "api", error: devicesResult.reason?.message || "接口调用失败", tables: [] };

    state.data =
      dataResult.status === "fulfilled" && dataResult.value.ok
        ? dataResult.value
        : { ok: false, database: "Data", error: dataResult.reason?.message || "DATA 接口调用失败", orderTree: [], deviceHistory: [], qualityTrace: [], reasoningResults: [], inference: { rules: [], applied: [], violations: [], summary: {} }, loadCurveModule: {}, summary: {} };

    state.store =
      storeResult.status === "fulfilled"
        ? adaptPayload(storeResult.value)
        : { ok: false, source: "api", error: storeResult.reason?.message || "接口调用失败", tables: [] };

    state.agv =
      agvResult.status === "fulfilled" && agvResult.value.ok
        ? agvResult.value
        : { ok: false, database: "AGV", error: agvResult.reason?.message || "AGV tasks 接口调用失败", tasks: [], summary: {} };

    syncCatalogsFromTables();
    await refreshEntityCatalogs();
  } catch (error) {
    state.ontology = buildFallbackOntology();
    state.classGraph = { nodes: [], edges: [] };
    state.instanceGraph = { nodes: [], edges: [] };
    state.neoTopologies = {};
    state.catalogs = { ...EMPTY_CATALOGS };
    state.data = { ok: false, database: "Data", error: error.message, orderTree: [], deviceHistory: [], qualityTrace: [], reasoningResults: [], inference: { rules: [], applied: [], violations: [], summary: {} }, loadCurveModule: {}, summary: {} };
    state.agv = { ok: false, database: "AGV", error: error.message, tasks: [], summary: {} };
    state.devices = { ok: false, source: "api", error: error.message, tables: [] };
    state.store = { ok: false, source: "api", error: error.message, tables: [] };
  } finally {
    setLoading(false);
    renderPage();
  }
}

function renderShell() {
  const meta = currentRouteMeta();
  const ontology = state.ontology || buildFallbackOntology();

  applySidebarState();
  elements.breadcrumb.textContent = meta.breadcrumb;
  elements.pageTitle.textContent = meta.title;
  elements.pageDescription.textContent = meta.description;

  elements.currentOntology.innerHTML = `
    <p class="sidebar-section-title">CURRENT ONTOLOGY</p>
    <article class="ontology-card">
      <div class="ontology-card-head">
        ${typeIconHtml("ontology", ontology.name)}
        <div>
          <h2>${escapeHtml(ontology.name)}</h2>
          <p>${escapeHtml(ontology.version)} · ${escapeHtml(ontology.status)}</p>
        </div>
      </div>
      <p class="ontology-card-copy">${escapeHtml(ontology.description)}</p>
      <div class="ontology-card-meta">
        <span class="meta-pill">${(state.classGraph.nodes || []).length} 类</span>
        <span class="meta-pill">${(state.instanceGraph.nodes || []).length} 实例</span>
      </div>
    </article>
  `;

  elements.sidebarNav.innerHTML = NAVIGATION.map((group) => `
    <section class="nav-group ${state.navExpanded[group.section] === false ? "collapsed" : ""}">
      <button class="nav-section-toggle" type="button" data-nav-section="${escapeHtml(group.section)}" aria-expanded="${state.navExpanded[group.section] !== false}">
        <span>${escapeHtml(group.section)}</span>
        <b>${state.navExpanded[group.section] === false ? "+" : "−"}</b>
      </button>
      <div class="nav-links ${state.navExpanded[group.section] === false ? "is-collapsed" : ""}">
        ${group.items
          .map(
            (item) => `
              <a class="nav-link ${normalizeRoute(item.hash) === state.route ? "active" : ""}" href="${item.hash}">
                ${typeIconHtml(navIconType(item), item.label)}
                <span class="nav-link-copy">
                  <strong>${escapeHtml(item.label)}</strong>
                </span>
              </a>
            `
          )
          .join("")}
      </div>
    </section>
  `).join("");

  elements.sidebarNav.querySelectorAll("a[href^='#']").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const href = link.getAttribute("href");
      if (normalizeRoute(href) === "/agent/console") {
        state.agent.consoleOpen = true;
        renderAgentConsoleOverlay();
        updateActiveNavigation();
        return;
      }
      location.hash = href;
    });
  });

  elements.sidebarNav.querySelectorAll("[data-nav-section]").forEach((button) => {
    button.addEventListener("click", () => {
      const section = button.dataset.navSection;
      if (!section) return;
      state.navExpanded[section] = state.navExpanded[section] === false;
      storeNavExpanded();
      renderShell();
    });
  });
}

function scheduleLiveEventRefresh() {
  if (state.liveEvents.refreshTimer) {
    clearTimeout(state.liveEvents.refreshTimer);
  }
  state.liveEvents.refreshTimer = setTimeout(() => {
    state.liveEvents.refreshTimer = null;
    refreshData().catch(() => renderPage());
  }, 150);
}

function connectDigitalTwinEvents() {
  if (state.liveEvents.source || typeof EventSource === "undefined") return;

  const source = new EventSource(`${apiBase()}/api/digital-twin/events`);
  state.liveEvents.source = source;

  source.onmessage = (event) => {
    if (!event.data) return;
    try {
      const payload = JSON.parse(event.data);
      if (payload.type && payload.type !== "connected") {
        scheduleLiveEventRefresh();
      }
    } catch {
      // Ignore malformed event payloads; EventSource will keep the connection alive.
    }
  };

  source.onerror = () => {
    source.close();
    state.liveEvents.source = null;
    setTimeout(connectDigitalTwinEvents, 3000);
  };
}

function reconnectDigitalTwinEvents() {
  state.liveEvents.source?.close();
  state.liveEvents.source = null;
  connectDigitalTwinEvents();
}

function renderMetricPills(items) {
  return items.map((item) => `<span class="metric-pill">${escapeHtml(item)}</span>`).join("");
}

function renderOntologySearch(searchKey, placeholder) {
  return `
    <div class="search-box ontology-search-box">
      <input
        class="search-input ontology-search-input"
        type="search"
        value="${escapeHtml(state.ontologySearch[searchKey] || "")}"
        placeholder="${escapeHtml(placeholder)}"
        data-ontology-search="${escapeHtml(searchKey)}"
        autocomplete="off"
        spellcheck="false"
      />
    </div>
  `;
}

function edgeStyle(edge) {
  const dx = edge.x2 - edge.x1;
  const dy = edge.y2 - edge.y1;
  const length = Math.sqrt(dx * dx + dy * dy);
  const angle = Math.atan2(dy, dx) * (180 / Math.PI);
  return `left:${edge.x1}%;top:${edge.y1}%;width:${length}%;transform:rotate(${angle}deg);`;
}

function edgeLabelStyle(edge) {
  const x = (edge.x1 + edge.x2) / 2;
  const y = (edge.y1 + edge.y2) / 2;
  return `left:${x}%;top:${y}%;`;
}

function renderTopologyGraph(graph) {
  const edges = (graph.edges || [])
    .map(
      (edge) => `
        <div class="graph-edge ${edge.style || "solid"}" style="${edgeStyle(edge)}"></div>
        <span class="graph-edge-label" style="${edgeLabelStyle(edge)}">${escapeHtml(edge.label)}</span>
      `
    )
    .join("");

  const nodes = (graph.nodes || [])
    .map((node) => {
      const entityType = node.entityType || "product";
      const entityId = node.id;
      const nodeStatus = entityType === "device" ? displayValue(node.status || node.runtime?.status || node.properties?.status, "") : "";
      return `
        <button class="topology-node ${escapeHtml(node.tone || "tone-cyan")}" data-entity-type="${escapeHtml(entityType)}" data-entity-id="${escapeHtml(entityId)}" style="left:${node.x}%;top:${node.y}%" type="button">
          <strong>${escapeHtml(classDisplayName(node))}</strong>
          <small>${escapeHtml(node.subtitle)}</small>
          ${nodeStatus ? `<span class="topology-node-status ${statusClass(nodeStatus)}">${escapeHtml(nodeStatus)}</span>` : ""}
        </button>
      `;
    })
    .join("");

  return `
    <div class="graph-stage">
      ${edges}
      ${nodes}
    </div>
  `;
}

function classTopologyMatches(item, query) {
  const q = normalizeText(query || "");
  if (!q) return true;
  return normalizeText(`${classDisplayName(item) || item.label || ""} ${classDescription(item) || ""} ${item.label || ""} ${item.en || ""} ${item.id || ""} ${(item.keywords || []).join(" ")}`).includes(q);
}

function classMappedInstances(node) {
  if (!node.moduleType) return [];
  const items = entityItems(node.moduleType);
  if (node.moduleType === "device" && Array.isArray(node.keywords) && node.keywords.length) {
    return items.filter((item) => node.keywords.some((keyword) => normalizeText(rowText(item)).includes(normalizeText(keyword))));
  }
  return items;
}

function classNodeEntity(node) {
  const instances = classMappedInstances(node);
  return {
    id: node.id,
    entityType: "class",
    label: classDisplayName(node),
    subtitle: classDescription(node),
    status: node.moduleType ? "mapped" : "class",
    source: node.moduleType ? [`ontology:${ENTITY_META[node.moduleType]?.title || node.moduleType}`] : ["ontology:class-topology"],
    properties: {
      className: node.en || classDisplayName(node),
      displayName: classDisplayName(node),
      mappedModule: node.moduleType ? ENTITY_META[node.moduleType]?.title : "无对应模块",
      instanceCount: instances.length,
    },
    runtime: node.moduleType
      ? {
          mappedModule: ENTITY_META[node.moduleType]?.title || node.moduleType,
          instanceCount: instances.length,
          dataSource: instances.length ? sourceText(instances[0].source) : "暂无实例数据",
        }
      : {},
    instances: instances.map((item) => ({
      id: item.id,
      entityType: node.moduleType,
      label: entityDisplayLabel(item, node.moduleType),
      subtitle: entityDisplaySubtitle(item, node.moduleType),
      status: item.status || "live",
      source: item.source || [],
    })),
    relations: relationRows()
      .filter((edge) => edge.source === node.id || edge.target === node.id)
      .map((edge) => {
        const targetId = edge.source === node.id ? edge.target : edge.source;
        const target = CLASS_TOPOLOGY_NODES.find((item) => item.id === targetId);
        return {
          id: edge.id,
          type: edge.name,
          source: edge.source,
          target: edge.target,
          sourceClass: classNameById(edge.source),
          targetClass: classNameById(edge.target),
          targetType: target?.moduleType || target?.entityType || "",
          targetId,
          label: target ? `${edge.name} ${classDisplayName(target)}` : edge.name,
        };
      }),
  };
}

function findModuleCatalogItem(node) {
  const entityType = node.moduleType;
  const items = entityItems(entityType);
  if (!items.length) return null;

  const keywords = node.keywords || [node.label, node.en, node.id];
  return (
    items.find((item) => keywords.some((keyword) => normalizeText(rowText(item)).includes(normalizeText(keyword)))) ||
    items[0]
  );
}

function openClassTopologyModule(nodeId) {
  const node = CLASS_TOPOLOGY_NODES.find((item) => item.id === nodeId);
  if (!node) return;

  state.selectedEntity = classNodeEntity(node);
  state.selectedEntityType = "class";
  state.selectedEntityId = node.id;
  renderPage();
}

function readStoredSidebarCollapsed() {
  try {
    return localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function storeSidebarCollapsed() {
  try {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, String(state.sidebarCollapsed));
  } catch {
    return;
  }
}

function readStoredNavExpanded() {
  const defaults = { ONTOLOGY: true, TOOLS: true, DATA: true, "AI AGENT": true };
  try {
    const stored = JSON.parse(localStorage.getItem(NAV_STORAGE_KEY) || "{}");
    return { ...defaults, ...(stored && typeof stored === "object" ? stored : {}) };
  } catch {
    return defaults;
  }
}

function storeNavExpanded() {
  try {
    localStorage.setItem(NAV_STORAGE_KEY, JSON.stringify(state.navExpanded));
  } catch {
    return;
  }
}

function classOverride(classId) {
  return state.classState.overrides[classId] || {};
}

function classDisplayName(node) {
  return classOverride(node.id).name || node.label;
}

function classDescription(node) {
  return classOverride(node.id).description || node.description || node.en || `${node.label} ontology class`;
}

function relationId(edge) {
  return edge.id || `${edge.source}__${edge.label}__${edge.target}`.replace(/\s+/g, "-").toLowerCase();
}

function relationOverride(relationIdValue) {
  return state.classState.relationOverrides?.[relationIdValue] || {};
}

function relationDisplayName(relation) {
  return relationOverride(relation.id).name || relation.name || relation.label;
}

function relationDescription(relation) {
  return relationOverride(relation.id).description || relation.description || `${classNameById(relation.source)} ${relationDisplayName(relation)} ${classNameById(relation.target)}`;
}

function classNameById(classId) {
  const node = CLASS_TOPOLOGY_NODES.find((item) => item.id === classId);
  const custom = state.classState.customClasses.find((item) => item.id === classId);
  if (node) return classDisplayName(node);
  if (custom) return classOverride(custom.id).name || custom.name;
  return classId || "-";
}

function isRelationDeleted(relationIdValue) {
  return relationOverride(relationIdValue).deleted === true;
}

function baseRelationRows() {
  return CLASS_TOPOLOGY_EDGES.map((edge) => ({
    id: relationId(edge),
    name: edge.label,
    label: edge.label,
    description: edge.description || `${classNameById(edge.source)} -> ${classNameById(edge.target)}`,
    source: edge.source,
    target: edge.target,
    sourceClass: classNameById(edge.source),
    targetClass: classNameById(edge.target),
    sourceType: "topology",
    sourceKind: "topology",
  }));
}

function relationRows({ includeDeleted = false } = {}) {
  const customRows = state.classState.customRelations.map((item) => ({
    ...item,
    sourceClass: classNameById(item.source),
    targetClass: classNameById(item.target),
    sourceType: "custom",
    sourceKind: "custom",
  }));
  return [...baseRelationRows(), ...customRows]
    .filter((item) => includeDeleted || !isRelationDeleted(item.id))
    .map((item) => ({
      ...item,
      name: relationDisplayName(item),
      label: relationDisplayName(item),
      description: relationDescription(item),
      sourceClass: classNameById(item.source),
      targetClass: classNameById(item.target),
    }));
}

function activeTopologyEdges() {
  return relationRows().map((relation) => ({
    id: relation.id,
    source: relation.source,
    target: relation.target,
    label: relation.name,
  }));
}

function activeNeoTopology() {
  const aliases = { "device-craft": "device-process" };
  const topology = state.neoTopologies[state.classTopologyMode] || state.neoTopologies[aliases[state.classTopologyMode]] || { nodes: [], edges: [] };
  return {
    ...topology,
    edges: (topology.edges || [])
      .filter((edge) => !isRelationDeleted(edge.id || `${topology.key}:${edge.source}:${edge.label}:${edge.target}`))
      .map((edge) => {
        const id = edge.id || `${topology.key}:${edge.source}:${edge.label}:${edge.target}`;
        const override = relationOverride(id);
        return {
          ...edge,
          id,
          label: override.name || edge.label,
          description: override.description || edge.description,
        };
      }),
  };
}

function topologyModeMeta(mode = state.classTopologyMode) {
  return TOPOLOGY_MODES.find((item) => item.key === mode) || TOPOLOGY_MODES[0];
}

function topologyRelationRows() {
  return Object.values(state.neoTopologies).flatMap((topology) =>
    (topology.edges || []).map((edge) => {
      const id = edge.id || `${topology.key}:${edge.source}:${edge.label}:${edge.target}`;
      const row = {
        id,
      name: edge.label || "RELATED_TO",
      label: edge.label || "RELATED_TO",
      description: `${edge.sourceClass || edge.source} -> ${edge.targetClass || edge.target}`,
      source: edge.source,
      target: edge.target,
      sourceClass: edge.sourceClass || edge.source,
      targetClass: edge.targetClass || edge.target,
      sourceType: topology.title || topology.key,
        sourceKind: "neo4j",
      };
      return {
        ...row,
        name: relationDisplayName(row),
        label: relationDisplayName(row),
        description: relationDescription(row),
      };
    })
  ).filter((row) => !isRelationDeleted(row.id));
}

function inferenceRuleRows() {
  const rules = Array.isArray(state.data?.inference?.rules) ? state.data.inference.rules : [];
  return rules.map((rule) => {
    const source = rule.source || "ontology";
    const target = rule.target || "ontology";
    return {
      id: `inference:${rule.id || rule.type}`,
      name: rule.type || rule.id || "推理规则",
      label: rule.type || rule.id || "推理规则",
      description: rule.purpose || rule.conclusion || rule.condition || "",
      source,
      target,
      sourceClass: classNameById(source),
      targetClass: classNameById(target),
      sourceType: "reasoning_service",
      sourceKind: "inference",
      rule,
    };
  });
}

function allRelationRows() {
  return [...relationRows(), ...topologyRelationRows()];
}

function isClassDeleted(classId) {
  return classOverride(classId).deleted === true;
}

function visibleTopologyNodes() {
  return CLASS_TOPOLOGY_NODES.filter((node) => !isClassDeleted(node.id));
}

function classInstanceCount(node) {
  if (node.custom) return 0;
  return classMappedInstances(node).length;
}

function classRows() {
  const baseRows = visibleTopologyNodes()
    .filter((node) => LIST_CLASS_NODE_IDS.has(node.id))
    .map((node) => ({
      id: node.id,
      name: classDisplayName(node),
      description: classDescription(node),
      instances: classInstanceCount(node),
      status: classOverride(node.id).status || "ACTIVE",
      source: "topology",
    }));

  const customRows = state.classState.customClasses
    .filter((item) => !isClassDeleted(item.id))
    .map((item) => ({
      id: item.id,
      name: classOverride(item.id).name || item.name,
      description: classOverride(item.id).description || item.description || "Custom ontology class",
      instances: 0,
      status: classOverride(item.id).status || item.status || "ACTIVE",
      source: "custom",
    }));

  return [...baseRows, ...customRows];
}

function deletedClassRows() {
  const baseRows = CLASS_TOPOLOGY_NODES
    .filter((node) => LIST_CLASS_NODE_IDS.has(node.id) && isClassDeleted(node.id))
    .map((node) => ({
      id: node.id,
      name: classOverride(node.id).name || node.label,
      description: classOverride(node.id).description || node.description || node.en || `${node.label} ontology class`,
      source: "topology",
    }));

  const customRows = state.classState.customClasses
    .filter((item) => isClassDeleted(item.id))
    .map((item) => ({
      id: item.id,
      name: classOverride(item.id).name || item.name,
      description: classOverride(item.id).description || item.description || "Custom ontology class",
      source: "custom",
    }));

  return [...baseRows, ...customRows];
}

function filteredClassRows() {
  const q = normalizeText(state.ontologySearch.classes || "");
  const rows = classRows();
  if (!q) return rows;
  return rows.filter((row) => normalizeText(`${row.name} ${row.description} ${row.status}`).includes(q));
}

function selectClassRow(classId) {
  const node = CLASS_TOPOLOGY_NODES.find((item) => item.id === classId);
  if (node) {
    state.selectedEntity = classNodeEntity(node);
    renderPage();
    return;
  }
  const custom = state.classState.customClasses.find((item) => item.id === classId);
  if (!custom) return;
  state.selectedEntity = {
    id: custom.id,
    entityType: "class",
    label: classOverride(custom.id).name || custom.name,
    subtitle: "自定义类",
    status: classOverride(custom.id).status || custom.status || "ACTIVE",
    source: ["frontend:custom-class"],
    properties: {
      className: classOverride(custom.id).name || custom.name,
      description: classOverride(custom.id).description || custom.description || "自定义本体类",
      mappedModule: "无对应模块",
    },
    runtime: {},
    relations: [],
  };
  renderPage();
}

function createClass() {
  const name = window.prompt("Class name");
  if (!name || !name.trim()) return;
  const description = window.prompt("Class description", "Custom ontology class") || "Custom ontology class";
  const id = `custom-${Date.now()}`;
  state.classState.customClasses.push({ id, name: name.trim(), description: description.trim(), status: "ACTIVE" });
  storeClassState();
  state.classViewMode = "list";
  renderPage();
}

function renameClass(classId) {
  const row = classRows().find((item) => item.id === classId);
  if (!row) return;
  const nextName = window.prompt("Rename class", row.name);
  if (!nextName || !nextName.trim()) return;
  const nextDescription = window.prompt("Edit description", row.description) || row.description;
  state.classState.overrides[classId] = {
    ...classOverride(classId),
    name: nextName.trim(),
    description: nextDescription.trim(),
  };
  storeClassState();
  renderPage();
}

function deleteClass(classId) {
  const row = classRows().find((item) => item.id === classId);
  if (!row) return;
  if (!window.confirm(`Delete class ${row.name}?`)) return;
  state.classState.overrides[classId] = { ...classOverride(classId), deleted: true };
  storeClassState();
  if (state.selectedEntity?.id === classId) state.selectedEntity = null;
  renderPage();
}

function restoreClass(classId) {
  const override = classOverride(classId);
  if (!override.deleted) return;
  const nextOverride = { ...override };
  delete nextOverride.deleted;
  state.classState.overrides[classId] = nextOverride;
  storeClassState();
  state.classRecycleOpen = deletedClassRows().length > 0;
  renderPage();
}

function renderClassRecycleBin(rows) {
  if (!state.classRecycleOpen) return "";
  return `
    <section class="class-recycle-panel">
      <div class="panel-header panel-header-spread">
        <div>
          <h3>回收站</h3>
          <p class="panel-muted">恢复已删除的本体类</p>
        </div>
        <span class="meta-pill">${rows.length} 个已删除</span>
      </div>
      ${rows.length ? `
        <div class="class-recycle-list">
          ${rows.map((row) => `
            <article class="class-recycle-item">
              <span>
                <strong>${escapeHtml(row.name)}</strong>
                <small>${escapeHtml(row.description)}</small>
              </span>
              <button class="class-action-btn" data-class-action="restore" data-class-id="${escapeHtml(row.id)}" type="button">恢复</button>
            </article>
          `).join("")}
        </div>
      ` : "<p class='panel-muted'>回收站为空</p>"}
    </section>
  `;
}

function renderClassesList() {
  const rows = filteredClassRows();
  return `
    <div class="class-table-wrap">
      <table class="class-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Description</th>
            <th>Instances</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          ${rows.length ? rows.map((row) => `
            <tr data-class-row-id="${escapeHtml(row.id)}">
              <td>
                <button class="class-name-cell" data-class-select="${escapeHtml(row.id)}" type="button">
                  <span class="class-dot"></span>
                  <strong>${escapeHtml(row.name)}</strong>
                </button>
              </td>
              <td>${escapeHtml(row.description)}</td>
              <td><span class="class-count">${row.instances}</span></td>
              <td><span class="status-chip online">${escapeHtml(row.status)}</span></td>
              <td>
                <div class="class-actions">
                  <button class="class-action-btn" data-class-action="rename" data-class-id="${escapeHtml(row.id)}" type="button">Rename</button>
                  <button class="class-action-btn danger" data-class-action="delete" data-class-id="${escapeHtml(row.id)}" type="button">Delete</button>
                </div>
              </td>
            </tr>
          `).join("") : `
            <tr>
              <td colspan="5" class="class-table-empty">暂无 class，请点击 New Class 新建</td>
            </tr>
          `}
        </tbody>
      </table>
    </div>
  `;
}

function topologyNodeLabel(nodeId, lookup) {
  const node = lookup.get(nodeId);
  return node?.label || node?.id || nodeId;
}

function isProductProcessStepEdge(edge, product, step) {
  if (!edge || !product || !step) return false;
  if (String(edge.label || "").toLowerCase() !== "has_step") return false;
  return (edge.source === product.id && edge.target === step.id) || (edge.target === product.id && edge.source === step.id);
}

function relatedProcessSteps(product, edges, nodeLookup) {
  return edges
    .map((edge) => {
      if (String(edge.label || "").toLowerCase() !== "has_step") return null;
      const source = nodeLookup.get(edge.source);
      const target = nodeLookup.get(edge.target);
      if (!source || !target) return null;
      if (source.id === product.id && topologyNodeSemanticType(target) === "process") return target;
      if (target.id === product.id && topologyNodeSemanticType(source) === "process") return source;
      return null;
    })
    .filter(Boolean);
}

function processFlowDescription(node, topology = activeNeoTopology()) {
  if (!node || state.classTopologyMode !== "product-process" || topologyNodeSemanticType(node) !== "process") {
    return node?.properties?.description || node?.subtitle || "";
  }
  const nodeLookup = new Map((topology.nodes || []).map((item) => [item.id, item]));
  const outbound = (topology.edges || []).filter((edge) => edge.source === node.id);
  const inbound = (topology.edges || []).filter((edge) => edge.target === node.id);
  const uses = outbound
    .filter((edge) => String(edge.label || "").toLowerCase() === "uses")
    .map((edge) => topologyNodeLabel(edge.target, nodeLookup));
  const produces = outbound
    .filter((edge) => String(edge.label || "").toLowerCase() === "produces")
    .map((edge) => topologyNodeLabel(edge.target, nodeLookup));
  const product = inbound
    .filter((edge) => String(edge.label || "").toLowerCase() === "has_step")
    .map((edge) => topologyNodeLabel(edge.source, nodeLookup))[0];
  const parts = [];
  if (product) parts.push(`所属产品：${product}`);
  if (uses.length) parts.push(`使用物料/部件：${uses.join("、")}`);
  if (produces.length) parts.push(`产出部件：${produces.join("、")}`);
  return parts.join("；") || node.properties?.description || node.subtitle || "";
}

function topologyNodeTypeLabel(node) {
  const semantic = topologyNodeSemanticType(node || {});
  if (semantic === "product") return "Product";
  if (semantic === "process") return "Process";
  if (semantic === "material") return "Material";
  if (semantic === "part") return "Part";
  if (semantic === "device") return "Device";
  if (semantic === "craft") return "Craft";
  return node?.entityType || "Entity";
}

function selectedTopologyNode() {
  if (!state.selectedEntity?.id) return null;
  return (activeNeoTopology().nodes || []).find((node) => node.id === state.selectedEntity.id) || null;
}

function topologyNeighborhood(rootId, topology = activeNeoTopology()) {
  if (!rootId) return topology;
  const nodes = topology.nodes || [];
  const edges = topology.edges || [];
  const selected = nodes.find((node) => node.id === rootId);
  if (!selected) return topology;

  const included = new Set([rootId]);
  const selectedType = topologyNodeSemanticType(selected);
  if (state.classTopologyMode === "product-process" && selectedType === "product") {
    edges.forEach((edge) => {
      if (edge.source !== rootId) return;
      included.add(edge.target);
      edges.forEach((childEdge) => {
        if (childEdge.source === edge.target) included.add(childEdge.target);
      });
    });
  } else {
    edges.forEach((edge) => {
      if (edge.source === rootId) included.add(edge.target);
      if (edge.target === rootId) included.add(edge.source);
    });
  }

  return {
    ...topology,
    nodes: nodes.filter((node) => included.has(node.id)),
    edges: edges.filter((edge) => included.has(edge.source) && included.has(edge.target)),
  };
}

function renderInstanceViewToggle() {
  return `
    <div class="instance-view-toggle" role="group" aria-label="Instance view">
      <button class="toolbar-btn ${state.classInstanceViewMode === "list" ? "primary" : ""}" data-instance-view="list" type="button">List</button>
      <button class="toolbar-btn ${state.classInstanceViewMode === "topology" ? "primary" : ""}" data-instance-view="topology" type="button">Topology</button>
    </div>
  `;
}

function renderSelectedTopologyInstancePanel() {
  const selected = selectedTopologyNode();
  if (!selected) {
    return `
      <aside class="topology-instance-panel">
        <div class="entity-card-head">
          <div>
            <p class="panel-eyebrow">Instance</p>
            <h3>未选择实例</h3>
            <p class="panel-muted">选择左侧产品、设备或工艺实例后查看对应局部结构</p>
          </div>
        </div>
      </aside>
    `;
  }

  const entity = topologyNodeEntity(selected);
  const description = processFlowDescription(selected);
  if (description) {
    entity.properties = { ...(entity.properties || {}), description };
    entity.subtitle = topologyNodeSemanticType(selected) === "process" ? "工序 Detail" : entity.subtitle;
  }
  return `
    <aside class="topology-instance-panel">
      <div class="entity-card-head">
        <div>
          <p class="panel-eyebrow">${escapeHtml(topologyNodeTypeLabel(selected))}</p>
          <h3>${escapeHtml(selected.label || selected.id)}</h3>
          <p class="panel-muted">${escapeHtml(selected.subtitle || selected.entityType || "")}</p>
        </div>
      </div>
      ${renderInstanceViewToggle()}
      <div class="panel-divider"></div>
      ${state.classInstanceViewMode === "topology"
        ? renderNeoTopology(topologyNeighborhood(selected.id), state.classTopologyMode)
        : entityPanel(entity)}
    </aside>
  `;
}

function renderProductProcessTreeList() {
  const topology = activeNeoTopology();
  const query = normalizeText(state.ontologySearch.classes || "");
  const nodes = topology.nodes || [];
  const nodeLookup = new Map(nodes.map((node) => [node.id, node]));
  const edges = (topology.edges || []).filter((edge) => nodeLookup.has(edge.source) && nodeLookup.has(edge.target));
  const products = nodes.filter((node) => topologyNodeSemanticType(node) === "product");
  const productBlocks = products.map((product) => {
    const steps = relatedProcessSteps(product, edges, nodeLookup);
    const searchable = [
      product.label,
      product.subtitle,
      product.id,
      ...steps.flatMap((step) => {
        const stepEdges = edges.filter((edge) => edge.source === step.id);
        return [
          step.label,
          step.subtitle,
          ...stepEdges.map((edge) => topologyNodeLabel(edge.target, nodeLookup)),
        ];
      }),
    ].join(" ");
    return { product, steps, searchable };
  }).filter((block) => !query || normalizeText(block.searchable).includes(query));

  return `
    <div class="topology-instance-layout">
      <div class="isa-tree-wrap">
        <div class="panel-subtitle">ISA-95 / IEC 62264 BOM / Process Tree</div>
        ${productBlocks.length ? productBlocks.map(({ product, steps }) => `
          <article class="isa-folder ${state.selectedEntity?.id === product.id ? "is-selected" : ""}">
            <div class="isa-folder-head">
              <button class="isa-tree-toggle" data-product-tree-toggle="${escapeHtml(product.id)}" type="button" aria-label="Toggle product steps">
                ${state.productProcessExpanded[product.id] === false ? ">" : "v"}
              </button>
              <button class="isa-folder-main" data-topology-node-id="${escapeHtml(product.id)}" type="button">
                <span class="isa-folder-icon">PD</span>
                <span>
                  <strong>${escapeHtml(product.label || product.id)}</strong>
                  <small>${escapeHtml(product.subtitle || "Product")}</small>
                </span>
              </button>
            </div>
            <div class="isa-folder-children ${state.productProcessExpanded[product.id] === false ? "is-collapsed" : ""}">
              ${steps.length ? steps.map((step) => {
                return `
                  <section class="isa-process-branch">
                    <button class="isa-process-node" data-topology-node-id="${escapeHtml(step.id)}" type="button">
                      <span class="isa-branch-line" aria-hidden="true"></span>
                      <span class="entity-type-pill">PR</span>
                      <span>
                        <strong>${escapeHtml(step.label || step.id)}</strong>
                        <small>${escapeHtml(step.subtitle || "Process")}</small>
                      </span>
                    </button>
                  </section>
                `;
              }).join("") : `<p class="panel-muted">该产品暂无工序节点</p>`}
            </div>
          </article>
        `).join("") : `<p class="panel-muted">暂无产品-工序拓扑数据。</p>`}
      </div>
      ${renderSelectedTopologyInstancePanel()}
    </div>
  `;
}

function renderTopologyRowsList() {
  const topology = activeNeoTopology();
  const nodeLookup = new Map((topology.nodes || []).map((node) => [node.id, node]));
  const rows = (topology.edges || []).filter((edge) => {
    const text = `${edge.label || ""} ${topologyNodeLabel(edge.source, nodeLookup)} ${topologyNodeLabel(edge.target, nodeLookup)}`;
    return normalizeText(text).includes(normalizeText(state.ontologySearch.classes || ""));
  });
  return `
    <div class="topology-instance-layout">
      <div class="class-table-wrap">
        <table class="class-table">
          <thead><tr><th>Source</th><th>Relation</th><th>Target</th><th>Source Type</th><th>Target Type</th></tr></thead>
          <tbody>
            ${rows.length ? rows.map((edge) => {
              const source = nodeLookup.get(edge.source);
              const target = nodeLookup.get(edge.target);
              return `<tr>
                <td><button class="class-name-cell" data-topology-node-id="${escapeHtml(edge.source)}" type="button"><strong>${escapeHtml(source?.label || edge.source)}</strong></button></td>
                <td>${escapeHtml(edge.label || "RELATED_TO")}</td>
                <td><button class="class-name-cell" data-topology-node-id="${escapeHtml(edge.target)}" type="button"><strong>${escapeHtml(target?.label || edge.target)}</strong></button></td>
                <td>${escapeHtml(topologyNodeTypeLabel(source))}</td>
                <td>${escapeHtml(topologyNodeTypeLabel(target))}</td>
              </tr>`;
            }).join("") : `<tr><td colspan="5" class="class-table-empty">该拓扑暂无关系。</td></tr>`}
          </tbody>
        </table>
      </div>
      ${renderSelectedTopologyInstancePanel()}
    </div>
  `;
}

function renderActiveClassList() {
  if (state.classTopologyMode === "production") return renderClassesList();
  if (state.classTopologyMode === "product-process") return renderProductProcessTreeList();
  return renderTopologyRowsList();
}

function filteredRelationRows() {
  const q = normalizeText(state.ontologySearch.relations || "");
  const rows = allRelationRows();
  if (!q) return rows;
  return rows.filter((row) =>
    normalizeText(`${row.name} ${row.description} ${row.sourceClass} ${row.targetClass} ${row.sourceType}`).includes(q)
  );
}

function relationClassOptions() {
  return visibleTopologyNodes().map((node) => ({ id: node.id, name: classDisplayName(node) }));
}

function findRelationClass(value) {
  const q = normalizeText(value || "");
  if (!q) return null;
  return relationClassOptions().find((item) => normalizeText(item.id) === q || normalizeText(item.name) === q);
}

function createRelation() {
  const optionsText = relationClassOptions().map((item) => `${item.name}(${item.id})`).join(", ");
  const name = window.prompt("Enter relation name");
  if (!name || !name.trim()) return;
  const description = window.prompt("Enter relation description", `${name.trim()} relation`) || `${name.trim()} relation`;
  const sourceInput = window.prompt(`Enter Source Class name or id\nOptions: ${optionsText}`);
  const source = findRelationClass(sourceInput);
  if (!source) {
    window.alert("Source Class not found. Use an existing topology class name or id.");
    return;
  }
  const targetInput = window.prompt(`Enter Target Class name or id\nOptions: ${optionsText}`);
  const target = findRelationClass(targetInput);
  if (!target) {
    window.alert("Target Class not found. Use an existing topology class name or id.");
    return;
  }
  const id = `custom-relation-${Date.now()}`;
  state.classState.customRelations.push({
    id,
    name: name.trim(),
    label: name.trim(),
    description: description.trim(),
    source: source.id,
    target: target.id,
  });
  storeClassState();
  renderPage();
}

function renameRelation(relationIdValue) {
  const row = allRelationRows().find((item) => item.id === relationIdValue);
  if (!row) return;
  const nextName = window.prompt("Rename Relation", row.name);
  if (!nextName || !nextName.trim()) return;
  const nextDescription = window.prompt("修改描述", row.description) || row.description;
  state.classState.relationOverrides[relationIdValue] = {
    ...relationOverride(relationIdValue),
    name: nextName.trim(),
    description: nextDescription.trim(),
  };
  storeClassState();
  renderPage();
}

function deleteRelation(relationIdValue) {
  const row = allRelationRows().find((item) => item.id === relationIdValue);
  if (!row) return;
  if (!window.confirm(`Delete Relation: ${row.name}?`)) return;
  state.classState.relationOverrides[relationIdValue] = { ...relationOverride(relationIdValue), deleted: true };
  storeClassState();
  if (state.selectedEntity?.entityType === "class") {
    const selectedNode = CLASS_TOPOLOGY_NODES.find((node) => node.id === state.selectedEntity.id);
    state.selectedEntity = selectedNode ? classNodeEntity(selectedNode) : state.selectedEntity;
  }
  renderPage();
}

function renderRelationsPage() {
  const rows = filteredRelationRows();
  const total = allRelationRows().length;
  return `
    <section class="page-grid">
      <article class="panel-card full-width">
        <div class="panel-header panel-header-spread">
          <div>
            <h2>Relations</h2>
            <p class="panel-muted">管理智能产线本体类之间的关系定义。</p>
          </div>
          <div class="metric-group">${renderMetricPills([`${rows.length}/${total} 条关系`, statusBadgeText()])}</div>
        </div>
        <div class="class-toolbar">
          ${renderOntologySearch("relations", "搜索关系...")}
          <div class="class-toolbar-actions">
            <button class="toolbar-btn primary" data-relation-action="new" type="button">+ 新建关系</button>
          </div>
        </div>
        <div class="class-table-wrap relation-table-wrap">
          <table class="class-table relation-table">
            <thead>
              <tr>
                <th>Relation</th>
                <th>Description</th>
                <th>Source Class</th>
                <th>Target Class</th>
                <th>Source</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              ${rows.length ? rows.map((row) => `
                <tr>
                  <td>
                    <span class="class-name-cell relation-name-cell">
                      ${typeIconHtml("relation", row.name)}
                      <strong>${escapeHtml(row.name)}</strong>
                    </span>
                  </td>
                  <td>${escapeHtml(row.description)}</td>
                  <td>${escapeHtml(row.sourceClass)}</td>
                  <td>${escapeHtml(row.targetClass)}</td>
                  <td>${escapeHtml(row.sourceType || "-")}</td>
                  <td>
                    ${row.sourceKind === "inference" ? `<span class="status-pill">系统规则</span>` : `
                      <div class="class-actions">
                        <button class="class-action-btn" data-relation-action="rename" data-relation-id="${escapeHtml(row.id)}" type="button">重命名</button>
                        <button class="class-action-btn danger" data-relation-action="delete" data-relation-id="${escapeHtml(row.id)}" type="button">删除</button>
                      </div>
                    `}
                  </td>
                </tr>
              `).join("") : `
                <tr>
                  <td colspan="6" class="class-table-empty">暂无关系，可点击“新建关系”创建。</td>
                </tr>
              `}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  `;
}
function clampTopologyScale(value) {
  return Math.min(1.35, Math.max(0.48, Number(value) || 0.78));
}

function topologyTransformStyle() {
  const view = state.topologyView;
  return `transform: translate(${view.x}px, ${view.y}px) scale(${view.scale});`;
}

function classNodeById(nodeId) {
  return CLASS_TOPOLOGY_NODES.find((node) => node.id === nodeId);
}

function classNodeCenter(node) {
  return { x: node.x + CLASS_NODE_WIDTH / 2, y: node.y + CLASS_NODE_HEIGHT / 2 };
}

function edgeAnchor(source, target) {
  const sourceCenter = classNodeCenter(source);
  const targetCenter = classNodeCenter(target);
  const dx = targetCenter.x - sourceCenter.x;
  const dy = targetCenter.y - sourceCenter.y;

  if (Math.abs(dx) >= Math.abs(dy)) {
    return {
      start: { x: sourceCenter.x + Math.sign(dx || 1) * CLASS_NODE_WIDTH / 2, y: sourceCenter.y },
      end: { x: targetCenter.x - Math.sign(dx || 1) * CLASS_NODE_WIDTH / 2, y: targetCenter.y },
    };
  }

  return {
    start: { x: sourceCenter.x, y: sourceCenter.y + Math.sign(dy || 1) * CLASS_NODE_HEIGHT / 2 },
    end: { x: targetCenter.x, y: targetCenter.y - Math.sign(dy || 1) * CLASS_NODE_HEIGHT / 2 },
  };
}

function edgePoints(edge, nodeLookup = null) {
  const source = nodeLookup?.get(edge.source) || classNodeById(edge.source);
  const target = nodeLookup?.get(edge.target) || classNodeById(edge.target);
  if (!source || !target) return [];

  const { start, end } = edgeAnchor(source, target);
  const laneOffset = Number(edge.laneOffset || 0);
  if (edge.diagonal) {
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const length = Math.hypot(dx, dy) || 1;
    const offsetX = (-dy / length) * laneOffset * 0.35;
    const offsetY = (dx / length) * laneOffset * 0.35;
    return [
      { x: start.x + offsetX, y: start.y + offsetY },
      { x: end.x + offsetX, y: end.y + offsetY },
    ];
  }
  if (Math.abs(end.x - start.x) >= Math.abs(end.y - start.y)) {
    const midX = Math.round((start.x + end.x) / 2 + laneOffset);
    return [start, { x: midX, y: start.y }, { x: midX, y: end.y }, end];
  }
  const midY = Math.round((start.y + end.y) / 2 + laneOffset);
  return [start, { x: start.x, y: midY }, { x: end.x, y: midY }, end];
}

function edgeLaneOffsets(edges, step = 40) {
  const groups = new Map();
  edges.forEach((edge) => {
    const key = edge.label ? `${edge.source}__${edge.label}` : `${edge.source}__${edge.target}`;
    const list = groups.get(key) || [];
    list.push(edge);
    groups.set(key, list);
  });

  const offsets = new Map();
  groups.forEach((group) => {
    group.forEach((edge, index) => {
      const center = (group.length - 1) / 2;
      offsets.set(edge.id || `${edge.source}:${edge.target}:${index}`, (index - center) * step);
    });
  });
  return offsets;
}

function withEdgeLanes(edges, mode = "production") {
  const laneStep = mode === "device-craft" ? 28 : 40;
  const labelStep = mode === "device-craft" ? 10 : 14;
  const offsets = edgeLaneOffsets(edges, laneStep);
  return edges.map((edge, index) => ({
    ...edge,
    laneOffset: offsets.get(edge.id || `${edge.source}:${edge.target}:${index}`) || 0,
    labelOffset: ((index % 5) - 2) * labelStep,
  }));
}

function edgePointString(points) {
  return points.map((point) => `${Math.round(point.x)},${Math.round(point.y)}`).join(" ");
}

function edgeLabelPosition(points, edge = {}) {
  if (!points.length) return { x: 0, y: 0 };
  const segments = points.slice(1).map((point, index) => {
    const previous = points[index];
    return { start: previous, end: point, length: Math.hypot(point.x - previous.x, point.y - previous.y) };
  });
  const totalLength = segments.reduce((sum, segment) => sum + segment.length, 0);
  let remaining = totalLength / 2;

  for (const segment of segments) {
    if (remaining <= segment.length) {
      const ratio = segment.length ? remaining / segment.length : 0;
      return {
        x: segment.start.x + (segment.end.x - segment.start.x) * ratio,
        y: segment.start.y + (segment.end.y - segment.start.y) * ratio - 18 + (Number(edge.labelOffset) || 0),
      };
    }
    remaining -= segment.length;
  }

  const last = points[points.length - 1];
  return { x: last.x, y: last.y - 18 + (Number(edge.labelOffset) || 0) };
}

function edgeGeometry(edge, nodeLookup = null) {
  const points = edgePoints(edge, nodeLookup);
  const label = edgeLabelPosition(points, edge);
  return { points: edgePointString(points), label };
}

function renderProductionClassTopology() {
  const query = state.ontologySearch.classes;
  const visibleNodes = visibleTopologyNodes().filter((node) => classTopologyMatches(node, query));
  const visibleNodeIds = new Set(visibleNodes.map((node) => node.id));
  const visibleEdges = withEdgeLanes(activeTopologyEdges().filter(
    (edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target) && (!query || visibleNodeIds.has(edge.source) || visibleNodeIds.has(edge.target) || classTopologyMatches(edge, query))
  ));

  return `
    <div class="production-topology-scroll">
      <div class="topology-controls" aria-label="拓扑缩放控制">
        <button class="topology-control-btn" data-topology-action="zoom-out" type="button">-</button>
        <span class="topology-scale-readout">${Math.round(state.topologyView.scale * 100)}%</span>
        <button class="topology-control-btn" data-topology-action="zoom-in" type="button">+</button>
        <button class="topology-control-btn wide" data-topology-action="reset" type="button">Reset</button>
      </div>
      <div class="production-topology-map" data-topology-map style="${topologyTransformStyle()}">
        <svg class="production-topology-lines" viewBox="0 0 1880 800" preserveAspectRatio="none" aria-hidden="true">
          <defs>
            <marker id="relationship-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth">
              <path d="M0,0 L8,4 L0,8 Z"></path>
            </marker>
          </defs>
          ${visibleEdges
            .map(
              (edge) => {
                const geometry = edgeGeometry(edge);
                return `
                  <polyline class="production-edge" data-edge-source="${escapeHtml(edge.source)}" data-edge-target="${escapeHtml(edge.target)}" data-edge-lane-offset="${Number(edge.laneOffset) || 0}" data-edge-label-offset="${Number(edge.labelOffset) || 0}" data-edge-diagonal="${edge.diagonal ? "true" : "false"}" points="${escapeHtml(geometry.points)}" marker-end="url(#relationship-arrow)"></polyline>
                  ${edge.label ? `<text class="production-edge-label" data-edge-label-source="${escapeHtml(edge.source)}" data-edge-label-target="${escapeHtml(edge.target)}" data-edge-label-lane-offset="${Number(edge.laneOffset) || 0}" data-edge-label-offset="${Number(edge.labelOffset) || 0}" data-edge-label-diagonal="${edge.diagonal ? "true" : "false"}" x="${geometry.label.x}" y="${geometry.label.y}">${escapeHtml(edge.label)}</text>` : ""}
                `;
              }
            )
            .join("")}
        </svg>
        ${visibleNodes
          .map(
            (node) => `
              <button
                class="production-class-node node-${escapeHtml(node.tone)} ${node.moduleType ? "module-mapped" : "module-unmapped"}"
                data-class-node-id="${escapeHtml(node.id)}"
                data-draggable-class-node="${escapeHtml(node.id)}"
                aria-pressed="${state.selectedEntity?.entityType === "class" && state.selectedEntity?.id === node.id ? "true" : "false"}"
                style="left:${node.x}px;top:${node.y}px"
                type="button"
              >
                <span class="node-icon">${escapeHtml(classDisplayName(node).slice(0, 1))}</span>
                <span class="node-copy">
                  <strong>${escapeHtml(classDisplayName(node))}</strong>
                </span>
              </button>
            `
          )
          .join("")}
      </div>
    </div>
  `;
}

function updateSelectedEntityFromCatalog(entityType, entityId) {
  const items = entityItems(entityType);
  const item =
    items.find((entry) => entry.id === entityId) ||
    items.find(
      (entry) =>
        normalizeText(entry.label || "") === normalizeText(entityId) ||
        normalizeText(entry.name || "") === normalizeText(entityId) ||
        normalizeText(entry.id || "") === normalizeText(entityId)
    );

  if (!item) {
    const classNode = CLASS_TOPOLOGY_NODES.find((node) => node.id === entityId);
    state.selectedEntity = classNode ? classNodeEntity(classNode) : null;
    state.selectedEntityType = entityType;
    state.selectedEntityId = entityId;
    return;
  }

  state.selectedEntity = {
    id: item.id,
    entityType,
    label: entityDisplayLabel(item, entityType),
    subtitle: entityDisplaySubtitle(item, entityType),
    status: entityType === "device" ? deviceDisplayStatus({ ...(item.properties || {}), ...(item.runtime || {}), status: item.status }) : item.status || "live",
    source: item.source || [],
    properties: item.properties || item,
    runtime: item.runtime || item.properties || {},
    relations: item.relations || [],
  };
  state.selectedEntityType = entityType;
  state.selectedEntityId = item.id;
}

async function openEntity(entityType, entityId) {
  const normalizedType = entityType.replace(/^process_instance$/, "work_order");
  if (MYSQL_ENTITY_TYPES.has(normalizedType)) {
    const exactItem = entityItems(normalizedType).find((entry) => entry.id === entityId);
    if (exactItem) {
      updateSelectedEntityFromCatalog(normalizedType, entityId);
      renderPage();
      return;
    }
  }
  try {
    const response = await fetchJson(`/api/digital-twin/entities/${normalizedType}/${encodeURIComponent(entityId)}`);
    if (response.ok && response.entity) {
      state.selectedEntity = response.entity;
      state.selectedEntityType = response.entity.entityType || normalizedType;
      state.selectedEntityId = response.entity.id || entityId;
    } else {
      updateSelectedEntityFromCatalog(normalizedType, entityId);
    }
  } catch {
    updateSelectedEntityFromCatalog(normalizedType, entityId);
  }
  renderPage();
}

function valueText(value, fallback = "-") {
  if (value === undefined || value === null || value === "") return fallback;
  if (Array.isArray(value) || typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function isRuntimeField(label) {
  const key = normalizeText(label);
  return [
    "status",
    "state",
    "runtime",
    "workstatus",
    "transportstatus",
    "task",
    "workorder",
    "current",
    "start",
    "end",
    "time",
    "load",
    "任务",
    "状态",
    "运行",
    "工单",
    "运输",
    "开始",
    "结束",
    "负载",
  ].some((token) => key.includes(normalizeText(token)));
}

function splitDeviceFields(entity) {
  const props = entity?.properties || {};
  const baseEntries = Object.entries(props).filter(([key]) => key !== "__table");
  const deviceEntries = baseEntries
    .filter(([key]) => !isRuntimeField(key))
    .slice(0, 12);

  return {
    deviceEntries: deviceEntries.length ? deviceEntries : baseEntries.filter(([key]) => !isRuntimeField(key)).slice(0, 8),
  };
}

function renderFieldCards(entries, emptyText) {
  if (!entries.length) {
    return `<div class="property-card-empty">${escapeHtml(emptyText)}</div>`;
  }
  return entries
    .map(([label, value]) => `
      <div class="property-data-card">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(valueText(value))}</strong>
      </div>
    `)
    .join("");
}

function renderDevicePropertyPanel(entity) {
  const props = entity.properties || {};
  const runtime = entity.runtime || {};
  const record = { ...props, ...runtime, status: entity.status };
  const source = Array.isArray(entity.source) ? entity.source.join(" · ") : String(entity.source || "-");
  const { deviceEntries } = splitDeviceFields(entity);
  const deviceId = firstField(props, ["设备编号", "设备ID", "AGV编号", "device_id", "deviceId", "agv_id", "agvId", "code", "id"], entity.id);
  const deviceType = firstField(props, ["设备类型", "类型", "device_type", "deviceType", "type"], entity.subtitle || "设备");
  const status = deviceDisplayStatus(record, entity.status || firstField(props, ["设备状态", "status", "state"], "实时"));

  return `
    <article class="entity-card property-panel device-property-panel">
      <div class="entity-card-head">
        <div>
          <h3>${escapeHtml(entity.label || entity.id)}</h3>
          <p class="panel-muted">${escapeHtml(entity.subtitle || deviceType || "设备")}</p>
        </div>
        <span class="status-chip ${statusClass(status)}">${escapeHtml(status)}</span>
      </div>

      <div class="device-property-visual">
        <div class="device-node-visual">
          ${typeIconHtml(entityIconType("device", props), entity.label || entity.id)}
          <span>${escapeHtml(deviceType)}</span>
        </div>
        <div class="device-property-flow">
          <span>设备数据</span>
          <strong>${escapeHtml(deviceId || "-")}</strong>
        </div>
        <div class="device-property-flow">
          <span>设备类型</span>
          <strong>${escapeHtml(deviceType || "-")}</strong>
        </div>
        <div class="device-property-flow">
          <span>数据来源</span>
          <strong>${escapeHtml(source)}</strong>
        </div>
      </div>

      <div class="property-two-column">
        <section class="property-section">
          <div class="panel-subtitle">设备数据</div>
          <div class="property-card-grid">${renderFieldCards(deviceEntries, "暂无设备基础数据")}</div>
        </section>
      </div>
    </article>
  `;
}

function entityPanel(entity) {
  if (!entity) {
    return `
      <article class="entity-card">
        <div class="entity-card-head">
          <div>
            <h3>属性视图</h3>
            <p class="panel-muted">选择节点或列表行后查看实体属性。</p>
          </div>
        </div>
      </article>
    `;
  }

  const props = entity.properties || {};
  const runtime = entity.runtime || {};
  const relations = entity.relations || [];
  const instances = Array.isArray(entity.instances) ? entity.instances : [];
  const source = Array.isArray(entity.source) ? entity.source.join(" · ") : String(entity.source || "-");
  const entries = Object.entries({
    id: entity.id,
    label: entity.label,
    subtitle: entity.subtitle,
    entityType: entity.entityType,
    status: entity.status || "",
    source,
  }).filter(([, value]) => value !== "");

  if (entity.entityType === "device") {
    return renderDevicePropertyPanel(entity);
  }

  return `
    <article class="entity-card property-panel">
      <div class="entity-card-head">
        <div>
          <h3>${escapeHtml(entity.label || entity.id)}</h3>
          <p class="panel-muted">${escapeHtml(entity.subtitle || entity.entityType || "实体")}</p>
        </div>
        <span class="status-chip ${entity.status && String(entity.status).includes("预警") ? "alarm" : "online"}">${escapeHtml(entity.status || entity.entityType || "实时")}</span>
      </div>
      <div class="entity-fields">
        ${entries.map(([label, value]) => `<span>${escapeHtml(PROPERTY_FIELD_LABELS[label] || label)}</span><span>${escapeHtml(value)}</span>`).join("")}
      </div>
      <div class="panel-divider"></div>
      <div class="panel-subtitle">属性</div>
      <div class="entity-fields">
        ${Object.entries(props)
          .slice(0, 12)
          .map(([label, value]) => `<span>${escapeHtml(label)}</span><span>${escapeHtml(value)}</span>`)
          .join("") || "<span>提示</span><span>无属性数据</span>"}
      </div>
      <div class="panel-divider"></div>
      <div class="panel-subtitle">运行态</div>
      <div class="entity-fields">
        ${Object.entries(runtime)
          .slice(0, 12)
          .map(([label, value]) => `<span>${escapeHtml(label)}</span><span>${escapeHtml(value)}</span>`)
          .join("") || "<span>提示</span><span>无运行态数据</span>"}
      </div>
      ${entity.status === "mapped" ? `
        <div class="panel-divider"></div>
        <div class="panel-subtitle">映射实例</div>
        <div class="mapped-instance-list">
          ${instances.length
            ? instances
                .slice(0, 12)
                .map(
                  (item) => `
                    <button class="mapped-instance-card entity-clickable" data-entity-type="${escapeHtml(item.entityType || "")}" data-entity-id="${escapeHtml(item.id || "")}" type="button">
                      ${typeIconHtml(entityIconType(item.entityType || "ontology", item), item.label || item.id || "实例")}
                      <span>
                        <strong>${escapeHtml(item.label || item.id || "实例")}</strong>
                        <small>${escapeHtml(item.subtitle || sourceText(item.source) || item.entityType || "")}</small>
                      </span>
                      <em>${escapeHtml(item.status || "实时")}</em>
                    </button>
                  `
                )
                .join("")
            : "<span class='panel-muted'>当前模块暂无可显示实例数据</span>"}
        </div>
      ` : ""}
      <div class="panel-divider"></div>
      <div class="panel-subtitle">关系</div>
      <div class="relation-list">
        ${relations.length
          ? relations
              .map(
                (relation) => `
                  <button class="relation-chip relation-clickable" data-target-type="${escapeHtml(relation.targetType || "")}" data-target-id="${escapeHtml(relation.targetId || "")}" type="button">
                    ${escapeHtml(relation.type || relation.label || "REL")}
                  </button>
                `
              )
              .join("")
          : "<span class='panel-muted'>暂无关系</span>"}
      </div>
    </article>
  `;
}

function topologyNodeMatches(node, query) {
  const q = normalizeText(query || "");
  if (!q) return true;
  return normalizeText(`${node.label || ""} ${node.subtitle || ""} ${node.id || ""} ${node.entityType || ""} ${rowText(node.properties || {})}`).includes(q);
}

function topologyNodePositionKey(mode, nodeId) {
  return `${mode || "production"}:${nodeId}`;
}

function topologyNodeSemanticType(node) {
  const text = normalizeText(`${node.entityType || ""} ${node.label || ""} ${node.subtitle || ""} ${node.id || ""}`);
  const entityType = normalizeText(node.entityType || "");
  if (entityType === "process" || entityType === "processinstance" || entityType === "assemblystep") return "process";
  if (entityType === "product") return "product";
  if (entityType === "material") return "material";
  if (entityType === "part") return "part";
  if (entityType === "device") return "device";
  if (entityType === "craft") return "craft";
  if (text.includes("craft")) return "craft";
  if (text.includes("device") || text.includes("workstation") || text.includes("station") || text.includes("warehouse") || text.includes("agv")) return "device";
  if (text.includes("processinstance") || text.includes("assemblystep") || text.includes("process")) return "process";
  if (text.includes("product")) return "product";
  if (text.includes("part") || text.includes("component")) return "part";
  if (text.includes("material")) return "material";
  return node.entityType || "entity";
}

function layoutNeoTopologyNodes(topology, nodes, mode = state.classTopologyMode) {
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const edges = (topology.edges || []).filter((edge) => nodeMap.has(edge.source) && nodeMap.has(edge.target));
  const incoming = new Map();
  const outgoing = new Map();
  edges.forEach((edge) => {
    incoming.set(edge.target, (incoming.get(edge.target) || 0) + 1);
    outgoing.set(edge.source, (outgoing.get(edge.source) || 0) + 1);
  });

  const savedOrPlaced = (node, x, y) => {
    const saved = state.topologyNodePositions[topologyNodePositionKey(mode, node.id)];
    return saved ? { ...node, x: saved.x, y: saved.y } : { ...node, x, y };
  };
  const sortByTraffic = (a, b) =>
    ((outgoing.get(b.id) || 0) + (incoming.get(b.id) || 0)) - ((outgoing.get(a.id) || 0) + (incoming.get(a.id) || 0)) ||
    String(a.label || a.id).localeCompare(String(b.label || b.id));
  const stack = (items, x, startY, gap) => items.sort(sortByTraffic).map((node, index) => savedOrPlaced(node, x, startY + index * gap));
  const stackOrdered = (items, x, startY, gap) => items.map((node, index) => savedOrPlaced(node, x, startY + index * gap));

  if (mode === "product-process") {
    const products = nodes.filter((node) => topologyNodeSemanticType(node) === "product");
    const processes = nodes.filter((node) => topologyNodeSemanticType(node) === "process");
    const inputs = nodes.filter((node) => topologyNodeSemanticType(node) === "material");
    const outputs = nodes.filter((node) => topologyNodeSemanticType(node) === "part");
    const others = nodes.filter((node) => !products.includes(node) && !processes.includes(node) && !inputs.includes(node) && !outputs.includes(node));
    return [
      ...stack(inputs, 90, 92, inputs.length > 4 ? 126 : 150),
      ...stack(processes, 610, 96, processes.length > 4 ? 126 : 154),
      ...stack(products, 1280, 172, products.length > 3 ? 142 : 180),
      ...stack(outputs, 1320, 450, outputs.length > 3 ? 118 : 142),
      ...stack(others, 960, 610, 120),
    ];
  }

  if (mode === "device-craft") {
    const devices = nodes.filter((node) => topologyNodeSemanticType(node) === "device");
    const crafts = nodes.filter((node) => topologyNodeSemanticType(node) === "craft");
    const others = nodes.filter((node) => !devices.includes(node) && !crafts.includes(node));
    const ranked = (items) => new Map(items.map((node, index) => [node.id, index]));
    const averagePeerRank = (nodeId, direction, peerRanks) => {
      const peers = edges
        .filter((edge) => direction === "source" ? edge.source === nodeId : edge.target === nodeId)
        .map((edge) => direction === "source" ? edge.target : edge.source)
        .filter((id) => peerRanks.has(id));
      if (!peers.length) return Number.MAX_SAFE_INTEGER;
      return peers.reduce((sum, id) => sum + peerRanks.get(id), 0) / peers.length;
    };
    const baseCrafts = [...crafts].sort(sortByTraffic);
    const craftRanks = ranked(baseCrafts);
    const orderedDevices = [...devices].sort(
      (a, b) => averagePeerRank(a.id, "source", craftRanks) - averagePeerRank(b.id, "source", craftRanks) || sortByTraffic(a, b)
    );
    const deviceRanks = ranked(orderedDevices);
    const orderedCrafts = [...crafts].sort(
      (a, b) => averagePeerRank(a.id, "target", deviceRanks) - averagePeerRank(b.id, "target", deviceRanks) || sortByTraffic(a, b)
    );
    return [
      ...stackOrdered(orderedDevices, 260, 92, devices.length > 4 ? 132 : 162),
      ...stackOrdered(orderedCrafts, 1030, 92, crafts.length > 4 ? 132 : 162),
      ...stack(others, 650, 560, 120),
    ];
  }

  let left = nodes.filter((node) => (outgoing.get(node.id) || 0) >= (incoming.get(node.id) || 0));
  let right = nodes.filter((node) => !left.includes(node));
  if (!left.length || !right.length) {
    left = nodes.filter((_, index) => index % 2 === 0);
    right = nodes.filter((node) => !left.includes(node));
  }
  return [
    ...stack(left, 150, 86, left.length > 4 ? 138 : 166),
    ...stack(right, 1240, 76, right.length > 4 ? 138 : 166),
  ];
}
function renderNeoTopology(topology = activeNeoTopology(), mode = state.classTopologyMode) {
  const query = state.ontologySearch.classes;
  const visibleNodes = layoutNeoTopologyNodes(
    topology,
    (topology.nodes || []).filter((node) => topologyNodeMatches(node, query)),
    mode
  );
  const nodeLookup = new Map(visibleNodes.map((node) => [node.id, node]));
  const visibleEdges = withEdgeLanes(
    (topology.edges || []).filter((edge) => nodeLookup.has(edge.source) && nodeLookup.has(edge.target)),
    mode
  ).map((edge) => ({
    ...edge,
    diagonal: mode === "product-process" || mode === "device-craft",
  }));
  const meta = topologyModeMeta();

  return `
    <div class="production-topology-scroll">
      <div class="topology-controls" aria-label="拓扑缩放控制">
        <button class="topology-control-btn" data-topology-action="zoom-out" type="button">-</button>
        <span class="topology-scale-readout">${Math.round(state.topologyView.scale * 100)}%</span>
        <button class="topology-control-btn" data-topology-action="zoom-in" type="button">+</button>
        <button class="topology-control-btn wide" data-topology-action="reset" type="button">Reset</button>
      </div>
      <div class="production-topology-map" data-topology-map style="${topologyTransformStyle()}">
        <svg class="production-topology-lines" viewBox="0 0 1880 800" preserveAspectRatio="none" aria-hidden="true">
          <defs>
            <marker id="relationship-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth">
              <path d="M0,0 L8,4 L0,8 Z"></path>
            </marker>
          </defs>
          ${visibleEdges.map((edge) => {
            const geometry = edgeGeometry(edge, nodeLookup);
            return `
              <polyline class="production-edge" data-edge-source="${escapeHtml(edge.source)}" data-edge-target="${escapeHtml(edge.target)}" data-edge-lane-offset="${Number(edge.laneOffset) || 0}" data-edge-label-offset="${Number(edge.labelOffset) || 0}" data-edge-diagonal="${edge.diagonal ? "true" : "false"}" points="${escapeHtml(geometry.points)}" marker-end="url(#relationship-arrow)"></polyline>
              ${edge.label ? `<text class="production-edge-label" data-edge-label-source="${escapeHtml(edge.source)}" data-edge-label-target="${escapeHtml(edge.target)}" data-edge-label-lane-offset="${Number(edge.laneOffset) || 0}" data-edge-label-offset="${Number(edge.labelOffset) || 0}" data-edge-label-diagonal="${edge.diagonal ? "true" : "false"}" x="${geometry.label.x}" y="${geometry.label.y}">${escapeHtml(edge.label)}</text>` : ""}
            `;
          }).join("")}
        </svg>
        ${visibleNodes.map((node) => `
          <button
            class="production-class-node node-${escapeHtml(node.tone || entityIconType(node.entityType, node))} module-mapped"
            data-topology-node-id="${escapeHtml(node.id)}"
            data-draggable-topology-node="${escapeHtml(node.id)}"
            aria-pressed="${state.selectedEntity?.id === node.id ? "true" : "false"}"
            style="left:${Number(node.x) || 0}px;top:${Number(node.y) || 0}px"
            type="button"
          >
            <span class="node-icon">${escapeHtml(String(node.label || node.entityType || "?").slice(0, 1))}</span>
            <span class="node-copy">
              <strong>${escapeHtml(node.label || node.id)}</strong>
              <small>${escapeHtml(node.subtitle || node.entityType || meta.label)}</small>
            </span>
          </button>
        `).join("")}
        ${visibleNodes.length ? "" : `<div class="topology-empty-state">${escapeHtml(topology.description || meta.description)} 暂无可显示实例</div>`}
      </div>
    </div>
  `;
}

function renderActiveClassTopology() {
  return state.classTopologyMode === "production" ? renderProductionClassTopology() : renderNeoTopology();
}

function ensureSelectedTopologyInstance() {
  if (state.classTopologyMode === "production" || state.classViewMode !== "list") return;
  const topology = activeNeoTopology();
  const selectedExists = state.selectedEntity?.id && (topology.nodes || []).some((node) => node.id === state.selectedEntity.id);
  if (selectedExists) return;
  const preferredType = state.classTopologyMode === "product-process" ? "product" : "device";
  const next =
    (topology.nodes || []).find((node) => topologyNodeSemanticType(node) === preferredType) ||
    (topology.nodes || [])[0];
  state.selectedEntity = next ? topologyNodeEntity(next) : null;
  state.selectedEntityType = next?.entityType || "";
  state.selectedEntityId = next?.id || "";
}

function topologyNodeEntity(node) {
  const topology = activeNeoTopology();
  const relations = (topology.edges || [])
    .filter((edge) => edge.source === node.id || edge.target === node.id)
    .map((edge) => {
      const targetId = edge.source === node.id ? edge.target : edge.source;
      const target = (topology.nodes || []).find((item) => item.id === targetId);
      return {
        id: edge.id,
        type: edge.label,
        label: target ? `${edge.label} ${target.label}` : edge.label,
        source: edge.source,
        target: edge.target,
        sourceClass: edge.sourceClass || edge.source,
        targetClass: edge.targetClass || edge.target,
        targetType: target?.entityType || "",
        targetId,
      };
    });
  return {
    id: node.id,
    entityType: node.entityType,
    label: node.label,
    subtitle: node.subtitle,
    status: node.status || "neo4j",
    source: node.source || ["neo4j"],
    properties: node.properties || {},
    runtime: { topology: topology.title || topology.key, neo4jNodeId: node.neo4jNodeId || "" },
    relations,
    topologyNode: true,
  };
}

function openTopologyNode(nodeId) {
  const topology = activeNeoTopology();
  const node = (topology.nodes || []).find((item) => item.id === nodeId);
  if (!node) return;
  state.selectedEntity = topologyNodeEntity(node);
  state.selectedEntityType = node.entityType || "";
  state.selectedEntityId = node.id;
  renderPage();
}

function suggestedTopologyModes(entity) {
  if (!entity) return [];
  if (entity.entityType === "class") {
    return ["product-process", "device-craft"];
  }
  if (entity.entityType === "product") return ["product-process"];
  if (entity.entityType === "process_instance" || entity.entityType === "process") return ["product-process"];
  if (entity.entityType === "material" || entity.entityType === "part") return ["product-process"];
  if (entity.entityType === "device" || entity.entityType === "craft") return ["device-craft"];
  return [];
}
function renderClassDetailPanel() {
  const entity = state.selectedEntity;
  if (!entity) {
    return `
      <aside class="class-detail-panel">
        <div class="entity-card-head">
          <div>
            <p class="panel-eyebrow">Detail</p>
            <h3>未选择节点</h3>
            <p class="panel-muted">点击左侧拓扑节点查看模块名称、属性和相连关系。</p>
          </div>
        </div>
      </aside>
    `;
  }

  const relations = entity.relations || [];
  const suggestedModes = suggestedTopologyModes(entity);
  return `
    <aside class="class-detail-panel">
      <div class="entity-card-head">
        <div>
          <p class="panel-eyebrow">Detail</p>
          <h3>${escapeHtml(entity.label || entity.id)}</h3>
          <p class="panel-muted">${escapeHtml(entity.subtitle || "本体类")}</p>
        </div>
      </div>
      ${suggestedModes.length ? `
        <div class="panel-divider"></div>
        <div class="panel-subtitle">子拓扑</div>
        <div class="topology-jump-list">
          ${suggestedModes.map((mode) => {
            const meta = topologyModeMeta(mode);
            return `<button class="topology-jump-btn" data-topology-mode="${escapeHtml(mode)}" type="button">${escapeHtml(meta.label)}</button>`;
          }).join("")}
        </div>
      ` : ""}
      <div class="panel-divider"></div>
      <div class="panel-subtitle">属性</div>
      <div class="entity-fields">
        ${Object.entries(entity.properties || {})
          .slice(0, 8)
          .map(([label, value]) => `<span>${escapeHtml(label)}</span><span>${escapeHtml(value)}</span>`)
          .join("") || "<span>提示</span><span>无属性数据</span>"}
      </div>
      <div class="panel-divider"></div>
      <div class="panel-subtitle">关系 (${relations.length})</div>
      <div class="class-detail-relation-list">
        ${relations.length
          ? relations.map((relation) => `
            <article class="class-detail-relation">
              <strong>${escapeHtml(relation.type || relation.label || "REL")}</strong>
              <span>${escapeHtml(relation.sourceClass || relation.source)} -> ${escapeHtml(relation.targetClass || relation.target)}</span>
            </article>
          `).join("")
          : "<p class='panel-muted'>暂无相连关系线段</p>"}
      </div>
    </aside>
  `;
}
function renderClassesPage() {
  ensureSelectedTopologyInstance();
  const activeModeMeta = topologyModeMeta();
  const activeNeo = activeNeoTopology();
  const visibleNodeCount = state.classTopologyMode === "production"
    ? visibleTopologyNodes().filter((node) => classTopologyMatches(node, state.ontologySearch.classes)).length
    : (activeNeo.nodes || []).filter((node) => topologyNodeMatches(node, state.ontologySearch.classes)).length;
  const visibleNodeIds = new Set(visibleTopologyNodes().map((node) => node.id));
  const visibleEdgeCount = state.classTopologyMode === "production" ? activeTopologyEdges().filter(
    (edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)
      && (!state.ontologySearch.classes || classTopologyMatches(edge, state.ontologySearch.classes)
        || classTopologyMatches(CLASS_TOPOLOGY_NODES.find((node) => node.id === edge.source) || {}, state.ontologySearch.classes)
        || classTopologyMatches(CLASS_TOPOLOGY_NODES.find((node) => node.id === edge.target) || {}, state.ontologySearch.classes))
  ).length : (activeNeo.edges || []).length;
  const rows = filteredClassRows();
  const deletedRows = deletedClassRows();
  const content = state.classViewMode === "list" ? renderActiveClassList() : `
    <section class="class-topology-layout">
      <div class="topology-panel">
        ${renderActiveClassTopology()}
      </div>
      ${renderClassDetailPanel()}
    </section>
  `;

  return `
    <section class="page-grid">
      <article class="panel-card full-width topology-workspace">
        <div class="panel-header panel-header-spread">
          <div>
            <h2>Classes</h2>
            <p class="panel-muted">${escapeHtml(activeModeMeta.description)}</p>
          </div>
          <div class="metric-group">
            ${renderMetricPills([`${visibleNodeCount} 个节点`, `${visibleEdgeCount} 条关系`, statusBadgeText()])}
          </div>
        </div>
        <div class="class-toolbar">
          ${renderOntologySearch("classes", "搜索类名称、描述或关系...")}
          <div class="class-toolbar-actions">
            <label class="topology-mode-select-wrap">
              <span>拓扑</span>
              <select class="topology-mode-select" data-topology-select aria-label="Topology mode">
                ${TOPOLOGY_MODES.map((mode) => `<option value="${escapeHtml(mode.key)}" ${state.classTopologyMode === mode.key ? "selected" : ""}>${escapeHtml(mode.label)}</option>`).join("")}
              </select>
            </label>
            <label class="topology-mode-select-wrap view-mode-select-wrap">
              <span>视图</span>
              <select class="topology-mode-select view-mode-select" data-class-view-select aria-label="Classes view mode">
                <option value="list" ${state.classViewMode === "list" ? "selected" : ""}>列表</option>
                <option value="topology" ${state.classViewMode === "topology" ? "selected" : ""}>拓扑</option>
              </select>
            </label>
            <button class="toolbar-btn" data-class-action="toggle-recycle" type="button">回收站 ${deletedRows.length ? `(${deletedRows.length})` : ""}</button>
            <button class="toolbar-btn primary" data-class-action="new" type="button">+ 新建类</button>
          </div>
        </div>

        ${renderClassRecycleBin(deletedRows)}

        ${content}

        ${state.classViewMode === "list" && state.classTopologyMode === "production" ? `
          <div class="panel-divider"></div>
          <div class="panel-header">
            <div>
              <h3>详情视图</h3>
              <p class="panel-muted">选择类条目查看详细属性。</p>
            </div>
          </div>
          ${entityPanel(state.selectedEntity)}
        ` : ""}
      </article>
    </section>
  `;
}
function entityDisplayLabel(item, entityType) {
  const props = item?.properties || item || {};
  if (entityType === "device") {
    const label = firstField(props, ["设备名称", "设备", "AGV名称", "小车名称", "工站名称", "工作站名称", "工作站名", "device_name", "deviceName", "workstation_name", "workstationName", "station_name", "stationName", "agv_name", "agvName", "name"], "");
    if (label) return label;
    if (item?.label && !/^dev\d+$/i.test(String(item.label).trim())) return item.label;
    const source = Array.isArray(item?.source) ? item.source.join(" ") : String(item?.source || "");
    if (normalizeText(source).includes("agv")) return "AGV";
  }
  if (entityType === "material") {
    const label = firstField(props, ["物料名称", "产品名称", "物料", "material_name", "materialName", "product_name", "productName", "name"], "");
    if (label) return label;
  }
  if (entityType === "order") {
    const label = firstField(props, ["订单名称", "产品名称", "客户名称", "order_name", "orderName", "product_name", "customer_name", "name"], "");
    if (label) return label;
  }
  if (entityType === "work_order") {
    const label = firstField(props, ["工单名称", "任务名称", "阶段", "work_order_name", "workOrderName", "title", "name"], "");
    if (label) return label;
  }
  return item?.label || item?.name || item?.id || "Entity";
}

function entityDisplaySubtitle(item, entityType) {
  const props = item?.properties || item || {};
  if (entityType === "device") {
    return firstField(props, ["设备编号", "AGV编号", "工站编号", "工作站编号", "device_code", "deviceCode", "device_id", "deviceId", "workstation_code", "workstationCode", "station_code", "stationCode", "agv_code", "agvCode", "agv_id", "agvId", "code"], item?.subtitle || item?.summary || item?.id || "Device");
  }
  if (entityType === "material") {
    return firstField(props, ["库位", "库位编号", "库位号", "仓位", "location", "slot"], item?.subtitle || item?.summary || item?.id || "Material");
  }
  if (entityType === "order") {
    return firstField(props, ["订单编号", "产品名称", "客户名称", "order_id", "product_name", "customer_name"], item?.subtitle || item?.summary || item?.id || "Order");
  }
  if (entityType === "work_order") {
    return firstField(props, ["工单编号", "工序名称", "所属订", "work_order_id", "process_name", "order_id"], item?.subtitle || item?.summary || item?.id || "Work Order");
  }
  return item?.subtitle || item?.summary || item?.id || "Entity";
}

function entityDedupeKey(entityType, item) {
  const label = normalizeText(entityDisplayLabel(item, entityType));
  const subtitle = normalizeText(entityDisplaySubtitle(item, entityType));
  const subtype = entityIconType(entityType, item);
  return `${entityType}|${subtype}|${label}|${subtitle}`;
}

function uniqueEntityItems(entityType, items) {
  const seen = new Set();
  const unique = [];
  items.forEach((item) => {
    const key = entityDedupeKey(entityType, item);
    if (seen.has(key)) return;
    seen.add(key);
    unique.push(item);
  });
  return unique;
}

function productionReportTemplate() {
  return REPORT_TEMPLATES.find((item) => item.id === "RPT-PRODUCTION-ANALYSIS")
    || REPORT_TEMPLATES.find((item) => normalizeText(item.title).includes("产品生产分析"))
    || null;
}

function itemProperties(item) {
  return item?.properties || item || {};
}

function prefixedIdValue(value) {
  return String(value || "").replace(/^[a-z_]+:/i, "");
}

function recordField(record, names, fallback = "") {
  const props = itemProperties(record);
  return firstField(props, names, fallback);
}

function orderIdentity(record, fallback = "") {
  return prefixedIdValue(recordField(record, ["订单编号", "订单ID", "order_id", "orderId", "id", "code"], record?.id || fallback));
}

function treeWorkOrderIdentity(record, fallback = "") {
  return prefixedIdValue(recordField(record, ["工单编号", "工单ID", "任务编号", "work_order_id", "workOrderId", "task_id", "taskId", "id", "code"], record?.id || fallback));
}

function normalizeOrderStatus(value) {
  const text = normalizeText(displayValue(value, ""));
  if (!text) return "已创建";
  if (text.includes("失败") || text.includes("异常") || text.includes("取消") || text.includes("fail") || text.includes("error") || text.includes("cancel")) return "失败";
  if (text.includes("完成") || text.includes("成功") || text.includes("finish") || text.includes("complete") || text.includes("done") || text.includes("succeed")) return "已完成";
  if (text.includes("执行") || text.includes("运行") || text.includes("生产") || text.includes("progress") || text.includes("running") || text.includes("processing")) return "执行中";
  if (text.includes("接收") || text.includes("received") || text.includes("accepted") || text.includes("ready")) return "已接收";
  if (text.includes("下发") || text.includes("分配") || text.includes("dispatch") || text.includes("issued") || text.includes("sent") || text.includes("assigned")) return "已下发";
  if (text.includes("创建") || text.includes("下单") || text.includes("新建") || text.includes("created") || text.includes("placed") || text.includes("pending") || text.includes("等待") || text.includes("wait")) return "已创建";
  return displayValue(value);
}

function normalizeWorkOrderStatus(value) {
  const text = normalizeText(displayValue(value, ""));
  if (!text) return "已创建";
  if (text.includes("失败") || text.includes("异常") || text.includes("取消") || text.includes("fail") || text.includes("error") || text.includes("cancel")) return "失败";
  if (text.includes("完成") || text.includes("成功") || text.includes("finish") || text.includes("complete") || text.includes("done") || text.includes("succeed")) return "已完成";
  if (text.includes("执行") || text.includes("运行") || text.includes("生产") || text.includes("progress") || text.includes("running") || text.includes("processing")) return "执行中";
  if (text.includes("接收") || text.includes("received") || text.includes("accepted") || text.includes("ready")) return "已接收";
  if (text.includes("下发") || text.includes("分配") || text.includes("dispatch") || text.includes("issued") || text.includes("sent") || text.includes("assigned")) return "已下发";
  if (text.includes("创建") || text.includes("等待") || text.includes("待") || text.includes("pending") || text.includes("queue") || text.includes("wait") || text.includes("created")) return "已创建";
  return displayValue(value);
}

function recordStartTime(record) {
  return recordField(record, ["开始时间", "下单时间", "计划开始时间", "start_time", "startTime", "order_start_time", "planned_start_time", "run_start_time"], "");
}

function recordEndTime(record) {
  return recordField(record, ["结束时间", "完成时间", "计划结束时间", "end_time", "endTime", "order_end_time", "planned_end_time", "run_end_time"], "");
}

function workOrderStation(record) {
  return recordField(record, [
    "分配工站",
    "分配工位",
    "工站",
    "工位",
    "设备名称",
    "assigned_workstation_name",
    "assigned_workstation_id",
    "assigned_station_name",
    "assigned_station_id",
    "assigned_device_name",
    "assigned_device_id",
    "workstation_name",
    "workstation_id",
    "station_name",
    "station_id",
  ], "-");
}

function catalogWorkOrderMatchesOrder(workOrder, orderKeys) {
  const props = itemProperties(workOrder);
  const parentId = prefixedIdValue(firstField(props, [
    "所属订单",
    "所属订单号",
    "所属订单编号",
    "订单编号",
    "订单ID",
    "source_order_id",
    "sourceOrderId",
    "order_id",
    "orderId",
    "parent_order_id",
    "parentOrderId",
  ], ""));
  return parentId && orderKeys.has(parentId);
}

function isCompletedOrCancelledStatus(status) {
  const normalized = normalizeText(displayValue(status, ""));
  return normalized.includes("已完成")
    || normalized.includes("完成")
    || normalized.includes("complete")
    || normalized.includes("done")
    || normalized.includes("失败")
    || normalized.includes("failed")
    || normalized.includes("failure")
    || normalized.includes("fail")
    || normalized.includes("已取消")
    || normalized.includes("取消")
    || normalized.includes("cancel");
}

function isActiveTaskStatus(status) {
  return !isCompletedOrCancelledStatus(status);
}

function isActiveOntologyOrder(order) {
  return !isCompletedOrCancelledStatus(normalizeOrderStatus(recordField(order, ["订单状态", "状态", "status", "state"], order.status)));
}

function isActiveOntologyWorkOrder(workOrder) {
  return !isCompletedOrCancelledStatus(normalizeWorkOrderStatus(recordField(workOrder, ["工单状态", "任务状态", "状态", "status", "state", "run_status"], workOrder.status)));
}

function normalizeOrderTreeItem(order, index, source = "data") {
  const orderId = orderIdentity(order, `order-${index + 1}`);
  const product = recordField(order, ["产品名称", "产品ID", "product_name", "product_id", "productName", "productId"], "");
  const customer = recordField(order, ["客户名称", "客户", "customer_name", "customerName"], "");
  const workOrders = Array.isArray(order.work_orders) ? order.work_orders : [];
  return {
    ...order,
    __treeId: orderId,
    __source: source,
    __label: recordField(order, ["订单名称", "order_name", "orderName", "name"], order.label || orderId),
    __subtitle: [product, customer].filter(Boolean).join(" · ") || orderId,
    __status: normalizeOrderStatus(recordField(order, ["订单状态", "状态", "status", "state"], order.status)),
    __startTime: recordStartTime(order),
    __endTime: recordEndTime(order),
    __workOrders: workOrders.map((workOrder, workIndex) => normalizeWorkOrderTreeItem(workOrder, workIndex, source)),
  };
}

function normalizeWorkOrderTreeItem(workOrder, index, source = "data") {
  const workOrderId = treeWorkOrderIdentity(workOrder, `work-order-${index + 1}`);
  return {
    ...workOrder,
    __treeId: workOrderId,
    __source: source,
    __label: recordField(workOrder, ["工单名称", "任务名称", "work_order_name", "workOrderName", "title", "name"], workOrder.label || workOrderId),
    __subtitle: recordField(workOrder, ["工序名称", "工序", "process_name", "processName", "process_id", "processId"], "-"),
    __status: normalizeWorkOrderStatus(recordField(workOrder, ["工单状态", "任务状态", "状态", "status", "state", "run_status"], workOrder.status)),
    __startTime: recordStartTime(workOrder),
    __endTime: recordEndTime(workOrder),
    __station: workOrderStation(workOrder),
  };
}

function buildDataOrderTreeItems() {
  const dataOrders = Array.isArray(state.data.orderTree) ? state.data.orderTree : [];
  return dataOrders.map((order, index) => normalizeOrderTreeItem(order, index, "data"));
}

function buildOntologyOrderTreeItems() {
  const orders = uniqueEntityItems("order", entityItems("order"));
  const workOrders = uniqueEntityItems("work_order", entityItems("work_order"));
  return orders.map((order, index) => {
    const orderId = orderIdentity(order, `order-${index + 1}`);
    const orderKeys = new Set([
      orderId,
      prefixedIdValue(order.id),
      recordField(order, ["订单名称", "order_name", "orderName", "name"], ""),
      recordField(order, ["订单ID", "order_id", "orderId"], ""),
    ].filter(Boolean));
    const relatedWorkOrders = workOrders.filter((workOrder) => catalogWorkOrderMatchesOrder(workOrder, orderKeys));
    const hasActiveWorkOrder = relatedWorkOrders.some(isActiveOntologyWorkOrder);
    if (!isActiveOntologyOrder(order) && !hasActiveWorkOrder) return null;
    return normalizeOrderTreeItem(
      {
        ...order,
        work_orders: relatedWorkOrders,
      },
      index,
      "ontology"
    );
  }).filter(Boolean);
}

function buildOrderTreeItems(source = "ontology") {
  return source === "data" ? buildDataOrderTreeItems() : buildOntologyOrderTreeItems();
}

function isArchivedOrderTreeItem(order) {
  return isCompletedOrCancelledStatus(order.__status);
}

function filterOrderTreeItems(items, query) {
  const q = normalizeText(query || "");
  if (!q) return items;
  return items
    .map((order) => {
      const orderMatches = normalizeText(rowText(order)).includes(q) || normalizeText(`${order.__label} ${order.__subtitle} ${order.__status}`).includes(q);
      const workOrders = (order.__workOrders || []).filter((workOrder) => (
        normalizeText(rowText(workOrder)).includes(q)
        || normalizeText(`${workOrder.__label} ${workOrder.__subtitle} ${workOrder.__status} ${workOrder.__station}`).includes(q)
      ));
      return orderMatches || workOrders.length ? { ...order, __workOrders: orderMatches ? order.__workOrders : workOrders } : null;
    })
    .filter(Boolean);
}

function renderOrderTree(orders, emptyMessage) {
  if (!orders.length) {
    return `<article class="entity-card"><h3>暂无订单数据</h3><p class="panel-muted">${escapeHtml(emptyMessage)}</p></article>`;
  }

  return `
    <div class="order-tree">
      ${orders.map((order) => {
        const expanded = state.orderTreeExpanded[order.__treeId] !== false;
        return `
          <article class="order-tree-folder">
            <div class="order-tree-head">
              <button class="isa-tree-toggle" data-order-tree-toggle="${escapeHtml(order.__treeId)}" type="button" aria-label="展开或收起订单">${expanded ? "−" : "+"}</button>
              ${typeIconHtml("order", order.__label)}
              <div class="order-tree-main">
                <h3>${escapeHtml(order.__label)}</h3>
                <p>${escapeHtml(order.__subtitle || order.__treeId)}</p>
              </div>
              ${dataStatusChip(order.__status)}
            </div>
            <div class="order-tree-fields">
              <span>订单编号</span><strong>${escapeHtml(order.__treeId)}</strong>
              <span>开始时间</span><strong>${escapeHtml(displayValue(order.__startTime))}</strong>
              <span>结束时间</span><strong>${escapeHtml(displayValue(order.__endTime))}</strong>
              <span>拆分工单</span><strong>${escapeHtml(String((order.__workOrders || []).length))}</strong>
            </div>
            <div class="order-tree-children ${expanded ? "" : "is-collapsed"}">
              ${(order.__workOrders || []).length ? order.__workOrders.map((workOrder) => `
                <article class="order-tree-child ${statusClass(workOrder.__status)}">
                  <div class="order-tree-child-head">
                    ${typeIconHtml("work_order", workOrder.__label)}
                    <div>
                      <h4>${escapeHtml(workOrder.__label)}</h4>
                      <p>${escapeHtml(workOrder.__subtitle || "-")}</p>
                    </div>
                    ${dataStatusChip(workOrder.__status)}
                  </div>
                  <div class="order-tree-fields compact">
                    <span>工单编号</span><strong>${escapeHtml(workOrder.__treeId)}</strong>
                    <span>分配工站</span><strong>${escapeHtml(workOrder.__station)}</strong>
                    <span>开始时间</span><strong>${escapeHtml(displayValue(workOrder.__startTime))}</strong>
                    <span>结束时间</span><strong>${escapeHtml(displayValue(workOrder.__endTime))}</strong>
                  </div>
                </article>
              `).join("") : "<p class='panel-muted'>该订单暂无拆分工单。</p>"}
            </div>
          </article>
        `;
      }).join("")}
    </div>
  `;
}

function renderOrderTreePage() {
  const allOrders = buildOrderTreeItems("ontology");
  const orders = filterOrderTreeItems(allOrders, state.ontologySearch.order);
  const workOrderCount = allOrders.reduce((total, order) => total + (order.__workOrders || []).length, 0);

  return `
    <section class="page-grid">
      <article class="panel-card full-width">
        <div class="panel-header panel-header-spread">
          <div>
            <h2>Orders</h2>
            <p class="panel-muted">本体页仅展示当前正在执行或等待执行的订单与工单；已结束订单归档在 DATA / 订单工单历史。</p>
          </div>
          <div class="metric-group">${renderMetricPills([`${orders.length}/${allOrders.length} 个活动订单`, `${workOrderCount} 个活动工单`, statusBadgeText()])}</div>
        </div>
        ${renderOntologySearch("order", "搜索订单、工单、工序或工站...")}
        ${renderOrderTree(orders, "当前本体中未读取到正在执行或等待执行的订单/工单实例。")}
      </article>
    </section>
  `;
}

function deviceRuntimeRecord(item) {
  return {
    ...(item?.properties || {}),
    ...(item?.runtime || {}),
    id: item?.id,
    label: item?.label,
    name: item?.label,
    subtitle: item?.subtitle,
    status: item?.status,
    __table: Array.isArray(item?.source) ? item.source.join(" / ") : item?.source,
  };
}

function deviceTaskTitle(task) {
  if (!task) return "暂无当前任务";
  return task.title || task.workOrder || task.taskId || task.status || "当前任务";
}

function productionDeviceAlias(record) {
  const text = normalizeDeviceStatusKey(`${deviceTitle(record)} ${deviceIdentity(record)} ${rowText(record)}`);
  if (!text) return "";
  if (text.includes("agv") || text.includes("小车")) return "";
  if (text.includes("立体") || text.includes("仓库") || text.includes("storage")) return "warehouse";
  if (text.includes("协作") || text.includes("cobot") || text.includes("processing")) return "cobot-workstation";
  if (text.includes("scara")) {
    const number = text.match(/\d+/)?.[0] || "";
    return `scara-workstation-${number || "unknown"}`;
  }
  const compact = text
    .replace(/自动化/g, "")
    .replace(/加工/g, "")
    .replace(/机器人/g, "")
    .replace(/设备/g, "");
  return compact;
}

function deviceTransportTaskForRecord(record, workOrders) {
  if (deviceConnectionState(record) === "offline") return null;
  const ownTask = transportTaskInfo(record, { allowDeviceRecord: false });
  if (ownTask && isActiveTaskStatus(ownTask.status)) return ownTask;
  const deviceId = normalizeText(deviceIdentity(record));
  const title = normalizeText(deviceTitle(record));
  return workOrders.map(transportTaskInfo).filter(Boolean).find((task) => {
    if (!isActiveTaskStatus(task.status)) return false;
    const text = normalizeText(`${task.agv} ${task.from} ${task.to} ${task.workOrder} ${task.title}`);
    return (deviceId && text.includes(deviceId)) || (title && text.includes(title));
  }) || null;
}

function buildDeviceTaskTreeItems(deviceItems) {
  const normalizedDeviceItems = deviceItems;
  const workOrders = uniqueEntityItems("work_order", entityItems("work_order"))
    .filter(isActiveOntologyWorkOrder)
    .map((item) => ({ ...item.properties, ...item.runtime, ...item, __table: Array.isArray(item.source) ? item.source.join(" / ") : item.source }));
  const transportRows = [
    ...workOrders,
    ...activeAgvTaskRows().map((row) => ({ ...row, __table: "order.work_orders" })),
  ];

  return normalizedDeviceItems.map((item, index) => {
    const record = deviceRuntimeRecord(item);
    const id = deviceIdentity(record) || prefixedIdValue(item.id) || `device-${index + 1}`;
    const subtype = deviceSubtype(record);
    const isAgv = subtype === "agv" || isAgvRow(record);
    const isStation = subtype === "workstation" || isWorkstationRow(record);
    const matchedOrder = isStation ? findWorkOrderForDevice(record, workOrders) : null;
    const connection = deviceConnectionState(record);
    const transportTask = isAgv && connection !== "offline" ? deviceTransportTaskForRecord(record, transportRows) : null;
    const currentId = activeDeviceCurrentWorkOrderId(record) || agvTaskId(record);
    const runtime = deviceRuntimeStatus(record);
    const status = matchedOrder
      ? firstField(matchedOrder, ["工单状", "工单状态", "任务状态", "status", "state"], "执行中")
      : transportTask
        ? transportTask.status
        : connection === "offline" ? "offline" : runtime || "idle";

    return {
      id,
      label: deviceTitle(record) || item.label || id,
      subtitle: rowType(record) || item.subtitle || subtype,
      status,
      record,
      taskType: transportTask ? "AGV运输任务" : matchedOrder || currentId ? "执行工单" : "当前任务",
      task: matchedOrder
        ? {
          title: workOrderTitle(matchedOrder),
          id: workOrderIdentity(matchedOrder) || currentId || "-",
          station: assignedDeviceText(matchedOrder) || deviceTitle(record),
          start: recordStartTime(matchedOrder),
          end: recordEndTime(matchedOrder),
          status,
        }
        : transportTask
          ? {
            title: transportTask.title,
            id: transportTask.workOrder,
            station: transportTask.agv,
            route: `${transportTask.from} -> ${transportTask.to}`,
            status,
          }
          : {
            title: currentId || "暂无当前任务",
            id: currentId || "-",
            station: deviceTitle(record),
            status,
          },
    };
  });
}

function renderDeviceTaskTree(deviceItems) {
  const tasks = buildDeviceTaskTreeItems(deviceItems);
  if (!tasks.length) {
    return `<article class="entity-card"><h3>暂无设备实例</h3><p class="panel-muted">未读取到本体设备实例。</p></article>`;
  }

  return `
    <div class="device-task-tree">
      ${tasks.map((device) => {
        const expanded = state.deviceTreeExpanded[device.id] !== false;
        const task = device.task;
        return `
          <article class="device-task-folder">
            <div class="device-task-head">
              <button class="isa-tree-toggle" data-device-tree-toggle="${escapeHtml(device.id)}" type="button" aria-label="展开或收起设备任务">${expanded ? "−" : "+"}</button>
              ${typeIconHtml(device.taskType === "AGV运输任务" ? "agv" : "workstation", device.label)}
              <div class="device-task-main">
                <h3>${escapeHtml(device.label)}</h3>
                <p>${escapeHtml(device.subtitle || device.id)}</p>
              </div>
              <div class="status-chip-set">${renderDeviceStateChips(device.record || {})}</div>
            </div>
            <div class="device-task-children ${expanded ? "" : "is-collapsed"}">
              <article class="device-task-child">
                <div class="device-task-child-head">
                  ${typeIconHtml(device.taskType === "AGV运输任务" ? "agv" : "work_order", device.taskType)}
                  <div>
                    <h4>${escapeHtml(deviceTaskTitle(task))}</h4>
                    <p>${escapeHtml(device.taskType)}</p>
                  </div>
                  <div class="task-progress ${statusClass(task.status)}"><span>${escapeHtml(task.status || "-")}</span></div>
                </div>
                <div class="order-tree-fields compact">
                  <span>任务编号</span><strong>${escapeHtml(task.id || "-")}</strong>
                  <span>${device.taskType === "AGV运输任务" ? "AGV小车" : "执行工站"}</span><strong>${escapeHtml(task.station || "-")}</strong>
                  <span>${device.taskType === "AGV运输任务" ? "运输路径" : "开始时间"}</span><strong>${escapeHtml(device.taskType === "AGV运输任务" ? task.route || "-" : displayValue(task.start))}</strong>
                  <span>结束时间</span><strong>${escapeHtml(displayValue(task.end))}</strong>
                </div>
              </article>
            </div>
          </article>
        `;
      }).join("")}
    </div>
  `;
}

function mergeDeviceEntityItems(items) {
  const merged = new Map();
  const technicalDevices = [];
  const namedProductionDevices = [];
  const codedProductionDevices = [];
  const uncodedProductionDevices = [];
  items.forEach((item, index) => {
    const record = deviceRuntimeRecord(item);
    const key = canonicalDeviceStatusKey(record) || normalizeDeviceStatusKey(prefixedIdValue(item.id));
    const titleKey = normalizeDeviceStatusKey(deviceTitle(record));
    const aliasKey = productionDeviceAlias(record);
    const subtype = deviceSubtype(record);
    const isNamedProductionDevice = !isTechnicalDeviceTitle(record)
      && (subtype === "warehouse" || subtype === "workstation" || isWorkstationRow(record));
    if (isTechnicalDeviceTitle(record) && /^dev\d+$/i.test(key) && !isAgvRow(record)) {
      technicalDevices.push({ key, index });
    } else if (isNamedProductionDevice) {
      namedProductionDevices.push({ key, index });
    }
    if (isNamedProductionDevice && !isAgvRow(record)) {
      if (/^dev\d+$/i.test(key)) {
        codedProductionDevices.push({ key, titleKey, aliasKey, index });
      } else {
        uncodedProductionDevices.push({ key, titleKey, aliasKey, index });
      }
    }
  });
  const autoAliases = new Map();
  technicalDevices
    .sort((left, right) => {
      const leftNumber = Number(left.key.match(/\d+/)?.[0] || left.index);
      const rightNumber = Number(right.key.match(/\d+/)?.[0] || right.index);
      return leftNumber - rightNumber;
    })
    .slice(0, namedProductionDevices.length)
    .forEach((device, index) => {
      const named = namedProductionDevices[index];
      if (named?.key) autoAliases.set(named.key, device.key);
    });
  const orderedCodedProductionDevices = codedProductionDevices.sort((left, right) => {
    const leftNumber = Number(left.key.match(/\d+/)?.[0] || left.index);
    const rightNumber = Number(right.key.match(/\d+/)?.[0] || right.index);
    return leftNumber - rightNumber;
  });
  uncodedProductionDevices
    .sort((left, right) => left.index - right.index)
    .forEach((device, index) => {
      const matched = orderedCodedProductionDevices.find((candidate) => (
        (device.aliasKey && candidate.aliasKey && device.aliasKey === candidate.aliasKey)
        || (
          device.titleKey
          && candidate.titleKey
          && (device.titleKey.includes(candidate.titleKey) || candidate.titleKey.includes(device.titleKey))
        )
      ));
      if (matched?.key) autoAliases.set(device.key, matched.key);
    });

  items.forEach((item, index) => {
    const record = deviceRuntimeRecord(item);
    const rawKey = canonicalDeviceStatusKey(record) || normalizeDeviceStatusKey(prefixedIdValue(item.id)) || `device-item:${index}`;
    const key = autoAliases.get(rawKey) || rawKey;
    const existing = merged.get(key);
    if (!existing) {
      merged.set(key, item);
      return;
    }

    const existingRecord = deviceRuntimeRecord(existing);
    const nextHasDisplayName = !isTechnicalDeviceTitle(record);
    const existingHasDisplayName = !isTechnicalDeviceTitle(existingRecord);
    const preferred = nextHasDisplayName && !existingHasDisplayName ? item : existing;
    const fallback = preferred === item ? existing : item;
    const source = [fallback.source, preferred.source]
      .flat()
      .filter((value) => value !== undefined && value !== null && value !== "");

    const properties = { ...(fallback.properties || {}), ...(preferred.properties || {}) };
    const runtime = { ...(fallback.runtime || {}), ...(preferred.runtime || {}), device_id: canonicalDeviceStatusId(key) };
    const status = deviceDisplayStatus(
      { ...properties, ...runtime, status: preferred.status || fallback.status },
      "offline"
    );

    merged.set(key, {
      ...fallback,
      ...preferred,
      id: `device:${canonicalDeviceStatusId(key)}`,
      label: nextHasDisplayName && !existingHasDisplayName ? item.label : existing.label,
      subtitle: preferred.subtitle || fallback.subtitle,
      status,
      source: Array.from(new Set(source)),
      properties: { ...properties, status },
      runtime: { ...runtime, status },
    });
  });
  return Array.from(merged.values());
}

function renderEntityListPage(entityType) {
  const baseItems = uniqueEntityItems(entityType, entityItems(entityType));
  const allItems = baseItems;
  const items = filterItems(allItems, state.ontologySearch[entityType]);
  const title = ENTITY_META[entityType].title;
  const emptyMessage = entityType === "order" || entityType === "work_order" ? "暂无订单或工单数据" : "暂无实时数据";
  const deviceTaskTree = entityType === "device" ? `
    <div class="panel-header compact-header">
      <div>
        <h3>设备当前任务</h3>
        <p class="panel-muted">仅展示正在执行或等待执行的工站工单和 AGV 运输任务，已完成或已取消任务转入设备运行历史。</p>
      </div>
    </div>
    ${renderDeviceTaskTree(items)}
    <div class="panel-divider"></div>
  ` : "";

  return `
    <section class="page-grid">
      <article class="panel-card full-width">
        <div class="panel-header panel-header-spread">
          <div>
            <h2>${escapeHtml(title)}</h2>
            <p class="panel-muted">${escapeHtml(ENTITY_LIST_COPY[entityType] || "查看实例列表，选择任意行后可在下方查看完整属性。")}</p>
          </div>
          <div class="metric-group">${renderMetricPills([`${items.length}/${allItems.length} 项`, state.ontology ? state.ontology.status : "实时"])}</div>
        </div>
        ${renderOntologySearch(entityType, `搜索 ${title}...`)}
        ${deviceTaskTree}
        <div class="entity-list-wrap">
          <table class="entity-list-table">
            <thead>
              <tr>
                <th>实例</th>
                <th>类型</th>
                <th>状态</th>
                <th>来源</th>
                <th>ID</th>
              </tr>
            </thead>
            <tbody>
              ${items.length
                ? items
                    .map((item, index) => {
                      const id = item.id || `${entityType}:${index}`;
                      const displayId = entityType === "material" ? globalSearchCode(item, entityType) : id;
                      const iconType = entityIconType(entityType, item);
                      const itemStatus = entityType === "device"
                        ? deviceDisplayStatus({ ...(item.properties || {}), ...(item.runtime || {}), status: item.status })
                        : item.status || "实时";
                      return `
                        <tr>
                          <td>
                            <button class="entity-list-name entity-clickable" data-entity-type="${escapeHtml(entityType)}" data-entity-id="${escapeHtml(id)}" type="button">
                              ${typeIconHtml(iconType, entityDisplayLabel(item, entityType))}
                              <span>
                                <strong>${escapeHtml(entityDisplayLabel(item, entityType))}</strong>
                                <small>${escapeHtml(entityDisplaySubtitle(item, entityType))}</small>
                              </span>
                            </button>
                          </td>
                          <td><span class="entity-type-pill">${escapeHtml(TYPE_ICON_META[iconType]?.label || entityType)}</span></td>
                          <td><span class="status-chip ${statusClass(itemStatus)}">${escapeHtml(itemStatus)}</span></td>
                          <td>${escapeHtml(Array.isArray(item.source) ? item.source.join(" · ") : String(item.source || "-"))}</td>
                          <td>${escapeHtml(displayId || id)}</td>
                        </tr>
                      `;
                    })
                    .join("")
                : `
                  <tr>
                    <td colspan="5" class="class-table-empty">${escapeHtml(emptyMessage)}</td>
                  </tr>
                `}
            </tbody>
          </table>
        </div>
        <div class="panel-divider"></div>
        <div class="panel-header">
          <div>
            <h3>属性视图</h3>
            <p class="panel-muted">选择任意列表行后查看详细属性。</p>
          </div>
        </div>
        ${entityPanel(state.selectedEntity)}
      </article>
    </section>
  `;
}

function dataStatusChip(status) {
  return `<span class="status-chip ${statusClass(status)}">${escapeHtml(statusDisplayText(status) || "-")}</span>`;
}

function agvTaskRows() {
  if (Array.isArray(state.agv.tasks) && state.agv.tasks.length) return state.agv.tasks;
  return Array.isArray(state.data.agvTasks) ? state.data.agvTasks : [];
}

function normalizeAgvTask(row) {
  return {
    id: firstField(row, ["运输编号", "transport_id", "transportId", "task_id", "taskId", "id"], "-"),
    type: firstField(row, ["任务类型", "task_type", "taskType", "运输类型"], "运输任务"),
    status: firstField(row, ["任务状态", "status", "state", "运输状态"], "等待中"),
    agv: firstField(row, ["AGV编号", "agv_id", "agvId", "小车编号"], "AGV"),
    from: firstField(row, ["起始工站/仓库", "起点设备", "from_device", "fromDevice", "source_device", "sourceDevice", "from_name", "fromName"], "-"),
    to: firstField(row, ["目标工站/仓库", "目标设备", "to_device", "toDevice", "target_device", "targetDevice", "to_name", "toName"], "-"),
    createdAt: firstField(row, ["创建时间", "created_at", "createdAt"], ""),
    startedAt: firstField(row, ["实际开始时间", "started_at", "startedAt", "start_time", "startTime"], ""),
    endedAt: firstField(row, ["结束时间", "ended_at", "endedAt", "end_time", "endTime"], ""),
    orderId: firstField(row, ["订单编号", "order_id", "orderId"], ""),
    workOrderId: firstField(row, ["工单编号", "work_order_id", "workOrderId"], ""),
    raw: row,
  };
}

function agvTasks() {
  return agvTaskRows().map(normalizeAgvTask);
}

function activeAgvTaskRows() {
  return agvTaskRows().filter((row) => isActiveTaskStatus(normalizeAgvTask(row).status));
}

function activeAgvTasks() {
  return activeAgvTaskRows().map(normalizeAgvTask);
}

function archivedAgvTasks() {
  return agvTasks().filter((task) => isCompletedOrCancelledStatus(task.status));
}

function renderAgvTransportTaskView() {
  const tasks = agvTasks();
  const statusSummary = {
    waiting: tasks.filter((task) => task.status === "等待中").length,
    moving: tasks.filter((task) => task.status === "运输中").length,
    completed: tasks.filter((task) => task.status === "已完成").length,
    failed: tasks.filter((task) => task.status === "失败").length,
    cancelled: tasks.filter((task) => task.status === "已取消").length,
  };

  return `
    <div class="agv-task-view">
      <div class="agv-task-summary">
        <div><span>任务总数</span><strong>${tasks.length}</strong></div>
        <div><span>等待中</span><strong>${statusSummary.waiting}</strong></div>
        <div><span>运输中</span><strong>${statusSummary.moving}</strong></div>
        <div><span>已完成</span><strong>${statusSummary.completed}</strong></div>
        <div><span>失败</span><strong>${statusSummary.failed}</strong></div>
      </div>
      <div class="agv-task-lane">
        ${tasks.length ? tasks.map((task) => `
          <article class="agv-task-card">
            <div class="agv-task-card-head">
              ${typeIconHtml("agv", task.agv)}
              <div>
                <h4>${escapeHtml(task.id)}</h4>
                <p>${escapeHtml(task.type)}</p>
              </div>
              ${dataStatusChip(task.status)}
            </div>
            <div class="agv-route">
              <span>${escapeHtml(task.from)}</span>
              <b>→</b>
              <span>${escapeHtml(task.to)}</span>
            </div>
            <div class="order-tree-fields compact">
              <span>AGV小车</span><strong>${escapeHtml(task.agv)}</strong>
              <span>订单编号</span><strong>${escapeHtml(task.orderId || "-")}</strong>
              <span>工单编号</span><strong>${escapeHtml(task.workOrderId || "-")}</strong>
              <span>创建时间</span><strong>${escapeHtml(displayValue(task.createdAt))}</strong>
              <span>实际开始</span><strong>${escapeHtml(displayValue(task.startedAt))}</strong>
              <span>结束时间</span><strong>${escapeHtml(displayValue(task.endedAt))}</strong>
            </div>
          </article>
        `).join("") : "<article class='entity-card'><h3>暂无 AGV 运输任务</h3><p class='panel-muted'>order.work_orders 暂无 AGV 运输工单。</p></article>"}
      </div>
    </div>
  `;
}

function renderDataError() {
  if (state.data.ok) return "";
  return `<article class="entity-card"><h3>DATA 数据不可用</h3><p class="panel-muted">${escapeHtml(state.data.error || "请检查 /api/digital-twin/data 与 MySQL Data 数据库。")}</p></article>`;
}

function renderDataOrdersPage() {
  const orders = buildOrderTreeItems("data").filter(isArchivedOrderTreeItem);
  const summary = state.data.summary || {};
  const workOrderCount = orders.reduce((total, order) => total + (order.__workOrders || []).length, 0);
  return `
    <section class="page-grid">
      <article class="panel-card full-width">
        <div class="panel-header panel-header-spread">
          <div>
            <h2>订单工单历史</h2>
            <p class="panel-muted">仅归档整单已完成或失败的订单；部分工单完成仍保留在 Ontology / Orders 中更新状态。</p>
          </div>
          <div class="metric-group">${renderMetricPills([`${summary.archivedOrderCount ?? orders.length} 个历史订单`, `${summary.archivedWorkOrderCount ?? workOrderCount} 个历史工单`, state.data.ok ? "Data 在线" : "Data 离线"])}</div>
        </div>
        ${renderDataError()}
        ${renderOrderTree(orders, "Data.order_work_order_history 暂无整单完成或取消的历史记录。")}
      </article>
    </section>
  `;
}

function renderLoadCurve(values) {
  let curve = Array.isArray(values) ? values : [];
  if (!curve.length && typeof values === "string") {
    try {
      const parsed = JSON.parse(values);
      curve = Array.isArray(parsed) ? parsed : [];
    } catch {
      curve = [];
    }
  }
  if (!curve.length) return `<div class="load-curve-empty">未接入负载曲线数据源</div>`;
  const max = Math.max(...curve, 1);
  return `
    <div class="load-curve-bars">
      ${curve.map((value) => `<span style="height:${Math.max(8, (Number(value) / max) * 100)}%" title="${escapeHtml(value)}%"></span>`).join("")}
    </div>
  `;
}

function archivedAgvTaskHistoryRows() {
  return archivedAgvTasks().map((task) => ({
    history_id: `agv-history:${task.id}`,
    device_id: task.agv || "-",
    device_name: task.agv || "AGV小车",
    device_type: "AGV",
    order_id: task.orderId || "",
    work_order_id: task.workOrderId || task.id || "-",
    work_order_name: task.type || "AGV运输任务",
    run_start_time: task.startedAt || task.createdAt || "",
    run_end_time: task.endedAt || "",
    run_status: task.status,
    avg_load_percent: "",
    peak_load_percent: "",
    load_curve_json: [],
    transport_id: task.id,
    transport_route: `${task.from || "-"} -> ${task.to || "-"}`,
    __historySource: "order.work_orders",
  }));
}

function archivedWorkOrderHistoryRows() {
  return uniqueEntityItems("work_order", entityItems("work_order"))
    .filter((item) => !isActiveOntologyWorkOrder(item))
    .map((item) => {
      const row = { ...item.properties, ...item.runtime, ...item };
      const deviceText = assignedDeviceText(row) || deviceIdentity(row) || "-";
      return {
        history_id: `work-order-history:${workOrderIdentity(row) || item.id}`,
        device_id: deviceText,
        device_name: deviceText,
        device_type: rowType(row) || "Workstation",
        order_id: orderIdentity(row, ""),
        work_order_id: workOrderIdentity(row) || item.id || "-",
        work_order_name: workOrderTitle(row) || item.label || "执行工单",
        run_start_time: recordStartTime(row),
        run_end_time: recordEndTime(row),
        run_status: normalizeWorkOrderStatus(recordField(row, ["工单状态", "任务状态", "状态", "status", "state", "run_status"], item.status)),
        avg_load_percent: firstField(row, ["平均负载", "avg_load_percent", "avgLoadPercent"], ""),
        peak_load_percent: firstField(row, ["峰值负载", "peak_load_percent", "peakLoadPercent"], ""),
        load_curve_json: firstField(row, ["load_curve_json", "loadCurveJson", "负载曲线"], []),
        __historySource: Array.isArray(item.source) ? item.source.join(" · ") : item.source || "Ontology.work_order",
      };
    });
}

function deviceHistoryIdentity(row) {
  return normalizeText([
    row.history_id,
    row.device_id,
    row.work_order_id,
    row.transport_id,
    row.run_status,
    row.run_end_time,
  ].filter(Boolean).join("|"));
}

function dataDeviceHistoryRows() {
  const rows = Array.isArray(state.data.deviceHistory) ? state.data.deviceHistory : [];
  const seen = new Set(rows.map(deviceHistoryIdentity).filter(Boolean));
  const archivedRows = [...archivedWorkOrderHistoryRows(), ...archivedAgvTaskHistoryRows()].filter((row) => {
    const key = deviceHistoryIdentity(row);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return [...rows, ...archivedRows];
}

function historyRowRunId(row, index = 0) {
  return [
    row.history_id,
    row.transport_id,
    row.device_id,
    row.work_order_id,
    row.run_start_time,
    row.run_end_time,
    index,
  ].filter((value) => value !== undefined && value !== null && value !== "").join("|");
}

function historyDeviceKey(row) {
  return displayValue(row.device_id || row.device_name || "未识别设备");
}

function historyDeviceName(row) {
  return displayValue(row.device_name || row.device_id || "未识别设备");
}

function normalizedDeviceHistoryRows() {
  return dataDeviceHistoryRows().map((row, index) => ({
    ...row,
    __runId: historyRowRunId(row, index),
    __deviceKey: historyDeviceKey(row),
  }));
}

function groupDeviceHistoryRows(rows) {
  const groups = new Map();
  rows.forEach((row) => {
    const key = row.__deviceKey;
    if (!groups.has(key)) {
      groups.set(key, {
        id: key,
        deviceId: displayValue(row.device_id || key),
        deviceName: historyDeviceName(row),
        deviceType: displayValue(row.device_type || "-"),
        rows: [],
      });
    }
    groups.get(key).rows.push(row);
  });
  return Array.from(groups.values()).map((group) => {
    const completed = group.rows.filter((row) => normalizeText(displayValue(row.run_status)).includes("完成")).length;
    const failed = group.rows.filter((row) => {
      const status = normalizeText(displayValue(row.run_status));
      return status.includes("失败") || status.includes("取消") || status.includes("fail") || status.includes("cancel");
    }).length;
    const latestEnd = group.rows.map((row) => displayValue(row.run_end_time, "")).filter(Boolean).sort().at(-1) || "";
    return { ...group, completed, failed, latestEnd };
  });
}

function selectedDeviceHistoryGroup(groups) {
  if (!groups.length) return null;
  return groups.find((group) => group.id === state.dataDeviceHistory.selectedDeviceId) || groups[0];
}

function selectedDeviceHistoryRun(group) {
  if (!group?.rows?.length) return null;
  return group.rows.find((row) => row.__runId === state.dataDeviceHistory.selectedRunId) || group.rows[0];
}

function historyOrderId(row) {
  return firstField(row, ["订单编号", "订单ID", "order_id", "orderId", "order"], "");
}

function historyRunTitle(row) {
  return displayValue(row.work_order_name || row.transport_id || row.work_order_id || "运行记录");
}

function findRelatedOrderForHistory(row) {
  const orderId = normalizeText(historyOrderId(row));
  const workOrderId = normalizeText(row.work_order_id || row.transport_id || "");
  const dataOrders = Array.isArray(state.data.orderTree) ? state.data.orderTree : [];
  const matchedDataOrder = dataOrders.find((order) => {
    const currentOrderId = normalizeText(orderIdentity(order, ""));
    const workOrders = Array.isArray(order.work_orders) ? order.work_orders : [];
    return (orderId && currentOrderId && orderId.includes(currentOrderId))
      || workOrders.some((workOrder) => {
        const currentWorkOrderId = normalizeText(workOrderIdentity(workOrder));
        return workOrderId && currentWorkOrderId && workOrderId.includes(currentWorkOrderId);
      });
  });
  if (matchedDataOrder) return matchedDataOrder;

  const ontologyOrders = uniqueEntityItems("order", entityItems("order"));
  return ontologyOrders.find((order) => {
    const row = { ...order.properties, ...order.runtime, ...order };
    const currentOrderId = normalizeText(orderIdentity(row, ""));
    return orderId && currentOrderId && orderId.includes(currentOrderId);
  }) || null;
}

function findRelatedWorkOrderForHistory(row) {
  const workOrderId = normalizeText(row.work_order_id || row.transport_id || "");
  if (!workOrderId) return null;
  const dataOrders = Array.isArray(state.data.orderTree) ? state.data.orderTree : [];
  for (const order of dataOrders) {
    const workOrders = Array.isArray(order.work_orders) ? order.work_orders : [];
    const matched = workOrders.find((workOrder) => {
      const currentWorkOrderId = normalizeText(workOrderIdentity(workOrder));
      return currentWorkOrderId && workOrderId.includes(currentWorkOrderId);
    });
    if (matched) return matched;
  }

  return uniqueEntityItems("work_order", entityItems("work_order")).find((item) => {
    const itemRow = { ...item.properties, ...item.runtime, ...item };
    const currentWorkOrderId = normalizeText(workOrderIdentity(itemRow));
    return currentWorkOrderId && workOrderId.includes(currentWorkOrderId);
  }) || null;
}

function renderHistoryRunDetail(row) {
  if (!row) {
    return `<article class="entity-card"><h3>请选择运行条目</h3><p class="panel-muted">点击左侧运行条目查看任务和订单信息。</p></article>`;
  }
  const relatedOrder = findRelatedOrderForHistory(row);
  const relatedWorkOrder = findRelatedWorkOrderForHistory(row);
  const orderRow = relatedOrder ? { ...relatedOrder.properties, ...relatedOrder.runtime, ...relatedOrder } : null;
  const workOrderRow = relatedWorkOrder ? { ...relatedWorkOrder.properties, ...relatedWorkOrder.runtime, ...relatedWorkOrder } : null;
  const orderId = historyOrderId(row) || (orderRow ? orderIdentity(orderRow, "") : "");
  const orderName = orderRow ? recordField(orderRow, ["订单名称", "order_name", "orderName", "name"], orderId || "-") : "-";
  const product = orderRow ? recordField(orderRow, ["产品名称", "产品ID", "product_name", "product_id", "productName", "productId"], "-") : "-";
  const workOrderStatus = workOrderRow ? normalizeWorkOrderStatus(recordField(workOrderRow, ["工单状态", "任务状态", "状态", "status", "state", "run_status"], row.run_status)) : row.run_status;

  return `
    <article class="entity-card device-history-detail">
      <div class="entity-card-head">
        <div>
          <h3>${escapeHtml(historyRunTitle(row))}</h3>
          <p class="panel-muted">${escapeHtml(row.device_name || row.device_id || "-")} · ${escapeHtml(row.device_type || "-")}</p>
        </div>
        ${dataStatusChip(row.run_status)}
      </div>
      <div class="order-tree-fields compact">
        <span>设备编号</span><strong>${escapeHtml(row.device_id || "-")}</strong>
        <span>任务编号</span><strong>${escapeHtml(row.work_order_id || row.transport_id || "-")}</strong>
        <span>开始时间</span><strong>${escapeHtml(displayValue(row.run_start_time))}</strong>
        <span>结束时间</span><strong>${escapeHtml(displayValue(row.run_end_time))}</strong>
        <span>平均负载</span><strong>${escapeHtml(row.avg_load_percent === "" ? "-" : `${displayValue(row.avg_load_percent, "0")}%`)}</strong>
        <span>峰值负载</span><strong>${escapeHtml(row.peak_load_percent === "" ? "-" : `${displayValue(row.peak_load_percent, "0")}%`)}</strong>
        ${row.transport_route ? `<span>运输路径</span><strong>${escapeHtml(row.transport_route)}</strong>` : ""}
        ${row.__historySource ? `<span>来源</span><strong>${escapeHtml(row.__historySource)}</strong>` : ""}
      </div>
      <div class="panel-divider"></div>
      <div class="property-two-column">
        <section class="property-section">
          <div class="panel-subtitle">对应任务</div>
          <div class="entity-fields">
            <span>任务名称</span><span>${escapeHtml(workOrderRow ? workOrderTitle(workOrderRow) : historyRunTitle(row))}</span>
            <span>任务编号</span><span>${escapeHtml(workOrderRow ? workOrderIdentity(workOrderRow) || row.work_order_id || "-" : row.work_order_id || row.transport_id || "-")}</span>
            <span>任务状态</span><span>${escapeHtml(displayValue(workOrderStatus))}</span>
            <span>执行设备</span><span>${escapeHtml(workOrderRow ? assignedDeviceText(workOrderRow) || row.device_name || row.device_id || "-" : row.device_name || row.device_id || "-")}</span>
          </div>
        </section>
        <section class="property-section">
          <div class="panel-subtitle">相关订单</div>
          <div class="entity-fields">
            <span>订单编号</span><span>${escapeHtml(orderId || "-")}</span>
            <span>订单名称</span><span>${escapeHtml(orderName)}</span>
            <span>产品</span><span>${escapeHtml(product)}</span>
            <span>订单状态</span><span>${escapeHtml(orderRow ? normalizeOrderStatus(recordField(orderRow, ["订单状态", "状态", "status", "state"], "-")) : "-")}</span>
          </div>
        </section>
      </div>
      ${renderLoadCurve(row.load_curve_json)}
    </article>
  `;
}

function renderDataDevicesPage() {
  const rows = normalizedDeviceHistoryRows();
  const groups = groupDeviceHistoryRows(rows);
  const selectedGroup = selectedDeviceHistoryGroup(groups);
  const selectedRun = selectedDeviceHistoryRun(selectedGroup);
  const module = state.data.loadCurveModule || {};
  return `
    <section class="page-grid">
      <article class="panel-card full-width">
        <div class="panel-header panel-header-spread">
          <div>
            <h2>设备运行历史</h2>
            <p class="panel-muted">按设备归档已结束运行记录；点击设备卡片查看详细历史，点击运行条目查看对应任务与订单信息。</p>
          </div>
          <div class="metric-group">${renderMetricPills([`${groups.length} devices`, `${rows.length} runs`, module.status || "module-only"])}</div>
        </div>
        ${renderDataError()}
        ${groups.length ? `
          <div class="device-history-layout">
            <div class="device-history-device-list">
              ${groups.map((group) => `
                <button class="entity-card device-history-device-card ${selectedGroup?.id === group.id ? "active" : ""}" type="button" data-device-history-device="${escapeHtml(group.id)}">
                  <div class="entity-card-head">
                    <div>
                      <h3>${escapeHtml(group.deviceName)}</h3>
                      <p class="panel-muted">${escapeHtml(group.deviceType)} · ${escapeHtml(group.deviceId)}</p>
                    </div>
                    <span class="status-chip online">${group.rows.length} 条</span>
                  </div>
                  <div class="entity-fields">
                    <span>已完成</span><span>${escapeHtml(group.completed)}</span>
                    <span>失败</span><span>${escapeHtml(group.failed)}</span>
                    <span>最近结束</span><span>${escapeHtml(displayValue(group.latestEnd))}</span>
                  </div>
                </button>
              `).join("")}
            </div>
            <div class="device-history-run-panel">
              <div class="panel-header compact-header">
                <div>
                  <h3>${escapeHtml(selectedGroup?.deviceName || "设备详细历史")}</h3>
                  <p class="panel-muted">${escapeHtml(selectedGroup ? `${selectedGroup.rows.length} 条运行记录` : "请选择设备")}</p>
                </div>
              </div>
              <div class="device-history-run-list">
                ${(selectedGroup?.rows || []).map((row) => `
                  <button class="device-history-run-item ${selectedRun?.__runId === row.__runId ? "active" : ""}" type="button" data-device-history-run="${escapeHtml(row.__runId)}">
                    <span>
                      <strong>${escapeHtml(historyRunTitle(row))}</strong>
                      <small>${escapeHtml(displayValue(row.run_start_time))} / ${escapeHtml(displayValue(row.run_end_time))}</small>
                    </span>
                    ${dataStatusChip(row.run_status)}
                  </button>
                `).join("")}
              </div>
              ${renderHistoryRunDetail(selectedRun)}
            </div>
          </div>
        ` : "<article class='entity-card'><h3>暂无设备运行历史</h3><p class='panel-muted'>Data.device_run_history 为空。</p></article>"}
      </article>
    </section>
  `;
}

function renderDataQualityPage() {
  const rows = state.data.qualityTrace || [];
  return `
    <section class="page-grid">
      <article class="panel-card full-width">
        <div class="panel-header panel-header-spread">
          <div>
            <h2>质检追溯</h2>
            <p class="panel-muted">存储质检工序产品历史、合格后贴标产品编号，并关联物料与部件用于追溯。</p>
          </div>
          <div class="metric-group">${renderMetricPills([`${rows.length} quality records`, "trace ready"])}</div>
        </div>
        ${renderDataError()}
        <div class="entity-list-wrap">
          <table class="entity-list-table">
            <thead>
              <tr>
                <th>Inspection</th>
                <th>Product</th>
                <th>Result</th>
                <th>Label Code</th>
                <th>Materials / Parts</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              ${rows.length ? rows.map((row) => `
                <tr>
                  <td><strong>${escapeHtml(row.inspection_id || "-")}</strong><br><small class="panel-muted">${escapeHtml(row.process_name || "质检")}</small></td>
                  <td>${escapeHtml(row.product_name || row.product_id || "-")}</td>
                  <td>${dataStatusChip(row.inspection_result)}</td>
                  <td>${escapeHtml(row.label_product_code || "未贴标")}</td>
                  <td>${escapeHtml([row.material_batch_ids, row.part_codes].filter(Boolean).join(" / ") || "-")}</td>
                  <td>${escapeHtml(displayValue(row.inspection_start_time))}<br>${escapeHtml(displayValue(row.inspection_end_time))}</td>
                </tr>
              `).join("") : `<tr><td colspan="6" class="class-table-empty">暂无质检追溯记录</td></tr>`}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  `;
}

function globalSearchTypeLabel(entityType) {
  return ENTITY_META[entityType]?.title || entityType || "-";
}

function globalSearchCode(item, entityType) {
  const props = itemProperties(item);
  const fallback = prefixedIdValue(item?.id || "");
  if (entityType === "device") {
    return firstField(props, ["设备编号", "设备ID", "AGV编号", "device_code", "deviceCode", "device_id", "deviceId", "agv_id", "agvId", "code", "id"], fallback);
  }
  if (entityType === "order") {
    return firstField(props, ["订单编号", "订单ID", "order_id", "orderId", "code", "id"], fallback);
  }
  if (entityType === "work_order") {
    return firstField(props, ["工单编号", "工单ID", "任务编号", "work_order_id", "workOrderId", "task_id", "taskId", "code", "id"], fallback);
  }
  if (entityType === "material") {
    return firstField(props, ["物料编号", "物料编码", "产品编号", "material_code", "materialCode", "product_code", "productCode", "code"], fallback);
  }
  if (entityType === "product") {
    return firstField(props, ["产品编号", "产品ID", "product_code", "productCode", "product_id", "productId", "code", "id"], fallback);
  }
  return firstField(props, ["工序编号", "工艺编号", "process_code", "processCode", "craft_code", "craftCode", "code", "id"], fallback);
}

function globalSearchStatus(item) {
  const props = itemProperties(item);
  return firstField(props, ["状态", "运行状态", "设备状态", "订单状态", "工单状态", "任务状态", "库存状态", "status", "state", "runtime_status"], item?.status || "实时");
}

function globalSearchStationProcess(item, entityType) {
  const props = itemProperties(item);
  const value = firstField(props, [
    "所属工站",
    "分配工站",
    "分配工位",
    "工站",
    "工位",
    "工序",
    "工序名称",
    "工艺",
    "工艺名称",
    "process_name",
    "processName",
    "craft_name",
    "craftName",
    "workstation_name",
    "workstationName",
    "station_name",
    "stationName",
    "assigned_workstation_name",
    "assigned_station_name",
  ], "");
  if (value) return value;
  if (entityType === "process" || entityType === "craft") return entityDisplayLabel(item, entityType);
  return "-";
}

function buildGlobalSearchRecords() {
  return GLOBAL_SEARCH_ENTITY_TYPES.flatMap((entityType) =>
    uniqueEntityItems(entityType, entityItems(entityType)).map((item, index) => {
      const id = item.id || `${entityType}:${index}`;
      const label = entityDisplayLabel(item, entityType);
      const subtitle = entityDisplaySubtitle(item, entityType);
      const code = globalSearchCode(item, entityType);
      const status = globalSearchStatus(item);
      const stationProcess = globalSearchStationProcess(item, entityType);
      return {
        id,
        entityType,
        item,
        label,
        subtitle,
        code,
        status,
        stationProcess,
        source: sourceText(item.source),
        iconType: entityIconType(entityType, item),
        searchText: normalizeText(`${id} ${label} ${subtitle} ${code} ${status} ${stationProcess} ${rowText(item)}`),
      };
    })
  );
}

function uniqueOptionValues(records, key) {
  const values = new Set();
  records.forEach((record) => {
    const value = String(record[key] || "").trim();
    if (value && value !== "-") values.add(value);
  });
  return Array.from(values).sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
}

function globalSearchScore(record, query) {
  const q = normalizeText(query || "");
  if (!q) return 0;
  const id = normalizeText(record.id);
  const code = normalizeText(record.code);
  const label = normalizeText(record.label);
  if (id === q || code === q || label === q) return 0;
  if (id.startsWith(q) || code.startsWith(q) || label.startsWith(q)) return 1;
  if (record.searchText.includes(q)) return 2;
  return 9;
}

function filteredGlobalSearchRecords(records) {
  const { query, entityType, status, stationProcess } = state.globalSearch;
  const q = normalizeText(query || "");
  const statusQuery = normalizeText(status === "all" ? "" : status);
  const stationQuery = normalizeText(stationProcess === "all" ? "" : stationProcess);
  return records
    .filter((record) => {
      if (entityType !== "all" && record.entityType !== entityType) return false;
      if (q && !record.searchText.includes(q)) return false;
      if (statusQuery && !normalizeText(record.status).includes(statusQuery)) return false;
      if (stationQuery && !normalizeText(record.stationProcess).includes(stationQuery)) return false;
      return true;
    })
    .sort((a, b) => globalSearchScore(a, q) - globalSearchScore(b, q) || a.label.localeCompare(b.label, "zh-Hans-CN"));
}

function renderGlobalSearchTypeOptions(selectedValue) {
  return [
    `<option value="all" ${selectedValue === "all" ? "selected" : ""}>全部对象</option>`,
    ...GLOBAL_SEARCH_ENTITY_TYPES.map((entityType) => `<option value="${escapeHtml(entityType)}" ${selectedValue === entityType ? "selected" : ""}>${escapeHtml(globalSearchTypeLabel(entityType))}</option>`),
  ].join("");
}

function renderGlobalSearchSelectOptions(values, allLabel, selectedValue) {
  return [
    `<option value="all" ${selectedValue === "all" ? "selected" : ""}>${escapeHtml(allLabel)}</option>`,
    ...values.map((value) => `<option value="${escapeHtml(value)}" ${selectedValue === value ? "selected" : ""}>${escapeHtml(value)}</option>`),
  ].join("");
}

function addGlobalSearchHistory(resultCount) {
  const query = state.globalSearch.query.trim();
  if (!query && state.globalSearch.entityType === "all" && state.globalSearch.status === "all" && state.globalSearch.stationProcess === "all") return;
  const entry = {
    id: `${Date.now()}`,
    query,
    entityType: state.globalSearch.entityType,
    status: state.globalSearch.status,
    stationProcess: state.globalSearch.stationProcess,
    resultCount,
    createdAt: new Date().toISOString(),
  };
  state.globalSearch.history = [
    entry,
    ...state.globalSearch.history.filter((item) =>
      item.query !== entry.query ||
      item.entityType !== entry.entityType ||
      item.status !== entry.status ||
      item.stationProcess !== entry.stationProcess
    ),
  ].slice(0, 12);
  storeSearchHistory();
}

function applyGlobalSearchHistory(index) {
  const entry = state.globalSearch.history[Number(index)];
  if (!entry) return;
  state.globalSearch.query = entry.query || "";
  state.globalSearch.entityType = entry.entityType || "all";
  state.globalSearch.status = entry.status || "all";
  state.globalSearch.stationProcess = entry.stationProcess || "all";
  renderPage();
}

function clearGlobalSearchHistory() {
  state.globalSearch.history = [];
  storeSearchHistory();
  renderPage();
}

async function openGlobalSearchResult(entityType, entityId) {
  const route = ENTITY_META[entityType]?.route || "/ontology/classes";
  state.route = route;
  if (normalizeRoute(location.hash) !== route) {
    location.hash = `#${route}`;
  }
  renderShell();
  await openEntity(entityType, entityId);
}

function openGlobalSearchTopology(entityType) {
  const classNodeId = entityType === "work_order" ? "work-order" : entityType === "device" ? "workstation" : entityType;
  state.route = "/ontology/classes";
  state.classTopologyMode = entityType === "device" || entityType === "craft" ? "device-craft" : entityType === "product" || entityType === "process" || entityType === "material" ? "product-process" : "production";
  state.classViewMode = "topology";
  if (normalizeRoute(location.hash) !== "/ontology/classes") {
    location.hash = "#/ontology/classes";
  }
  renderShell();
  if (CLASS_TOPOLOGY_NODES.some((node) => node.id === classNodeId)) {
    openClassTopologyModule(classNodeId);
  } else {
    renderPage();
  }
}

function renderGlobalSearchHistory() {
  if (!state.globalSearch.history.length) {
    return `<p class="panel-muted">暂无查询历史。提交一次检索后会在这里保留最近 12 条查询轨迹。</p>`;
  }
  return `
    <div class="search-history-list">
      ${state.globalSearch.history.map((entry, index) => `
        <button class="search-history-item" type="button" data-search-history-index="${index}">
          <strong>${escapeHtml(entry.query || "筛选查询")}</strong>
          <span>${escapeHtml(entry.entityType === "all" ? "全部对象" : globalSearchTypeLabel(entry.entityType))} · ${escapeHtml(entry.resultCount)} 条结果</span>
          <small>${escapeHtml(new Date(entry.createdAt).toLocaleString())}</small>
        </button>
      `).join("")}
    </div>
  `;
}

function renderSearchPage() {
  const records = buildGlobalSearchRecords();
  const results = filteredGlobalSearchRecords(records);
  const statusOptions = uniqueOptionValues(records, "status");
  const stationOptions = uniqueOptionValues(records, "stationProcess");
  const suggestions = records.slice(0, 18).map((record) => `${record.label} ${record.code}`).filter(Boolean);

  return `
    <section class="page-grid global-search-page">
      <article class="panel-card full-width">
        <div class="panel-header panel-header-spread">
          <div>
            <h2>Global Search</h2>
            <p class="panel-muted">跨设备、订单、工单、物料、产品、工序和工艺统一检索，支持关键词、ID、状态、工站或工序组合过滤。</p>
          </div>
          <div class="metric-group">${renderMetricPills([`${results.length}/${records.length} 条结果`, statusBadgeText()])}</div>
        </div>

        <form class="global-search-form" data-global-search-form>
          <div class="global-search-main">
            <input
              class="search-input"
              type="search"
              value="${escapeHtml(state.globalSearch.query)}"
              placeholder="输入关键词、ID 或部分名称..."
              list="global-search-suggestions"
              data-global-search-query
              autocomplete="off"
              spellcheck="false"
            />
            <button class="toolbar-btn primary" type="submit">Search</button>
            <button class="toolbar-btn" type="button" data-global-search-refresh>刷新最新数据</button>
          </div>
          <datalist id="global-search-suggestions">
            ${suggestions.map((item) => `<option value="${escapeHtml(item)}"></option>`).join("")}
          </datalist>
          <div class="global-search-filters">
            <label>
              <span>对象类型</span>
              <select class="ontology-select" data-global-search-filter="entityType">
                ${renderGlobalSearchTypeOptions(state.globalSearch.entityType)}
              </select>
            </label>
            <label>
              <span>状态</span>
              <select class="ontology-select" data-global-search-filter="status">
                ${renderGlobalSearchSelectOptions(statusOptions, "全部状态", state.globalSearch.status)}
              </select>
            </label>
            <label>
              <span>工站 / 工序</span>
              <select class="ontology-select" data-global-search-filter="stationProcess">
                ${renderGlobalSearchSelectOptions(stationOptions, "全部工站 / 工序", state.globalSearch.stationProcess)}
              </select>
            </label>
          </div>
        </form>

        <div class="global-search-layout">
          <div class="entity-list-wrap global-search-results">
            <table class="entity-list-table">
              <thead>
                <tr>
                  <th>对象</th>
                  <th>编号</th>
                  <th>类型</th>
                  <th>状态</th>
                  <th>工站 / 工序</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                ${results.length ? results.map((record) => `
                  <tr>
                    <td>
                      <button class="entity-list-name entity-clickable" type="button" data-search-open-type="${escapeHtml(record.entityType)}" data-search-open-id="${escapeHtml(record.id)}">
                        ${typeIconHtml(record.iconType, record.label)}
                        <span>
                          <strong>${escapeHtml(record.label)}</strong>
                          <small>${escapeHtml(record.subtitle || record.source)}</small>
                        </span>
                      </button>
                    </td>
                    <td>${escapeHtml(record.code || record.id)}</td>
                    <td><span class="entity-type-pill">${escapeHtml(globalSearchTypeLabel(record.entityType))}</span></td>
                    <td><span class="status-chip ${statusClass(record.status)}">${escapeHtml(record.status || "实时")}</span></td>
                    <td>${escapeHtml(record.stationProcess || "-")}</td>
                    <td>
                      <div class="global-search-actions">
                        <button class="toolbar-btn" type="button" data-search-open-type="${escapeHtml(record.entityType)}" data-search-open-id="${escapeHtml(record.id)}">属性视图</button>
                        <button class="toolbar-btn" type="button" data-search-topology-type="${escapeHtml(record.entityType)}">拓扑图</button>
                      </div>
                    </td>
                  </tr>
                `).join("") : `
                  <tr>
                    <td colspan="6" class="class-table-empty">没有匹配结果，请调整关键词或筛选条件。</td>
                  </tr>
                `}
              </tbody>
            </table>
          </div>

          <aside class="entity-card compact-card search-history-panel">
            <div class="entity-card-head">
              <div>
                <h3>History</h3>
                <p class="panel-muted">记录最近的 Global Search 查询行为。</p>
              </div>
              <button class="toolbar-btn" type="button" data-search-history-clear>清空</button>
            </div>
            ${renderGlobalSearchHistory()}
          </aside>
        </div>
      </article>
    </section>
  `;
}

function parseTimeMs(value) {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const text = String(value).trim();
  if (!text) return null;
  const direct = Date.parse(text);
  if (!Number.isNaN(direct)) return direct;
  const normalized = Date.parse(text.replace(" ", "T"));
  return Number.isNaN(normalized) ? null : normalized;
}

function durationSeconds(start, end) {
  const startMs = parseTimeMs(start);
  const endMs = parseTimeMs(end);
  if (startMs === null || endMs === null || endMs < startMs) return null;
  return Math.round((endMs - startMs) / 1000);
}

function explicitDurationSeconds(record) {
  const value = recordField(record, ["用时", "耗时", "总用时", "duration_seconds", "durationSecond", "duration_sec", "duration", "elapsed_seconds"], "");
  const numberValue = Number(value);
  return Number.isFinite(numberValue) && numberValue > 0 ? numberValue : null;
}

function recordDurationSeconds(record) {
  return explicitDurationSeconds(record) ?? durationSeconds(recordStartTime(record), recordEndTime(record));
}

function formatDuration(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value)) return "-";
  if (value >= 3600) return `${(value / 3600).toFixed(1)} h`;
  if (value >= 60) return `${Math.round(value / 60)} min`;
  return `${Math.round(value)} s`;
}

function buildProductionAnalysis() {
  const orders = buildOrderTreeItems("data");
  const batches = [];
  const processMap = new Map();
  const flow = [];
  const seenProcess = new Set();

  orders.forEach((order) => {
    const orderDuration = recordDurationSeconds(order);
    const processDurations = [];
    (order.__workOrders || []).forEach((workOrder) => {
      const processName = workOrder.__subtitle || recordField(workOrder, ["工序名称", "process_name", "processName"], "未命名工序");
      const duration = recordDurationSeconds(workOrder);
      if (!seenProcess.has(processName)) {
        seenProcess.add(processName);
        flow.push(processName);
      }
      if (duration !== null) {
        processDurations.push({
          processName,
          duration,
          station: workOrder.__station,
          start: recordStartTime(workOrder),
          end: recordEndTime(workOrder),
        });
        const stats = processMap.get(processName) || { processName, durations: [], stations: new Set() };
        stats.durations.push(duration);
        if (workOrder.__station && workOrder.__station !== "-") stats.stations.add(workOrder.__station);
        processMap.set(processName, stats);
      }
    });

    const totalDuration = orderDuration ?? processDurations.reduce((total, item) => total + item.duration, 0);
    if (totalDuration > 0 || processDurations.length) {
      batches.push({
        id: order.__treeId,
        label: order.__label,
        product: recordField(order, ["产品名称", "产品ID", "product_name", "product_id"], order.__subtitle || "产品"),
        totalDuration,
        start: recordStartTime(order),
        end: recordEndTime(order),
        processDurations,
      });
    }
  });

  const processStats = Array.from(processMap.values()).map((item) => {
    const sum = item.durations.reduce((total, value) => total + value, 0);
    return {
      processName: item.processName,
      avg: sum / item.durations.length,
      min: Math.min(...item.durations),
      max: Math.max(...item.durations),
      count: item.durations.length,
      stations: Array.from(item.stations),
    };
  });

  return { batches, flow, processStats };
}

function isProductionReportRequest(text) {
  const value = normalizeText(text);
  return value.includes("产品") && value.includes("报告") && (value.includes("生产分析") || value.includes("用时分析") || value.includes("工序用时"));
}

function reportTable(headers, rows) {
  if (!rows.length) return "暂无可统计数据。";
  const header = `| ${headers.join(" | ")} |`;
  const divider = `| ${headers.map(() => "---").join(" | ")} |`;
  const body = rows.map((row) => `| ${row.map((cell) => String(cell ?? "-").replace(/\|/g, "/")).join(" | ")} |`);
  return [header, divider, ...body].join("\n");
}

function extractReportTitle(content) {
  const firstTitle = String(content || "").split(/\r?\n/).find((line) => line.trim().startsWith("# "));
  return firstTitle ? firstTitle.replace(/^#\s+/, "").trim() : "产品生产分析报告";
}

function reportContentSummary(content) {
  return String(content || "")
    .replace(/^#+\s+/gm, "")
    .replace(/\|/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 120);
}

function saveGeneratedReportFromContent(content) {
  const analysis = buildProductionAnalysis();
  const product = analysis.batches[0]?.product || "产品";
  const createdAt = new Date().toISOString();
  const report = {
    id: `RPT-GEN-${createdAt.replace(/[-:.TZ]/g, "").slice(0, 14)}`,
    title: `${extractReportTitle(content)} - ${product}`,
    summary: reportContentSummary(content),
    status: "Active",
    kind: "generated",
    format: "Markdown",
    createdAt,
    source: "AI Agent",
    skillPath: productionReportTemplate()?.skillPath || "skills/product-production-analysis-report/SKILL.md",
    content,
  };
  state.reports = [report, ...state.reports.filter((item) => item.id !== report.id)];
  storeReports();
}

function buildProductionAnalysisReportText() {
  const template = productionReportTemplate();
  const analysis = buildProductionAnalysis();
  const batches = analysis.batches;
  const processStats = analysis.processStats;

  if (!batches.length) {
    return [
      "# 产品生产分析报告",
      "",
      "当前 DATA 订单工单历史中没有可计算的生产用时数据。请确认 `/api/digital-twin/data` 返回了 `orderTree`，且订单/工单包含开始时间与结束时间。",
      "",
      `参考 Skill：${template?.skillPath || "skills/product-production-analysis-report/SKILL.md"}`,
    ].join("\n");
  }

  const totalDurations = batches.map((item) => item.totalDuration).filter((value) => Number.isFinite(value));
  const avgTotal = totalDurations.reduce((total, value) => total + value, 0) / totalDurations.length;
  const minTotal = Math.min(...totalDurations);
  const maxTotal = Math.max(...totalDurations);
  const bottleneck = [...processStats].sort((a, b) => b.avg - a.avg)[0];
  const longestBatch = [...batches].sort((a, b) => b.totalDuration - a.totalDuration)[0];

  const batchRows = batches.map((item) => [
    item.id,
    item.product,
    formatDuration(item.totalDuration),
    `${item.processDurations.length} 道工序`,
  ]);
  const processRows = processStats.map((item) => [
    item.processName,
    item.stations.join(" / ") || "未绑定工站",
    formatDuration(item.avg),
    formatDuration(item.min),
    formatDuration(item.max),
    item.count,
  ]);
  const timelineRows = (longestBatch?.processDurations || []).map((item, index) => [
    `工序${index + 1}`,
    item.processName,
    item.station || "-",
    formatDuration(item.duration),
  ]);

  return [
    "# 产品生产分析报告",
    "",
    `参考模板：${template?.title || "产品生产分析报告模板"} (${template?.id || "RPT-PRODUCTION-ANALYSIS"})`,
    `本地 Skill：${template?.skillPath || "skills/product-production-analysis-report/SKILL.md"}`,
    "",
    "## 1. 摘要",
    "",
    `本次基于 DATA 订单工单历史统计了 ${batches.length} 个订单/批次。平均生产用时为 ${formatDuration(avgTotal)}，最短 ${formatDuration(minTotal)}，最长 ${formatDuration(maxTotal)}。`,
    bottleneck ? `当前平均用时最长的工序为「${bottleneck.processName}」，平均用时 ${formatDuration(bottleneck.avg)}，建议作为瓶颈优先排查对象。` : "当前工序用时数据不足，暂不判断瓶颈工序。",
    "",
    "## 2. 产品-工序拓扑流程",
    "",
    analysis.flow.length ? analysis.flow.map((name, index) => `工序${index + 1}：${name}`).join(" -> ") : "暂无可展示的产品-工序拓扑流程。",
    "",
    "## 3. 产品生产用时分布",
    "",
    reportTable(["订单/批次", "产品", "总用时", "工序数"], batchRows),
    "",
    "## 4. 各工序用时分析",
    "",
    reportTable(["工序", "工站", "平均用时", "最短", "最长", "样本数"], processRows),
    "",
    "## 5. 单次生产时间线",
    "",
    longestBatch ? `选取总用时最长的订单/批次：${longestBatch.id}。` : "暂无可选订单/批次。",
    "",
    reportTable(["序号", "工序", "工站", "用时"], timelineRows),
    "",
    "## 6. 建议",
    "",
    bottleneck
      ? `优先核查「${bottleneck.processName}」对应工站的节拍、等待、上下料和设备负载；若该工序波动较大，可进一步按订单批次、设备和人员维度拆分。`
      : "补充工单开始/结束时间后，再进行瓶颈与波动分析。",
  ].join("\n");
}

function renderProductionTimeDistribution(analysis) {
  const max = Math.max(...analysis.batches.map((item) => item.totalDuration), 1);
  if (!analysis.batches.length) return `<div class="load-curve-empty">暂无可计算的生产用时数据</div>`;
  return `
    <div class="analysis-bars">
      ${analysis.batches.slice(0, 8).map((item) => `
        <div class="analysis-bar-row">
          <span>${escapeHtml(item.label || item.id)}</span>
          <div class="analysis-bar-track">
            <i style="width:${Math.max(6, (item.totalDuration / max) * 100)}%"></i>
          </div>
          <strong>${escapeHtml(formatDuration(item.totalDuration))}</strong>
        </div>
      `).join("")}
    </div>
  `;
}

function renderProcessFlow(analysis) {
  if (!analysis.flow.length) return `<div class="load-curve-empty">暂无产品-工序拓扑数据</div>`;
  return `
    <div class="process-flow">
      ${analysis.flow.slice(0, 8).map((name, index) => `
        <span class="process-flow-node">
          <strong>工序${index + 1}</strong>
          <em>${escapeHtml(name)}</em>
        </span>
      `).join("<b>→</b>")}
    </div>
  `;
}

function renderProcessDurationStats(analysis) {
  const max = Math.max(...analysis.processStats.map((item) => item.avg), 1);
  if (!analysis.processStats.length) return `<div class="load-curve-empty">暂无工序用时统计</div>`;
  return `
    <div class="process-stats">
      ${analysis.processStats.map((item) => `
        <div class="process-stat-row">
          <div>
            <strong>${escapeHtml(item.processName)}</strong>
            <span>${escapeHtml(item.stations.join(" / ") || "未绑定工站")}</span>
          </div>
          <div class="analysis-bar-track">
            <i style="width:${Math.max(6, (item.avg / max) * 100)}%"></i>
          </div>
          <strong>${escapeHtml(formatDuration(item.avg))}</strong>
        </div>
      `).join("")}
    </div>
  `;
}

function renderProductionAnalysisPanel() {
  const template = productionReportTemplate();
  const analysis = buildProductionAnalysis();
  const avgTotal = analysis.batches.length
    ? analysis.batches.reduce((total, item) => total + item.totalDuration, 0) / analysis.batches.length
    : 0;

  return `
    <article class="panel-card full-width production-analysis-panel">
      <div class="panel-header panel-header-spread">
        <div>
          <h2>产品生产分析报告预览</h2>
          <p class="panel-muted">依据 Data 中的订单、工单开始/结束时间生成生产用时分布和工序用时分析。</p>
        </div>
        <div class="metric-group">${renderMetricPills([template ? template.id : "Template missing", `${analysis.batches.length} batches`, `平均 ${formatDuration(avgTotal)}`])}</div>
      </div>
      <div class="analysis-grid">
        <section>
          <h3>产品生产用时分布</h3>
          ${renderProductionTimeDistribution(analysis)}
        </section>
        <section>
          <h3>产品-工序拓扑流程</h3>
          ${renderProcessFlow(analysis)}
        </section>
        <section class="analysis-wide">
          <h3>各工序用时</h3>
          ${renderProcessDurationStats(analysis)}
        </section>
      </div>
    </article>
  `;
}

function displayValue(value, fallback = "-") {
  if (value === undefined || value === null || value === "") return fallback;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function statusClass(value) {
  const text = normalizeText(displayValue(value));
  if (!text || text === "-") return "idle";
  if (text.includes("失败") || text.includes("取消") || text.includes("fail") || text.includes("error") || text.includes("fault") || text.includes("异常") || text.includes("cancel")) return "failed";
  if (text.includes("完成") || text.includes("成功") || text.includes("complete") || text.includes("finish") || text.includes("done") || text.includes("succeed")) return "completed";
  if (text.includes("执行") || text.includes("运行") || text.includes("生产") || text.includes("busy") || text.includes("running") || text.includes("processing") || text.includes("progress")) return "running";
  if (text.includes("接收") || text.includes("accepted") || text.includes("received") || text.includes("ready")) return "received";
  if (text.includes("下发") || text.includes("分配") || text.includes("dispatch") || text.includes("issued") || text.includes("sent") || text.includes("assigned")) return "dispatched";
  if (text.includes("创建") || text.includes("下单") || text.includes("created")) return "created";
  if (text.includes("offline") || text.includes("离线")) return "offline";
  if (text.includes("maintenance") || text.includes("debug") || text.includes("维护") || text.includes("调试")) return "maintenance";
  if (text.includes("paused") || text.includes("pause") || text.includes("暂停")) return "paused";
  if (text.includes("idle") || text.includes("空闲") || text.includes("等待") || text.includes("pending") || text.includes("wait")) return "idle";
  if (text.includes("预警") || text.includes("warn") || text.includes("alarm") || text.includes("不合格")) return "alarm";
  return "online";
}

function statusDisplayText(value) {
  const text = normalizeText(displayValue(value, ""));
  if (!text) return "";
  if (text === "online" || text.includes("在线")) return "online";
  if (text === "offline" || text.includes("离线")) return "offline";
  if (text === "idle" || text.includes("空闲")) return "idle";
  if (text === "busy" || text.includes("执行") || text.includes("running") || text.includes("processing")) return "busy";
  if (text === "error" || text.includes("异常") || text.includes("故障") || text.includes("fail")) return "error";
  if (text === "paused" || text.includes("暂停")) return "paused";
  return displayValue(value);
}

function rowType(row) {
  const explicitType = firstField(row, ["类型", "设备类型", "device_type", "deviceType", "type", "category"], "");
  if (explicitType) return explicitType;
  const table = normalizeText(row.__table || "");
  if (table.includes("agv")) return "AGV";
  if (table.includes("workstation") || table.includes("station")) return "Workstation";
  return "";
}

function deviceStatus(row, fallback = "offline") {
  return firstField(row, ["状", "status", "state", "运行状", "设备状", "工位状", "runtime_status", "runtimeStatus", "work_status", "workStatus", "transport_status", "transportStatus"], fallback);
}

function explicitDeviceConnectionState(row) {
  const value = firstField(row, ["connection_state", "connectionState", "连接状态", "在线状态"], "");
  const text = normalizeText(value);
  if (!text) return "";
  if (text.includes("online") || text.includes("在线")) return "online";
  return "offline";
}

function deviceConnectionState(row) {
  return explicitDeviceConnectionState(row) || "offline";
}

function deviceRuntimeStatus(row) {
  if (deviceConnectionState(row) === "offline") return "";
  const value = firstField(row, ["runtime_status", "runtimeStatus", "work_status", "workStatus", "运行状态", "设备运行状态", "status", "state"], "");
  const text = normalizeText(value);
  if (text.includes("busy") || text.includes("running") || text.includes("processing") || text.includes("执行")) return "busy";
  if (text.includes("error") || text.includes("fault") || text.includes("fail") || text.includes("异常") || text.includes("故障")) return "error";
  if (text.includes("paused") || text.includes("pause") || text.includes("暂停")) return "paused";
  if (text.includes("idle") || text.includes("空闲")) return "idle";
  return "idle";
}

function deviceDisplayStatus(row, fallback = "offline") {
  const connection = explicitDeviceConnectionState(row);
  if (connection === "offline") return "offline";
  if (connection === "online") return deviceRuntimeStatus(row) || "idle";
  return "offline";
}

function renderDeviceStateChips(row) {
  const connection = deviceConnectionState(row);
  const runtime = deviceRuntimeStatus(row);
  if (connection === "offline") {
    return `<span class="status-chip connection offline">${escapeHtml(statusDisplayText(connection))}</span>`;
  }
  return `
    <span class="status-chip runtime ${statusClass(runtime || "idle")}">${escapeHtml(statusDisplayText(runtime || "idle"))}</span>
  `;
}

function agvTaskId(row) {
  return firstField(row, ["运输任务", "transport_task_id", "transportTaskId", "current_transport_task_id", "currentTransportTaskId", "task_id", "taskId", "当前任务", "当前运输任务"], "");
}

function transportFromDevice(row) {
  return firstField(row, ["起点设备", "from_device", "fromDevice", "source_device", "sourceDevice", "from_name", "fromName"], "-");
}

function transportToDevice(row) {
  return firstField(row, ["目标设备", "to_device", "toDevice", "target_device", "targetDevice", "to_name", "toName"], "-");
}

function isWorkstationRow(row) {
  const text = normalizeText(`${rowText(row)} ${rowType(row)}`);
  return text.includes("工作") || text.includes("工站") || text.includes("workstation") || text.includes("station") || text.includes("scara") || text.includes("cobot");
}

function isAgvRow(row) {
  const text = normalizeText(`${rowText(row)} ${rowType(row)}`);
  return text.includes("agv") || text.includes("小车") || text.includes("运输");
}

function normalizeDeviceStatusKey(value) {
  const text = String(value ?? "").trim();
  if (!text) return "";
  return normalizeText(text.replace(/^(?:device|workstation|station|warehouse|agv)[:：]/i, "").trim());
}

function canonicalDeviceStatusKey(row) {
  const titleKey = normalizeDeviceStatusKey(deviceTitle(row));
  if (DEVICE_STATUS_NAME_ALIASES.has(titleKey)) return normalizeDeviceStatusKey(DEVICE_STATUS_NAME_ALIASES.get(titleKey));
  const identityKey = normalizeDeviceStatusKey(deviceIdentity(row));
  if (DEVICE_STATUS_NAME_ALIASES.has(identityKey)) return normalizeDeviceStatusKey(DEVICE_STATUS_NAME_ALIASES.get(identityKey));
  return identityKey || titleKey;
}

function canonicalDeviceStatusId(key) {
  return /^dev\d+$/i.test(key) ? key.toUpperCase() : key;
}

function isTechnicalDeviceTitle(row) {
  const titleKey = normalizeDeviceStatusKey(deviceTitle(row));
  const identityKey = normalizeDeviceStatusKey(deviceIdentity(row));
  return !titleKey || titleKey === identityKey || /^dev\d+$/i.test(titleKey);
}

function mergeDeviceStatusRows(existing, next, key) {
  const existingTitle = deviceTitle(existing);
  const nextTitle = deviceTitle(next);
  const preferNextTitle = isTechnicalDeviceTitle(existing) && !isTechnicalDeviceTitle(next);
  const merged = { ...existing, ...next };
  const canonicalId = canonicalDeviceStatusId(key);
  const tables = [existing.__table, next.__table].filter(Boolean);
  merged.__table = Array.from(new Set(tables)).join(" / ");
  merged.device_id = canonicalId;
  if (preferNextTitle) {
    merged.device_name = nextTitle;
  } else if (!merged.device_name && existingTitle && !isTechnicalDeviceTitle(existing)) {
    merged.device_name = existingTitle;
  }
  return merged;
}

function autoDeviceStatusAliases(rows) {
  const technicalDevices = [];
  const namedProductionDevices = [];
  rows.forEach((row, index) => {
    const key = canonicalDeviceStatusKey(row);
    const subtype = deviceSubtype(row);
    const isNamedProductionDevice = !isTechnicalDeviceTitle(row)
      && (subtype === "warehouse" || subtype === "workstation" || isWorkstationRow(row));
    if (isTechnicalDeviceTitle(row) && /^dev\d+$/i.test(key) && !isAgvRow(row)) {
      technicalDevices.push({ key, index });
    } else if (isNamedProductionDevice) {
      namedProductionDevices.push({ key, index });
    }
  });

  const aliases = new Map();
  technicalDevices
    .sort((left, right) => {
      const leftNumber = Number(left.key.match(/\d+/)?.[0] || left.index);
      const rightNumber = Number(right.key.match(/\d+/)?.[0] || right.index);
      return leftNumber - rightNumber;
    })
    .slice(0, namedProductionDevices.length)
    .forEach((device, index) => {
      const named = namedProductionDevices[index];
      if (named?.key) aliases.set(named.key, device.key);
    });
  return aliases;
}

function mergeDeviceStatusList(rows) {
  const merged = new Map();
  rows.forEach((row, index) => {
    const key = normalizeDeviceStatusKey(deviceIdentity(row)) || `row:${index}`;
    const existing = merged.get(key);
    merged.set(key, existing ? mergeDeviceStatusRows(existing, row, key) : { ...row, device_id: canonicalDeviceStatusId(key) });
  });
  return Array.from(merged.values());
}

function deviceIdentity(row) {
  return firstField(row, ["设备编号", "AGV编号", "工站编号", "工作站编号", "deviceCode", "device_code", "device_id", "deviceId", "workstation_code", "workstationCode", "workstation_id", "workstationId", "station_code", "stationCode", "station_id", "stationId", "agv_id", "agvId", "code"], "");
}

function deviceTitle(row) {
  return firstField(row, ["设备名称", "设备", "AGV名称", "小车名称", "工站名称", "工作站名称", "工作站名", "device_name", "deviceName", "workstation_name", "workstationName", "station_name", "stationName", "agv_name", "agvName", "name"], deviceIdentity(row) || row.__table);
}

function workOrderIdentity(row) {
  return firstField(row, ["工单编号", "work_order_id", "workOrderId", "task_id", "taskId", "id", "code"], "");
}

function workOrderTitle(row) {
  return firstField(row, ["工单名称", "work_order_name", "workOrderName", "title", "name", "阶段", "stage"], workOrderIdentity(row) || row.__table);
}

function assignedDeviceText(row) {
  return firstField(row, [
    "执行设备",
    "执行工站",
    "运输工站",
    "assigned_device_name",
    "assignedDeviceName",
    "assigned_device_id",
    "assignedDeviceId",
    "device_name",
    "deviceName",
    "device_id",
    "deviceId",
    "workstation",
    "station",
  ], "");
}

function currentWorkOrderId(row) {
  return firstField(row, ["当前工单编号", "执行工单编号", "current_work_order_id", "currentWorkOrderId", "work_order_id", "workOrderId", "task_id", "taskId"], "");
}

function activeDeviceCurrentWorkOrderId(row) {
  const connection = deviceConnectionState(row);
  const runtime = normalizeText(deviceRuntimeStatus(row));
  if (connection === "offline" || runtime === "idle" || runtime === "空闲") return "";
  return currentWorkOrderId(row);
}

function findWorkOrderForDevice(device, workOrders) {
  const currentId = normalizeText(activeDeviceCurrentWorkOrderId(device));
  const deviceId = normalizeText(deviceIdentity(device));
  const title = normalizeText(deviceTitle(device));

  return workOrders.find((order) => {
    const orderId = normalizeText(workOrderIdentity(order));
    const assigned = normalizeText(assignedDeviceText(order));
    return (currentId && orderId && currentId.includes(orderId)) || (assigned && ((deviceId && assigned.includes(deviceId)) || (title && assigned.includes(title))));
  });
}

function explicitTransportTaskId(row) {
  return firstField(row, [
    "运输编号",
    "transport_id",
    "transportId",
    "transport_task_id",
    "transportTaskId",
    "current_transport_task_id",
    "currentTransportTaskId",
    "工单编号",
    "work_order_id",
    "workOrderId",
    "task_id",
    "taskId",
  ], "");
}

function transportTaskInfo(row, options = {}) {
  const text = normalizeText(rowText(row));
  const taskType = firstField(row, ["task_type", "taskType", "任务类型", "运输类型", "stage", "阶段"], "");
  const explicitTaskId = explicitTransportTaskId(row);
  const isTransportType = text.includes("运输") || normalizeText(taskType).includes("transport");
  if (!explicitTaskId && !isTransportType) return null;
  if (!options.allowDeviceRecord && !isTransportType && isAgvRow(row)) return null;

  return {
    title: firstField(row, ["运输编号", "transport_id", "transportId"], "") || workOrderTitle(row),
    status: firstField(row, ["任务状态", "工单状", "任务状", "运输状", "status", "state"], "运输"),
    agv: firstField(row, ["AGV编号", "agv_id", "agvId", "小车编号", "vehicle_id", "vehicleId"], "AGV"),
    from: firstField(row, ["起始工站/仓库", "起点设备", "from_device", "fromDevice", "source_device", "sourceDevice", "from_name", "fromName"], "-"),
    to: firstField(row, ["目标工站/仓库", "目标设备", "to_device", "toDevice", "target_device", "targetDevice", "to_name", "toName"], "-"),
    workOrder: firstField(row, ["工单编号", "work_order_id", "workOrderId"], "") || explicitTaskId || "-",
    table: row.__table,
  };
}

function renderDeviceStatusPage() {
  const rows = mergeDeviceStatusList(deviceRowsFromMysql());
  const workOrders = entityItems("work_order")
    .filter(isActiveOntologyWorkOrder)
    .map((item) => ({ ...item.properties, ...item.runtime, ...item, __table: Array.isArray(item.source) ? item.source.join(" / ") : item.source }));
  const workstationRows = rows.filter(isWorkstationRow);
  const workstationTasks = workstationRows.map((device) => {
    const matchedOrder = findWorkOrderForDevice(device, workOrders);
    return { device, order: matchedOrder, currentId: activeDeviceCurrentWorkOrderId(device) };
  });
  const agvRows = rows.filter(isAgvRow);
  const agvTasks = [
    ...activeAgvTaskRows().map((row) => ({ ...row, __table: "order.work_orders" })),
    ...workOrders,
  ].map(transportTaskInfo).filter(Boolean);
  const onlineCount = rows.filter((row) => deviceConnectionState(row) === "online").length;

  return `
    <section class="page-grid">
      <article class="panel-card full-width">
        <div class="panel-header panel-header-spread">
          <div>
            <h2>获取设备状态信息</h2>
            <p class="panel-muted">查询当前产线设备运行状态、工站执行工单和 AGV 小车运输任务</p>
          </div>
          <div class="metric-group">${renderMetricPills([`${rows.length} 台设备`, `${onlineCount} 台在线`, `${agvTasks.length} 个 AGV 任务`, statusBadgeText()])}</div>
        </div>

        <div class="tool-section">
          <div class="panel-header compact-header">
            <div>
              <h3>产线设备运行状态</h3>
              <p class="panel-muted">来自设备数据库的实时设备记录</p>
            </div>
          </div>
          <div class="entity-grid entity-grid-3">
            ${rows.length
              ? rows
            .map((row) => {
              const title = deviceTitle(row);
              const connection = deviceConnectionState(row);
              const runtime = deviceRuntimeStatus(row);
              return `
                <article class="entity-card">
                  <div class="entity-card-head">
                    <div>
                      <h3>${escapeHtml(title)}</h3>
                      <p class="panel-muted">${escapeHtml(rowType(row) || row.__table)}</p>
                    </div>
                    <div class="status-chip-set">${renderDeviceStateChips(row)}</div>
                  </div>
                  <div class="entity-fields">
                    <span>设备编号</span><span>${escapeHtml(deviceIdentity(row) || "-")}</span>
                    <span>连接状态</span><span>${escapeHtml(statusDisplayText(connection))}</span>
                    ${runtime ? `<span>运行状态</span><span>${escapeHtml(statusDisplayText(runtime))}</span>` : ""}
                    <span>数据</span><span>${escapeHtml(row.__table)}</span>
                  </div>
                </article>
              `;
            })
            .join("")
              : "<article class='entity-card'><h3>暂无设备运行数据</h3><p class='panel-muted'>请检查 /api/digital-twin/devices。</p></article>"}
          </div>
        </div>

        <div class="panel-divider"></div>
        <div class="tool-section">
          <div class="panel-header compact-header">
            <div>
              <h3>工站当前执行工单</h3>
              <p class="panel-muted">优先读取设备当前工单字段，并关联工单数据</p>
            </div>
          </div>
          <div class="entity-grid entity-grid-2">
            ${workstationTasks.length
              ? workstationTasks.map(({ device, order, currentId }) => {
                const status = order ? firstField(order, ["工单状", "status", "state"], "执行") : deviceStatus(device, "未确认");
                return `
                  <article class="entity-card">
                    <div class="entity-card-head">
                      <div>
                        <h3>${escapeHtml(deviceTitle(device))}</h3>
                        <p class="panel-muted">${escapeHtml(deviceIdentity(device) || device.__table)}</p>
                      </div>
                      <span class="status-chip ${statusClass(status)}">${escapeHtml(status)}</span>
                    </div>
                    <div class="entity-fields">
                      <span>设备状态</span><span>${escapeHtml(statusDisplayText(deviceConnectionState(device)))}${deviceRuntimeStatus(device) ? ` / ${escapeHtml(statusDisplayText(deviceRuntimeStatus(device)))}` : ""}</span>
                      <span>当前工单</span><span>${escapeHtml(order ? workOrderTitle(order) : currentId || "")}</span>
                      <span>工单编号</span><span>${escapeHtml(order ? workOrderIdentity(order) || "-" : currentId || "-")}</span>
                      <span>执行设备</span><span>${escapeHtml(order ? assignedDeviceText(order) || deviceTitle(device) : deviceTitle(device))}</span>
                    </div>
                  </article>
                `;
              }).join("")
              : "<article class='entity-card'><h3>暂无工站执行记录</h3><p class='panel-muted'>未从 device 数据识别到工站或当前工单字段</p></article>"}
          </div>
        </div>

        <div class="panel-divider"></div>
        <div class="tool-section">
          <div class="panel-header compact-header">
            <div>
              <h3>AGV 小车运输任务</h3>
              <p class="panel-muted">简要展示 AGV 运输任务；完整运输任务视图请在 Ontology / Devices 中点击 AGV 实例查看。</p>
            </div>
          </div>
          <div class="entity-grid entity-grid-2">
            ${agvTasks.length
              ? agvTasks.map((task) => `
                <article class="entity-card">
                  <div class="entity-card-head">
                    <div>
                      <h3>${escapeHtml(task.title)}</h3>
                      <p class="panel-muted">${escapeHtml(task.workOrder)}</p>
                    </div>
                    <span class="status-chip ${statusClass(task.status)}">${escapeHtml(task.status)}</span>
                  </div>
                  <div class="entity-fields">
                    <span>AGV 小车</span><span>${escapeHtml(task.agv)}</span>
                    <span>起点设备</span><span>${escapeHtml(task.from)}</span>
                    <span>目标设备</span><span>${escapeHtml(task.to)}</span>
                    <span>数据来源</span><span>${escapeHtml(task.table || "-")}</span>
                  </div>
                </article>
              `).join("")
              : agvRows.length
                ? agvRows.map((row) => {
                  return `
                    <article class="entity-card">
                      <div class="entity-card-head">
                        <div>
                          <h3>${escapeHtml(deviceTitle(row))}</h3>
                          <p class="panel-muted">${escapeHtml(deviceIdentity(row) || row.__table)}</p>
                        </div>
                        <div class="status-chip-set">${renderDeviceStateChips(row)}</div>
                      </div>
                      <div class="entity-fields">
                        <span>当前任务</span><span>${escapeHtml(agvTaskId(row) || activeDeviceCurrentWorkOrderId(row) || "暂无运输任务")}</span>
                        <span>数据</span><span>${escapeHtml(row.__table)}</span>
                      </div>
                    </article>
                  `;
                }).join("")
                : "<article class='entity-card'><h3>暂无 AGV 运输数据</h3><p class='panel-muted'>未找到 AGV 设备或运输工单。</p></article>"}
          </div>
        </div>
      </article>
    </section>
  `;
}

function reportDate(value) {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "-";
  return date.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function reasoningRuleCards() {
  const liveRules = inferenceRuleRows().map((row) => ({
    id: row.id,
    title: row.name,
    summary: row.description || "后端 reasoning_service 返回的推理规则。",
    condition: row.rule?.condition || row.rule?.when || `${row.sourceClass} -> ${row.targetClass}`,
    conclusion: row.rule?.conclusion || row.description || "供 Agent 生成推理说明和分析结论时参考。",
    source: row.sourceType || "reasoning_service",
    status: "Live Rule",
  }));
  if (liveRules.length) return liveRules;
  return REASONING_RULE_TEMPLATES.map((item) => ({ ...item, status: "Template" }));
}

function renderReasoningRuleCard(item) {
  return `
    <article class="report-card template">
      <div class="report-card-top">
        ${typeIconHtml("reasoning", item.title)}
        <div>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.summary || item.id || "-")}</p>
        </div>
      </div>
      <div class="entity-fields">
        <span>触发条件</span><span>${escapeHtml(item.condition || "-")}</span>
        <span>推理结论</span><span>${escapeHtml(item.conclusion || "-")}</span>
        <span>规则来源</span><span>${escapeHtml(item.source || "reasoning_service")}</span>
      </div>
      <div class="report-card-foot">
        <span class="meta-pill">${escapeHtml(item.id || "RULE")}</span>
        <span class="status-chip idle">${escapeHtml(item.status || "Template")}</span>
      </div>
    </article>
  `;
}

function renderReasoningRulesPage() {
  const rules = reasoningRuleCards();
  const persisted = Array.isArray(state.data?.reasoningResults) ? state.data.reasoningResults.length : 0;
  const violations = Number(state.data?.inference?.summary?.violation_count || state.data?.inference?.violations?.length || 0);
  return `
    <section class="page-grid report-management-page reasoning-rules-page">
      <article class="panel-card full-width report-management-panel">
        <div class="report-toolbar">
          <div>
            <p class="panel-eyebrow">Tools / Agent Reference</p>
            <h2>Reasoning Rules</h2>
            <p class="panel-muted">集中展示 ontology 推理规则，作为产线管控 Agent 解释工单拆分、设备匹配、AGV 运输和异常判断的参考模板。</p>
          </div>
          <div class="metric-group">${renderMetricPills([`${rules.length} 条规则`, `${persisted} 条落库结果`, `${violations} 条违规`, statusBadgeText()])}</div>
        </div>
        <div class="report-grid">
          ${rules.map(renderReasoningRuleCard).join("")}
        </div>
      </article>
    </section>
  `;
}

function builtInReportCards() {
  return [
    ...REPORT_TEMPLATES.map((item) => ({
      id: item.id,
      title: item.title,
      summary: `报告模板：${item.sections.join("、")}。图表包含 ${item.charts.join("、")}。`,
      status: "Template",
      kind: "template",
      format: item.format,
      createdAt: "2026-05-15T00:00:00",
      skillPath: item.skillPath || "",
    })),
    ...GENERATED_REPORTS.map((item) => ({
      ...item,
      kind: item.kind || "generated",
      status: item.status || "Active",
    })),
  ];
}

function allReportCards() {
  const seen = new Set();
  return [...state.reports, ...builtInReportCards()].filter((item) => {
    const id = item.id || item.title;
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

function selectedReportCard() {
  if (!state.selectedReportId) return null;
  return allReportCards().find((item) => item.id === state.selectedReportId) || null;
}

function reportContent(item) {
  if (!item) return "";
  if (item.content) return item.content;
  if (item.id === "RPT-PRODUCTION-ANALYSIS-001" || item.id?.startsWith("RPT-GEN-")) {
    return buildProductionAnalysisReportText();
  }
  return [
    `# ${item.title}`,
    "",
    item.summary || "暂无报告正文。",
    "",
    item.skillPath ? `Skill：${item.skillPath}` : "",
    item.filePath ? `文件：${item.filePath}` : "",
  ].filter(Boolean).join("\n");
}

function markdownTableHtml(lines, startIndex) {
  const rows = [];
  let index = startIndex;
  while (index < lines.length && /^\s*\|.*\|\s*$/.test(lines[index])) {
    const cells = lines[index].trim().slice(1, -1).split("|").map((cell) => cell.trim());
    if (!cells.every((cell) => /^:?-{3,}:?$/.test(cell))) rows.push(cells);
    index += 1;
  }
  if (!rows.length) return { html: "", nextIndex: index };
  const [head, ...body] = rows;
  return {
    nextIndex: index,
    html: `
      <table>
        <thead><tr>${head.map((cell) => `<th>${escapeHtml(cell)}</th>`).join("")}</tr></thead>
        <tbody>${body.map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>`).join("")}</tbody>
      </table>
    `,
  };
}

function markdownToReportHtml(markdown) {
  const lines = String(markdown || "").split(/\r?\n/);
  const blocks = [];
  let paragraph = [];
  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push(`<p>${escapeHtml(paragraph.join(" "))}</p>`);
    paragraph = [];
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      flushParagraph();
      const table = markdownTableHtml(lines, index);
      if (table.html) blocks.push(table.html);
      index = table.nextIndex - 1;
      continue;
    }
    if (trimmed.startsWith("### ")) {
      flushParagraph();
      blocks.push(`<h4>${escapeHtml(trimmed.slice(4))}</h4>`);
      continue;
    }
    if (trimmed.startsWith("## ")) {
      flushParagraph();
      blocks.push(`<h3>${escapeHtml(trimmed.slice(3))}</h3>`);
      continue;
    }
    if (trimmed.startsWith("# ")) {
      flushParagraph();
      blocks.push(`<h2>${escapeHtml(trimmed.slice(2))}</h2>`);
      continue;
    }
    if (trimmed.startsWith("- ")) {
      flushParagraph();
      const items = [];
      while (index < lines.length && lines[index].trim().startsWith("- ")) {
        items.push(`<li>${escapeHtml(lines[index].trim().slice(2))}</li>`);
        index += 1;
      }
      blocks.push(`<ul>${items.join("")}</ul>`);
      index -= 1;
      continue;
    }
    paragraph.push(trimmed);
  }
  flushParagraph();
  return blocks.join("");
}

function isProductionAnalysisReport(report) {
  const text = normalizeText(`${report?.id || ""} ${report?.title || ""} ${report?.skillPath || ""}`);
  return text.includes("productionanalysis") || text.includes("产品生产分析") || text.includes("rptgen");
}

function reportChartPalette(index) {
  return ["#22d3ee", "#34d399", "#f59e0b", "#fb7185", "#8b5cf6", "#60a5fa"][index % 6];
}

function renderReportMetricCards(analysis) {
  const totals = analysis.batches.map((item) => item.totalDuration).filter((value) => Number.isFinite(value));
  const avg = totals.length ? totals.reduce((sum, value) => sum + value, 0) / totals.length : 0;
  const max = totals.length ? Math.max(...totals) : 0;
  const bottleneck = [...analysis.processStats].sort((a, b) => b.avg - a.avg)[0];
  return `
    <div class="report-metric-strip">
      <span><strong>${analysis.batches.length}</strong><em>订单/批次</em></span>
      <span><strong>${formatDuration(avg)}</strong><em>平均总用时</em></span>
      <span><strong>${formatDuration(max)}</strong><em>最长总用时</em></span>
      <span><strong>${escapeHtml(bottleneck?.processName || "-")}</strong><em>瓶颈工序</em></span>
    </div>
  `;
}

function renderReportStackedBars(analysis) {
  if (!analysis.batches.length) return `<div class="load-curve-empty">暂无批次用时数据</div>`;
  const max = Math.max(...analysis.batches.map((item) => item.totalDuration), 1);
  return `
    <div class="report-stacked-bars">
      ${analysis.batches.map((batch) => `
        <div class="report-stacked-row">
          <span>${escapeHtml(batch.id)}</span>
          <div class="report-stacked-track" title="${escapeHtml(formatDuration(batch.totalDuration))}">
            ${(batch.processDurations || []).map((item, index) => `
              <i style="width:${Math.max(4, (item.duration / max) * 100)}%;background:${reportChartPalette(index)}" title="${escapeHtml(`${item.processName} ${formatDuration(item.duration)}`)}"></i>
            `).join("")}
          </div>
          <strong>${escapeHtml(formatDuration(batch.totalDuration))}</strong>
        </div>
      `).join("")}
    </div>
  `;
}

function renderReportProcessBars(analysis) {
  if (!analysis.processStats.length) return `<div class="load-curve-empty">暂无工序用时统计</div>`;
  const max = Math.max(...analysis.processStats.map((item) => item.avg), 1);
  return `
    <div class="report-process-bars">
      ${analysis.processStats.map((item, index) => `
        <div class="report-process-bar">
          <span>${escapeHtml(item.processName)}</span>
          <div><i style="width:${Math.max(6, (item.avg / max) * 100)}%;background:${reportChartPalette(index)}"></i></div>
          <strong>${escapeHtml(formatDuration(item.avg))}</strong>
        </div>
      `).join("")}
    </div>
  `;
}

function renderReportShareDonut(analysis) {
  const total = analysis.processStats.reduce((sum, item) => sum + item.avg, 0);
  if (!total) return `<div class="load-curve-empty">暂无占比数据</div>`;
  let cursor = 0;
  const stops = analysis.processStats.map((item, index) => {
    const start = cursor;
    cursor += (item.avg / total) * 100;
    return `${reportChartPalette(index)} ${start.toFixed(2)}% ${cursor.toFixed(2)}%`;
  });
  return `
    <div class="report-donut-wrap">
      <div class="report-donut" style="background:conic-gradient(${stops.join(",")})"><span>占比</span></div>
      <div class="report-donut-legend">
        ${analysis.processStats.map((item, index) => `
          <span><i style="background:${reportChartPalette(index)}"></i>${escapeHtml(item.processName)} ${Math.round((item.avg / total) * 100)}%</span>
        `).join("")}
      </div>
    </div>
  `;
}

function renderReportGantt(analysis) {
  const batch = [...analysis.batches].sort((a, b) => b.totalDuration - a.totalDuration)[0];
  if (!batch || !batch.processDurations.length) return `<div class="load-curve-empty">暂无单次生产时间线</div>`;
  const orderStart = parseTimeMs(batch.start);
  const orderEnd = parseTimeMs(batch.end);
  const timedItems = batch.processDurations.map((item) => ({
    ...item,
    startMs: parseTimeMs(item.start),
    endMs: parseTimeMs(item.end),
  }));
  const hasClock = timedItems.every((item) => item.startMs !== null && item.endMs !== null);
  const timelineStart = hasClock ? Math.min(orderStart ?? timedItems[0].startMs, ...timedItems.map((item) => item.startMs)) : 0;
  const timelineEnd = hasClock ? Math.max(orderEnd ?? timedItems.at(-1).endMs, ...timedItems.map((item) => item.endMs)) : batch.totalDuration;
  let cursor = 0;

  return `
    <div class="report-gantt">
      <div class="report-gantt-caption">${escapeHtml(batch.id)} · ${escapeHtml(formatDuration(batch.totalDuration))}</div>
      ${timedItems.map((item, index) => {
        const start = hasClock ? item.startMs : cursor;
        const end = hasClock ? item.endMs : cursor + item.duration;
        if (!hasClock) cursor = end;
        const span = Math.max(1, timelineEnd - timelineStart);
        const left = Math.max(0, ((start - timelineStart) / span) * 100);
        const width = Math.max(5, ((end - start) / span) * 100);
        return `
          <div class="report-gantt-row">
            <span>${escapeHtml(item.processName)}</span>
            <div class="report-gantt-track">
              <i style="left:${left}%;width:${width}%;background:${reportChartPalette(index)}">${escapeHtml(formatDuration(item.duration))}</i>
            </div>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderReportVisuals(report) {
  if (!isProductionAnalysisReport(report)) return "";
  const analysis = buildProductionAnalysis();
  return `
    <section class="report-visual-section">
      <div class="report-visual-head">
        <div>
          <p class="panel-eyebrow">Visual Analysis</p>
          <h3>分析图表</h3>
        </div>
      </div>
      ${renderReportMetricCards(analysis)}
      <div class="report-visual-grid">
        <article>
          <h4>产品生产用时分布</h4>
          ${renderReportStackedBars(analysis)}
        </article>
        <article>
          <h4>工序平均用时</h4>
          ${renderReportProcessBars(analysis)}
        </article>
        <article>
          <h4>单次生产甘特图</h4>
          ${renderReportGantt(analysis)}
        </article>
        <article>
          <h4>工序用时占比</h4>
          ${renderReportShareDonut(analysis)}
        </article>
      </div>
    </section>
  `;
}

function renderReportViewer() {
  const report = selectedReportCard();
  if (!report) return "";
  return `
    <div class="report-viewer-backdrop">
      <aside class="report-viewer" role="dialog" aria-modal="true" aria-label="报告内容查看">
        <div class="report-viewer-head">
          <div>
            <p class="panel-eyebrow">${escapeHtml(report.source || "Report")}</p>
            <h2>${escapeHtml(report.title)}</h2>
            <p class="panel-muted">${escapeHtml(reportDate(report.createdAt))} · ${escapeHtml(report.format || "Markdown")}</p>
          </div>
          <button class="toolbar-btn" type="button" data-report-close>关闭</button>
        </div>
        <div class="report-viewer-body">
          ${renderReportVisuals(report)}
          ${markdownToReportHtml(reportContent(report))}
        </div>
      </aside>
    </div>
  `;
}

function renderReportCard(item) {
  const isTemplate = item.kind === "template";
  const openAttr = isTemplate ? "" : `data-report-open="${escapeHtml(item.id)}"`;
  return `
    <article class="report-card ${isTemplate ? "template" : "generated clickable"}" ${openAttr}>
      <div class="report-card-top">
        ${typeIconHtml(isTemplate ? "class" : "report", item.title)}
        <div>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.summary || item.id || "-")}</p>
        </div>
      </div>
      <div class="report-card-meta">
        <span>${escapeHtml(reportDate(item.createdAt))}</span>
        <span>${escapeHtml(item.format || "Markdown")}</span>
        ${item.skillPath ? `<span>${escapeHtml(item.skillPath)}</span>` : ""}
      </div>
      <div class="report-card-foot">
        <span class="meta-pill">${escapeHtml(isTemplate ? "Template" : item.source || "AI Agent")}</span>
        <span class="status-chip ${isTemplate ? "idle" : "online"}">${escapeHtml(isTemplate ? item.status || "Template" : "查看")}</span>
      </div>
    </article>
  `;
}

function renderReportsPage() {
  const reports = allReportCards();
  return `
    <section class="page-grid report-management-page">
      <article class="panel-card full-width report-management-panel">
        <div class="report-toolbar">
          <div>
            <p class="panel-eyebrow">Data / Report Management</p>
            <h2>All Reports</h2>
          </div>
          <div class="report-toolbar-actions">
            <input class="search-input report-search" type="search" value="" placeholder="Search reports..." readonly />
            <span class="toolbar-btn">Templates</span>
          </div>
        </div>
        <div class="report-grid">
          ${reports.map(renderReportCard).join("")}
        </div>
      </article>
      ${renderReportViewer()}
      ${renderProductionAnalysisPanel()}
    </section>
  `;
}

function agentSuggestions() {
  return [
    "查看当前正在加工的订单",
    "生产一个立方堆，用红色蓝色绿色立方体",
    "检查一下设备的运行状态",
  ];
}

function agentQuickActions() {
  return [
    {
      label: "产品生产报告",
      prompt: "生成产品生产分析报告，包含生产用时分布、产品-工序拓扑和各工序用时分析",
      icon: "report",
    },
  ];
}

function renderAgentConsole() {
  const isOpen = state.agent.consoleOpen;
  return `
    <aside class="agent-console-overlay ${isOpen ? "open" : "collapsed"} ${state.sidebarCollapsed ? "sidebar-collapsed" : ""}" aria-label="产线管控 Agent 控制台">
      <div class="agent-console-shell">
        <button class="agent-console-tab" type="button" data-agent-console-toggle aria-expanded="${isOpen}">
          <div>
            <h2>产线管控Agent</h2>
          </div>
          <span class="status-chip ${state.agent.status === "error" ? "alarm" : state.agent.status === "busy" ? "idle" : "online"}">${agentStatusText()}</span>
          <b>${isOpen ? "收起" : "展开"}</b>
        </button>
        <div class="agent-console-panel">
          <section class="agent-console-chat">
            <button class="toolbar-btn agent-console-close" type="button" data-agent-console-toggle>关闭</button>
          <div class="agent-suggestion-row">
              ${agentSuggestions().map((item) => `<button class="suggestion-chip agent-suggestion" type="button" data-agent-prompt="${escapeHtml(item)}">${escapeHtml(item)}</button>`).join("")}
          </div>
          <div id="agent-chat-log" class="agent-chat-log ${state.agent.messages.length ? "" : "empty"}">${renderAgentMessagesHtml()}</div>
          <form id="agent-form" class="agent-form">
              <textarea id="agent-input" class="agent-input" rows="3" placeholder="示例：请概括当前 ontology 中的仓库、订单、产线和库存预警信息"></textarea>
            <div class="agent-actions">
              <button id="agent-send-btn" class="toolbar-btn primary" type="submit" ${state.agent.pending ? "disabled" : ""}>发送到 Agent</button>
              <button id="agent-stop-btn" class="toolbar-btn" type="button" ${state.agent.pending ? "" : "disabled"}>停止</button>
              <button id="agent-clear-btn" class="toolbar-btn" type="button">清空会话</button>
            </div>
          </form>
          <div class="agent-quick-actions">
            ${agentQuickActions().map((item) => `
              <button class="agent-quick-action agent-suggestion" type="button" data-agent-prompt="${escapeHtml(item.prompt)}">
                ${typeIconHtml(item.icon, item.label)}
                <span>${escapeHtml(item.label)}</span>
              </button>
            `).join("")}
          </div>
          </section>
        </div>
      </div>
    </aside>
  `;
}

function renderAgentPage() {
  return renderAgentConsole();
}

function ensureAgentConsoleRoot() {
  if (elements.agentConsoleRoot) return elements.agentConsoleRoot;
  const root = document.createElement("div");
  root.id = "agent-console-root";
  document.body.appendChild(root);
  elements.agentConsoleRoot = root;
  return root;
}

function renderAgentConsoleOverlay() {
  const root = ensureAgentConsoleRoot();
  root.innerHTML = renderAgentConsole();
  bindAgentEvents(root);
  renderAgentMessages();
}

function ensureThemeSwitcherRoot() {
  if (elements.themeSwitcherRoot) return elements.themeSwitcherRoot;
  const root = document.createElement("div");
  root.id = "theme-switcher-root";
  document.body.appendChild(root);
  elements.themeSwitcherRoot = root;
  return root;
}

function renderThemeSwitcher() {
  const root = ensureThemeSwitcherRoot();
  root.innerHTML = `
    <aside class="theme-switcher" aria-label="主题颜色配置">
      <span>主题颜色</span>
      <div class="theme-switcher-options">
        <button class="${state.theme === "dark" ? "active" : ""}" type="button" data-theme-value="dark" aria-pressed="${state.theme === "dark"}">黑色</button>
        <button class="${state.theme === "light" ? "active" : ""}" type="button" data-theme-value="light" aria-pressed="${state.theme === "light"}">白色</button>
      </div>
    </aside>
  `;
  root.querySelectorAll("[data-theme-value]").forEach((button) => {
    button.addEventListener("click", () => setTheme(button.dataset.themeValue || "dark"));
  });
}

function renderAgentMessagesHtml() {
  if (!state.agent.messages.length) {
    return "";
  }

  return state.agent.messages
    .map((message) => `
      <article class="agent-message ${message.role}${message.error ? " error" : ""}">
        <span class="agent-role">${message.role === "user" ? "User" : "Agent"}</span>
        <p>${escapeHtml(message.content || (state.agent.pending && message.role === "assistant" ? "Thinking..." : ""))}</p>
      </article>
    `)
    .join("");
}

function renderAgentMessages() {
  const log = document.querySelector("#agent-chat-log");
  if (!log) return;
  log.classList.toggle("empty", !state.agent.messages.length);
  log.innerHTML = renderAgentMessagesHtml();
  log.scrollTop = log.scrollHeight;
}

function renderPage() {
  if (!state.ontology) {
    state.ontology = buildFallbackOntology();
  }

  let html = "";
  if (state.route === "/ontology/classes") {
    html = renderClassesPage();
  } else if (state.route === "/ontology/relations") {
    html = renderRelationsPage();
  } else if (state.route === "/ontology/devices") {
    html = renderEntityListPage("device");
  } else if (state.route === "/ontology/orders") {
    html = renderOrderTreePage();
  } else if (state.route === "/ontology/work-orders") {
    html = renderOrderTreePage();
  } else if (state.route === "/ontology/materials") {
    html = renderEntityListPage("material");
  } else if (state.route === "/ontology/products") {
    html = renderEntityListPage("product");
  } else if (state.route === "/ontology/processes") {
    html = renderEntityListPage("process");
  } else if (state.route === "/ontology/crafts") {
    html = renderEntityListPage("craft");
  } else if (state.route === "/tools/search") {
    html = renderSearchPage();
  } else if (state.route === "/tools/reasoning-rules") {
    html = renderReasoningRulesPage();
  } else if (state.route === "/tools/reports") {
    html = renderReportsPage();
  } else if (state.route === "/data/orders") {
    html = renderDataOrdersPage();
  } else if (state.route === "/data/devices") {
    html = renderDataDevicesPage();
  } else if (state.route === "/data/quality") {
    html = renderDataQualityPage();
  } else if (state.route === "/agent/console") {
    state.agent.consoleOpen = true;
    html = renderEntityListPage("device");
  } else {
    html = renderClassesPage();
  }

  elements.appRoot.innerHTML = html;
  updateActiveNavigation();
  renderAgentConsoleOverlay();

  elements.appRoot.querySelectorAll("[data-entity-type][data-entity-id]").forEach((element) => {
    element.addEventListener("click", async () => {
      await openEntity(element.dataset.entityType, element.dataset.entityId);
    });
  });

  elements.appRoot.querySelectorAll("[data-class-node-id]").forEach((element) => {
    element.addEventListener("click", () => {
      if (element.dataset.dragged === "true") {
        element.dataset.dragged = "";
        return;
      }
      openClassTopologyModule(element.dataset.classNodeId);
    });
  });

  elements.appRoot.querySelectorAll("[data-topology-node-id]").forEach((element) => {
    element.addEventListener("click", () => {
      if (element.dataset.dragged === "true") {
        element.dataset.dragged = "";
        return;
      }
      openTopologyNode(element.dataset.topologyNodeId);
    });
  });

  elements.appRoot.querySelectorAll("[data-topology-select]").forEach((select) => {
    select.addEventListener("change", () => {
      state.classTopologyMode = select.value || "production";
      state.classViewMode = state.classTopologyMode === "production" ? "topology" : "list";
      state.classInstanceViewMode = "list";
      state.selectedEntity = null;
      renderPage();
    });
  });

  elements.appRoot.querySelectorAll("[data-class-view-select]").forEach((select) => {
    select.addEventListener("change", () => {
      state.classViewMode = select.value || "topology";
      state.classInstanceViewMode = "list";
      renderPage();
    });
  });

  elements.appRoot.querySelectorAll("[data-topology-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.classTopologyMode = button.dataset.topologyMode || "production";
      state.classViewMode = state.classTopologyMode === "production" ? "topology" : "list";
      state.classInstanceViewMode = "list";
      state.selectedEntity = null;
      renderPage();
    });
  });

  elements.appRoot.querySelectorAll("[data-product-tree-toggle]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const productId = button.dataset.productTreeToggle;
      if (!productId) return;
      state.productProcessExpanded[productId] = state.productProcessExpanded[productId] !== false ? false : true;
      renderPage();
    });
  });

  elements.appRoot.querySelectorAll("[data-order-tree-toggle]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const orderId = button.dataset.orderTreeToggle;
      if (!orderId) return;
      state.orderTreeExpanded[orderId] = state.orderTreeExpanded[orderId] !== false ? false : true;
      renderPage();
    });
  });

  elements.appRoot.querySelectorAll("[data-report-open]").forEach((card) => {
    card.addEventListener("click", () => {
      state.selectedReportId = card.dataset.reportOpen || "";
      renderPage();
    });
  });

  elements.appRoot.querySelectorAll("[data-report-close]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedReportId = "";
      renderPage();
    });
  });

  elements.appRoot.querySelectorAll("[data-device-history-device]").forEach((button) => {
    button.addEventListener("click", () => {
      state.dataDeviceHistory.selectedDeviceId = button.dataset.deviceHistoryDevice || "";
      state.dataDeviceHistory.selectedRunId = "";
      renderPage();
    });
  });

  elements.appRoot.querySelectorAll("[data-device-history-run]").forEach((button) => {
    button.addEventListener("click", () => {
      state.dataDeviceHistory.selectedRunId = button.dataset.deviceHistoryRun || "";
      renderPage();
    });
  });

  elements.appRoot.querySelectorAll("[data-device-tree-toggle]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const deviceId = button.dataset.deviceTreeToggle;
      if (!deviceId) return;
      state.deviceTreeExpanded[deviceId] = state.deviceTreeExpanded[deviceId] !== false ? false : true;
      renderPage();
    });
  });

  elements.appRoot.querySelectorAll("[data-instance-view]").forEach((button) => {
    button.addEventListener("click", () => {
      state.classInstanceViewMode = button.dataset.instanceView || "list";
      renderPage();
    });
  });

  elements.appRoot.querySelectorAll(".relation-clickable").forEach((element) => {
    element.addEventListener("click", async () => {
      const targetType = element.dataset.targetType;
      const targetId = element.dataset.targetId;
      if (targetType && targetId) {
        await openEntity(targetType, targetId);
      }
    });
  });

  bindTopologyViewport();
  bindClassNodeDragging();


  elements.appRoot.querySelectorAll("[data-class-view]").forEach((button) => {
    button.addEventListener("click", () => {
      state.classViewMode = button.dataset.classView || "topology";
      renderPage();
    });
  });

  elements.appRoot.querySelectorAll("[data-class-select]").forEach((button) => {
    button.addEventListener("click", () => selectClassRow(button.dataset.classSelect));
  });

  elements.appRoot.querySelectorAll("[data-class-action]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const action = button.dataset.classAction;
      const classId = button.dataset.classId;
      if (action === "new") createClass();
      if (action === "toggle-recycle") {
        state.classRecycleOpen = !state.classRecycleOpen;
        renderPage();
      }
      if (action === "rename" && classId) renameClass(classId);
      if (action === "delete" && classId) deleteClass(classId);
      if (action === "restore" && classId) restoreClass(classId);
    });
  });

  elements.appRoot.querySelectorAll("[data-relation-action]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const action = button.dataset.relationAction;
      const relationIdValue = button.dataset.relationId;
      if (action === "new") createRelation();
      if (action === "rename" && relationIdValue) renameRelation(relationIdValue);
      if (action === "delete" && relationIdValue) deleteRelation(relationIdValue);
    });
  });

  elements.appRoot.querySelectorAll("[data-ontology-search]").forEach((input) => {
    input.addEventListener("input", () => {
      const key = input.dataset.ontologySearch;
      state.ontologySearch[key] = input.value;
      renderPage();
      const nextInput = elements.appRoot.querySelector(`[data-ontology-search="${key}"]`);
      if (nextInput) {
        nextInput.focus();
        nextInput.setSelectionRange(nextInput.value.length, nextInput.value.length);
      }
    });
  });

  const searchForm = elements.appRoot.querySelector("[data-global-search-form]");
  searchForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    addGlobalSearchHistory(filteredGlobalSearchRecords(buildGlobalSearchRecords()).length);
    renderPage();
  });

  elements.appRoot.querySelectorAll("[data-global-search-query]").forEach((input) => {
    input.addEventListener("input", () => {
      state.globalSearch.query = input.value;
      renderPage();
      const nextInput = elements.appRoot.querySelector("[data-global-search-query]");
      if (nextInput) {
        nextInput.focus();
        nextInput.setSelectionRange(nextInput.value.length, nextInput.value.length);
      }
    });
  });

  elements.appRoot.querySelectorAll("[data-global-search-filter]").forEach((select) => {
    select.addEventListener("change", () => {
      const key = select.dataset.globalSearchFilter;
      if (key && Object.prototype.hasOwnProperty.call(state.globalSearch, key)) {
        state.globalSearch[key] = select.value || "all";
        renderPage();
      }
    });
  });

  elements.appRoot.querySelectorAll("[data-global-search-refresh]").forEach((button) => {
    button.addEventListener("click", () => {
      refreshData();
    });
  });

  elements.appRoot.querySelectorAll("[data-search-open-type][data-search-open-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      await openGlobalSearchResult(button.dataset.searchOpenType, button.dataset.searchOpenId);
    });
  });

  elements.appRoot.querySelectorAll("[data-search-topology-type]").forEach((button) => {
    button.addEventListener("click", () => {
      openGlobalSearchTopology(button.dataset.searchTopologyType);
    });
  });

  elements.appRoot.querySelectorAll("[data-search-history-index]").forEach((button) => {
    button.addEventListener("click", () => {
      applyGlobalSearchHistory(button.dataset.searchHistoryIndex);
    });
  });

  elements.appRoot.querySelectorAll("[data-search-history-clear]").forEach((button) => {
    button.addEventListener("click", clearGlobalSearchHistory);
  });

}

function applyTopologyTransform() {
  const map = elements.appRoot.querySelector("[data-topology-map]");
  const readout = elements.appRoot.querySelector(".topology-scale-readout");
  if (map) {
    map.style.transform = `translate(${state.topologyView.x}px, ${state.topologyView.y}px) scale(${state.topologyView.scale})`;
  }
  if (readout) {
    readout.textContent = `${Math.round(state.topologyView.scale * 100)}%`;
  }
}

function setTopologyZoom(nextScale, anchorX = 0, anchorY = 0) {
  const previousScale = state.topologyView.scale;
  const scale = clampTopologyScale(nextScale);
  if (scale === previousScale) return;

  state.topologyView.x = anchorX - ((anchorX - state.topologyView.x) / previousScale) * scale;
  state.topologyView.y = anchorY - ((anchorY - state.topologyView.y) / previousScale) * scale;
  state.topologyView.scale = scale;
  applyTopologyTransform();
}

function resetTopologyView() {
  state.topologyView = { scale: 0.78, x: 0, y: 0 };
  applyTopologyTransform();
}

function bindTopologyViewport() {
  const viewport = elements.appRoot.querySelector(".production-topology-scroll");
  if (!viewport) return;

  viewport.querySelectorAll("[data-topology-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const rect = viewport.getBoundingClientRect();
      const anchorX = rect.width / 2;
      const anchorY = rect.height / 2;
      if (button.dataset.topologyAction === "zoom-in") {
        setTopologyZoom(state.topologyView.scale + 0.12, anchorX, anchorY);
      } else if (button.dataset.topologyAction === "zoom-out") {
        setTopologyZoom(state.topologyView.scale - 0.12, anchorX, anchorY);
      } else {
        resetTopologyView();
      }
    });
  });

  viewport.addEventListener(
    "wheel",
    (event) => {
      if (!event.ctrlKey && Math.abs(event.deltaY) < Math.abs(event.deltaX)) return;
      event.preventDefault();
      const rect = viewport.getBoundingClientRect();
      const nextScale = state.topologyView.scale * (event.deltaY > 0 ? 0.92 : 1.08);
      setTopologyZoom(nextScale, event.clientX - rect.left, event.clientY - rect.top);
    },
    { passive: false }
  );

  let dragStart = null;
  viewport.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target.closest("button, input, textarea, select")) return;
    dragStart = {
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      x: state.topologyView.x,
      y: state.topologyView.y,
    };
    viewport.setPointerCapture(event.pointerId);
    viewport.classList.add("is-panning");
  });

  viewport.addEventListener("pointermove", (event) => {
    if (!dragStart || event.pointerId !== dragStart.pointerId) return;
    state.topologyView.x = dragStart.x + event.clientX - dragStart.clientX;
    state.topologyView.y = dragStart.y + event.clientY - dragStart.clientY;
    applyTopologyTransform();
  });

  const stopPan = (event) => {
    if (!dragStart || event.pointerId !== dragStart.pointerId) return;
    dragStart = null;
    viewport.classList.remove("is-panning");
  };
  viewport.addEventListener("pointerup", stopPan);
  viewport.addEventListener("pointercancel", stopPan);
}

function topologyDomNodeLookup() {
  const lookup = new Map();
  elements.appRoot.querySelectorAll("[data-class-node-id], [data-topology-node-id]").forEach((element) => {
    const id = element.dataset.classNodeId || element.dataset.topologyNodeId;
    if (!id) return;
    lookup.set(id, {
      id,
      x: Number.parseFloat(element.style.left) || 0,
      y: Number.parseFloat(element.style.top) || 0,
    });
  });
  return lookup;
}

function updateClassTopologyEdges() {
  const nodeLookup = topologyDomNodeLookup();
  elements.appRoot.querySelectorAll(".production-edge").forEach((element) => {
    const edge = {
      source: element.dataset.edgeSource,
      target: element.dataset.edgeTarget,
      laneOffset: Number.parseFloat(element.dataset.edgeLaneOffset) || 0,
      labelOffset: Number.parseFloat(element.dataset.edgeLabelOffset) || 0,
      diagonal: element.dataset.edgeDiagonal === "true",
    };
    const geometry = edgeGeometry(edge, nodeLookup);
    element.setAttribute("points", geometry.points);
  });

  elements.appRoot.querySelectorAll(".production-edge-label").forEach((element) => {
    const edge = {
      source: element.dataset.edgeLabelSource,
      target: element.dataset.edgeLabelTarget,
      laneOffset: Number.parseFloat(element.dataset.edgeLabelLaneOffset) || 0,
      labelOffset: Number.parseFloat(element.dataset.edgeLabelOffset) || 0,
      diagonal: element.dataset.edgeLabelDiagonal === "true",
    };
    const geometry = edgeGeometry(edge, nodeLookup);
    element.setAttribute("x", String(geometry.label.x));
    element.setAttribute("y", String(geometry.label.y));
  });
}

function topologyNodeById(nodeId) {
  return (activeNeoTopology().nodes || []).find((node) => node.id === nodeId);
}

function bindTopologyNodeDragging() {
  elements.appRoot.querySelectorAll("[data-draggable-topology-node]").forEach((element) => {
    let dragStart = null;

    element.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const node = topologyNodeById(element.dataset.draggableTopologyNode);
      if (!node) return;

      event.stopPropagation();
      element.setPointerCapture(event.pointerId);
      dragStart = {
        pointerId: event.pointerId,
        clientX: event.clientX,
        clientY: event.clientY,
        x: Number.parseFloat(element.style.left) || Number(node.x) || 0,
        y: Number.parseFloat(element.style.top) || Number(node.y) || 0,
        moved: false,
      };
      element.classList.add("is-dragging");
    });

    element.addEventListener("pointermove", (event) => {
      if (!dragStart || event.pointerId !== dragStart.pointerId) return;
      const node = topologyNodeById(element.dataset.draggableTopologyNode);
      if (!node) return;

      const dx = (event.clientX - dragStart.clientX) / state.topologyView.scale;
      const dy = (event.clientY - dragStart.clientY) / state.topologyView.scale;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
        dragStart.moved = true;
        element.dataset.dragged = "true";
      }

      node.x = dragStart.x + dx;
      node.y = dragStart.y + dy;
      state.topologyNodePositions[topologyNodePositionKey(state.classTopologyMode, node.id)] = { x: node.x, y: node.y };
      element.style.left = `${node.x}px`;
      element.style.top = `${node.y}px`;
      updateClassTopologyEdges();
    });

    const stopDrag = (event) => {
      if (!dragStart || event.pointerId !== dragStart.pointerId) return;
      if (!dragStart.moved) {
        element.dataset.dragged = "";
      }
      dragStart = null;
      element.classList.remove("is-dragging");
    };

    element.addEventListener("pointerup", stopDrag);
    element.addEventListener("pointercancel", stopDrag);
  });
}

function bindClassNodeDragging() {
  const map = elements.appRoot.querySelector("[data-topology-map]");
  if (!map) return;

  elements.appRoot.querySelectorAll("[data-draggable-class-node]").forEach((element) => {
    let dragStart = null;

    element.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const node = classNodeById(element.dataset.draggableClassNode);
      if (!node) return;

      event.stopPropagation();
      element.setPointerCapture(event.pointerId);
      dragStart = {
        pointerId: event.pointerId,
        clientX: event.clientX,
        clientY: event.clientY,
        x: node.x,
        y: node.y,
        moved: false,
      };
      element.classList.add("is-dragging");
    });

    element.addEventListener("pointermove", (event) => {
      if (!dragStart || event.pointerId !== dragStart.pointerId) return;
      const node = classNodeById(element.dataset.draggableClassNode);
      if (!node) return;

      const dx = (event.clientX - dragStart.clientX) / state.topologyView.scale;
      const dy = (event.clientY - dragStart.clientY) / state.topologyView.scale;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
        dragStart.moved = true;
        element.dataset.dragged = "true";
      }

      node.x = dragStart.x + dx;
      node.y = dragStart.y + dy;
      element.style.left = `${node.x}px`;
      element.style.top = `${node.y}px`;
      updateClassTopologyEdges();
    });

    const stopDrag = (event) => {
      if (!dragStart || event.pointerId !== dragStart.pointerId) return;
      if (!dragStart.moved) {
        element.dataset.dragged = "";
      }
      dragStart = null;
      element.classList.remove("is-dragging");
    };

    element.addEventListener("pointerup", stopDrag);
    element.addEventListener("pointercancel", stopDrag);
  });

  bindTopologyNodeDragging();
}

function bindAgentEvents(root = document) {
  root.querySelectorAll("[data-agent-console-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      state.agent.consoleOpen = !state.agent.consoleOpen;
      renderAgentConsoleOverlay();
      updateActiveNavigation();
    });
  });

  const form = root.querySelector("#agent-form");
  const input = root.querySelector("#agent-input");
  const stopBtn = root.querySelector("#agent-stop-btn");
  const clearBtn = root.querySelector("#agent-clear-btn");

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = input?.value || "";
    if (input) input.value = "";
    await sendAgentMessage(text);
  });

  input?.addEventListener("keydown", async (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      const text = input.value;
      input.value = "";
      await sendAgentMessage(text);
    }
  });

  stopBtn?.addEventListener("click", stopAgentRequest);

  clearBtn?.addEventListener("click", () => {
    if (state.agent.pending) return;
    state.agent.messages = [];
    storeAgentMessages();
    renderAgentConsoleOverlay();
  });

  root.querySelectorAll(".agent-suggestion").forEach((button) => {
    button.addEventListener("click", () => {
      state.agent.consoleOpen = true;
      if (input) {
        input.value = button.dataset.agentPrompt || "";
        input.focus();
      }
    });
  });
}

function updateActiveNavigation() {
  document.querySelectorAll(".nav-link").forEach((link) => {
    const route = normalizeRoute(link.getAttribute("href"));
    link.classList.toggle("active", route === state.route || (route === "/agent/console" && state.agent.consoleOpen));
  });
}

function applySidebarState() {
  elements.appShell?.classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
  if (!elements.sidebarToggle) return;

  elements.sidebarToggle.textContent = state.sidebarCollapsed ? ">" : "<";
  elements.sidebarToggle.setAttribute("aria-expanded", String(!state.sidebarCollapsed));
  elements.sidebarToggle.setAttribute("aria-label", state.sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar");
  elements.sidebarToggle.title = state.sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar";
}

function bindEvents() {
  window.addEventListener("hashchange", () => setRoute(location.hash));
  elements.refreshBtn.addEventListener("click", refreshData);
  elements.apiBaseInput.addEventListener("change", () => {
    reconnectDigitalTwinEvents();
    refreshData();
  });
  elements.sidebarToggle?.addEventListener("click", () => {
    state.sidebarCollapsed = !state.sidebarCollapsed;
    storeSidebarCollapsed();
    applySidebarState();
    renderAgentConsoleOverlay();
  });
}

function initialize() {
  if (state.route === "/agent/console") {
    state.agent.consoleOpen = true;
    state.route = "/ontology/devices";
  }
  applyTheme();
  elements.apiBaseInput.value = readStoredApiBase();
  renderShell();
  bindEvents();
  connectDigitalTwinEvents();
  renderThemeSwitcher();
  renderPage();
  refreshData().catch(() => renderPage());
}

initialize();






















