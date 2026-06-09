import { NAVIGATION, ROUTE_META } from "./config/navigation.js";
import { MOCK_TEMPLATES } from "./data/mock-data.js";
import { fetchJson, loadDigitalTwin, adaptPayload } from "./data/api.js";
import { flattenRows } from "./data/adapters/mysql-tables.js";
import { buildOverviewModel, getDeviceMeta, listDeviceKeys } from "./data/adapters/ontology-view-model.js";
import { escapeHtml } from "./utils/html.js";
import { firstField, rowText } from "./utils/text.js";
import { statusClassForRows } from "./domain/workflow-stages.js";

const STORAGE_KEY = "digitalTwinApiBase";
const state = {
  route: normalizeRoute(location.hash),
  selectedDevice: "warehouse",
  devices: { ok: false, source: "api", error: "", tables: [] },
  store: { ok: false, source: "api", error: "", tables: [] },
  loading: false,
};

const elements = {
  sidebarNav: document.querySelector("#sidebar-nav"),
  breadcrumb: document.querySelector("#breadcrumb"),
  pageTitle: document.querySelector("#page-title"),
  pageDescription: document.querySelector("#page-description"),
  appRoot: document.querySelector("#app-root"),
  apiBaseInput: document.querySelector("#api-base"),
  refreshBtn: document.querySelector("#refresh-btn"),
};

function normalizeRoute(hash) {
  const value = String(hash || "#/ontology/overview").replace(/^#/, "");
  return value || "/ontology/overview";
}

function readStoredApiBase() {
  try {
    return localStorage.getItem(STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function storeApiBase(value) {
  try {
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    return;
  }
}

function currentRouteMeta() {
  return ROUTE_META[state.route] || ROUTE_META["/ontology/overview"];
}

function setRoute(hash) {
  state.route = normalizeRoute(hash);
  renderShell();
  renderPage();
}

function setLoading(value) {
  state.loading = value;
  elements.refreshBtn.disabled = value;
  elements.refreshBtn.textContent = value ? "刷新中..." : "刷新";
}

function applyPayload(kind, payload) {
  const adapted = adaptPayload(payload);
  state[kind] = adapted;
}

function apiBase() {
  const base = elements.apiBaseInput.value.trim().replace(/\/+$/, "");
  if (!base) {
    throw new Error("请填写后端地址");
  }
  return base;
}

async function refreshData() {
  setLoading(true);
  try {
    storeApiBase(apiBase());
    const payload = await loadDigitalTwin(elements.apiBaseInput);
    applyPayload("devices", payload.devices);
    applyPayload("store", payload.store);
  } catch (error) {
    state.devices = { ok: false, source: "api", error: error.message, tables: [] };
    state.store = { ok: false, source: "api", error: error.message, tables: [] };
  } finally {
    setLoading(false);
    renderPage();
  }
}

function statusBadgeText() {
  if (state.devices.ok && state.store.ok) {
    return "已连接 device / store 数据库";
  }
  if (state.devices.ok || state.store.ok) {
    return "部分实时，部分兜底";
  }
  return "已切换到前端兜底数据";
}

function deviceRowsForSelected() {
  const rows = flattenRows(state.devices.tables);
  const meta = getDeviceMeta(state.selectedDevice);
  const matched = rows.filter((row) => meta.keywords.some((keyword) => rowText(row).toLowerCase().includes(String(keyword).toLowerCase())));
  return matched.length ? matched : rows;
}

function renderShell() {
  const meta = currentRouteMeta();
  elements.breadcrumb.textContent = meta.breadcrumb;
  elements.pageTitle.textContent = meta.title;
  elements.pageDescription.textContent = meta.description;

  elements.sidebarNav.innerHTML = NAVIGATION.map((group) => `
    <section class="nav-group">
      <p class="nav-group-title">${escapeHtml(group.section)}</p>
      <div class="nav-links">
        ${group.items
          .map(
            (item) => `
          <a class="nav-link ${normalizeRoute(item.hash) === state.route ? "active" : ""}" href="${item.hash}">
            <span>${escapeHtml(item.label)}</span>
            <small>${escapeHtml(item.description)}</small>
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
      location.hash = link.getAttribute("href");
    });
  });
}

function renderOverview() {
  const model = buildOverviewModel(state.devices.tables, state.store.tables, state.selectedDevice);
  const deviceCards = model.deviceRows.slice(0, 8).map((row) => renderRecordCard(row)).join("");
  const storeCards = model.storeRows.slice(0, 8).map((row) => renderMaterialCard(row)).join("");
  const deviceMeta = getDeviceMeta(state.selectedDevice);
  const stageStrip = model.workflowStages
    .map((stage) => `<span class="stage-pill stage-${stage.color}">${escapeHtml(stage.label)}</span>`)
    .join("");

  return `
    <section class="page-grid overview-grid">
      <article class="hero-card scene-card">
        <div class="section-head">
          <div>
            <p class="eyebrow">Production Scene</p>
            <h2>产线数字孪生总览</h2>
          </div>
          <span class="status-pill ${state.devices.ok && state.store.ok ? "online" : "warn"}">${escapeHtml(statusBadgeText())}</span>
        </div>
        <div class="summary-grid">
          <div class="metric-card"><span>设备记录</span><strong>${model.deviceCount}</strong></div>
          <div class="metric-card"><span>库存条目</span><strong>${model.storeCount}</strong></div>
          <div class="metric-card"><span>当前资产</span><strong>${escapeHtml(deviceMeta.title)}</strong></div>
          <div class="metric-card"><span>数据模式</span><strong>${escapeHtml(state.devices.ok && state.store.ok ? "api" : "hybrid")}</strong></div>
        </div>
        <div class="floor-board">
          <button class="device-node active" data-device="warehouse" type="button">立体仓库</button>
          <button class="device-node" data-device="cobot" type="button">协作机器人</button>
          <button class="device-node" data-device="scara-1" type="button">SCARA 1</button>
          <button class="device-node" data-device="scara-2" type="button">SCARA 2</button>
          <div class="connector-line"></div>
          <div class="stage-strip">${stageStrip}</div>
        </div>
      </article>

      <aside class="inspect-panel">
        <section class="panel-card">
          <div class="section-head compact">
            <div>
              <p class="eyebrow">Selected Entity</p>
              <h3>${escapeHtml(deviceMeta.title)}</h3>
            </div>
            <span class="badge ${model.deviceStatus}">${escapeHtml(model.deviceStatus)}</span>
          </div>
          <p class="muted">${escapeHtml(deviceMeta.subtitle)}</p>
        </section>
        <section class="panel-card">
          <div class="section-head compact"><h3>设备数据</h3><span class="tag">${state.devices.ok ? "live" : "empty"}</span></div>
          <div class="record-list">${deviceCards || emptyCard("devices", state.devices.error || "暂无设备数据")}</div>
        </section>
        <section class="panel-card">
          <div class="section-head compact"><h3>仓库物料</h3><span class="tag">${state.store.ok ? "live" : "empty"}</span></div>
          <div class="material-grid">${storeCards || emptyCard("store", state.store.error || "暂无库存数据")}</div>
        </section>
      </aside>
    </section>
  `;
}

function renderTemplates() {
  return `
    <section class="page-grid">
      <article class="panel-card full-width">
        <div class="section-head"><div><p class="eyebrow">Templates</p><h2>Ontology Templates</h2></div></div>
        <div class="template-grid">
          ${MOCK_TEMPLATES.map((item) => `
            <article class="template-card">
              <div class="template-meta">
                <span>${escapeHtml(item.version)}</span>
                <span class="badge ${item.status === "Active" ? "online" : "idle"}">${escapeHtml(item.status)}</span>
              </div>
              <h3>${escapeHtml(item.title)}</h3>
              <p class="muted">${escapeHtml(item.summary)}</p>
              <small>${escapeHtml(item.subtitle)}</small>
            </article>
          `).join("")}
        </div>
      </article>
    </section>
  `;
}

function renderDevices() {
  const rows = flattenRows(state.devices.tables);
  return `
    <section class="page-grid">
      <article class="panel-card full-width">
        <div class="section-head"><div><p class="eyebrow">Devices</p><h2>Device Graph</h2></div></div>
        <div class="record-list">
          ${rows.map((row) => renderRecordCard(row)).join("") || emptyCard("devices", "没有设备记录")}
        </div>
      </article>
    </section>
  `;
}

function renderWorkflow() {
  const stages = ["出库", "加工", "质检", "贴标", "入库"];
  return `
    <section class="page-grid">
      <article class="panel-card full-width">
        <div class="section-head"><div><p class="eyebrow">Workflow</p><h2>Production Flow</h2></div></div>
        <div class="workflow-track">
          ${stages.map((stage, index) => `<div class="workflow-step"><span>${index + 1}</span><strong>${stage}</strong></div>`).join("")}
        </div>
      </article>
    </section>
  `;
}

function renderPlaceholder(title) {
  return `
    <section class="page-grid">
      <article class="panel-card full-width placeholder-card">
        <div class="section-head"><div><p class="eyebrow">${escapeHtml(title)}</p><h2>${escapeHtml(title)}</h2></div></div>
        <p class="muted">该页面先作为控制台占位，后续接入真实 ontology、数据源和管理功能。</p>
      </article>
    </section>
  `;
}

function renderPage() {
  let html = "";
  if (state.route === "/ontology/overview") html = renderOverview();
  else if (state.route === "/ontology/templates") html = renderTemplates();
  else if (state.route === "/ontology/devices") html = renderDevices();
  else if (state.route === "/ontology/workflow") html = renderWorkflow();
  else html = renderPlaceholder(currentRouteMeta().title);

  elements.appRoot.innerHTML = html;

  elements.appRoot.querySelectorAll(".device-node").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedDevice = button.dataset.device;
      renderPage();
    });
  });

  updateActiveDeviceButtons();
}

function updateActiveDeviceButtons() {
  document.querySelectorAll(".nav-link").forEach((link) => {
    link.classList.toggle("active", normalizeRoute(link.getAttribute("href")) === state.route);
  });
  elements.appRoot.querySelectorAll(".device-node").forEach((button) => {
    button.classList.toggle("active", button.dataset.device === state.selectedDevice);
  });
}

function renderRecordCard(row) {
  const title = firstField(row, ["设备名称", "设备名", "device_name", "deviceName", "name"], row.__table);
  return `
    <article class="record-card">
      <div class="card-title-row">
        <h4>${escapeHtml(title)}</h4>
        <span>${escapeHtml(row.__table)}</span>
      </div>
      <div class="kv">${renderKv(row)}</div>
    </article>
  `;
}

function renderMaterialCard(row) {
  const title = firstField(row, ["物料名称", "物料名", "material_name", "materialName", "name"], row.__table);
  return `
    <article class="material-card">
      <div class="card-title-row">
        <h4>${escapeHtml(title)}</h4>
        <span>${escapeHtml(row.__table)}</span>
      </div>
      <div class="kv">${renderKv(row)}</div>
    </article>
  `;
}

function renderKv(row) {
  return Object.entries(row)
    .filter(([key]) => key !== "__table")
    .slice(0, 10)
    .map(([key, value]) => `<span>${escapeHtml(key)}</span><span>${escapeHtml(value)}</span>`)
    .join("");
}

function emptyCard(kind, message) {
  const className = kind === "store" ? "material-card" : "record-card";
  return `<article class="${className}"><div class="kv"><span>提示</span><span>${escapeHtml(message)}</span></div></article>`;
}

function bindGlobalEvents() {
  window.addEventListener("hashchange", () => setRoute(location.hash));
  elements.refreshBtn.addEventListener("click", refreshData);
  elements.apiBaseInput.addEventListener("change", refreshData);
}

function initialize() {
  const storedApiBase = readStoredApiBase();
  if (storedApiBase) {
    elements.apiBaseInput.value = storedApiBase;
  }
  renderShell();
  bindGlobalEvents();
  renderPage();
  refreshData().catch(() => renderPage());
}

initialize();
