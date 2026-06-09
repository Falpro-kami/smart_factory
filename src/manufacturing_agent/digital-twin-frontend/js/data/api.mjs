import { normalizeTables } from "./adapters/mysql-tables.mjs";

function apiBaseFromInput(input) {
  const base = input.value.trim().replace(/\/+$/, "");
  if (!base) {
    throw new Error("请填写后端地址");
  }
  return base;
}

export async function fetchJson(input, path) {
  const response = await fetch(`${apiBaseFromInput(input)}${path}`, {
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

export async function loadDigitalTwin(input) {
  const [devices, store] = await Promise.allSettled([
    fetchJson(input, "/api/digital-twin/devices"),
    fetchJson(input, "/api/digital-twin/store"),
  ]);

  return {
    devices: devices.status === "fulfilled" ? devices.value : { ok: false, error: devices.reason?.message || "接口请求失败", tables: [] },
    store: store.status === "fulfilled" ? store.value : { ok: false, error: store.reason?.message || "接口请求失败", tables: [] },
  };
}

export function adaptPayload(payload) {
  const tables = normalizeTables(payload?.tables);
  if (payload?.ok && tables.length) {
    return { ok: true, source: "api", error: "", tables };
  }

  return {
    ok: false,
    source: "api",
    error: payload?.error || "接口未返回可展示数据",
    tables: [],
  };
}
