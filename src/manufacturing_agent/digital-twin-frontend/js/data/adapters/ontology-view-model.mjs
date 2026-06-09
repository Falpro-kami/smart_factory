import { rowText } from "../../utils/text.mjs";
import { WORKFLOW_STAGES, stageLabel, statusClassForRows } from "../../domain/workflow-stages.mjs";

const DEVICE_META = {
  warehouse: {
    title: "立体仓库",
    subtitle: "自动化立体仓库，用于物料存储、出库和入库。",
    keywords: ["立体仓库", "仓库", "storage", "warehouse", "store"],
  },
  cobot: {
    title: "协作机器人工作站",
    subtitle: "协作机器人加工工作站，用于堆积、拼接等加工任务。",
    keywords: ["协作机器人", "协作", "加工", "机器人", "processing", "cobot"],
  },
  "scara-1": {
    title: "SCARA 工作站 1",
    subtitle: "SCARA 机器人工作站 1，用于质量检测。",
    keywords: ["scara工作站1", "scara 工作站 1", "scara1", "sc-01", "质检", "检测", "inspection"],
  },
  "scara-2": {
    title: "SCARA 工作站 2",
    subtitle: "SCARA 机器人工作站 2，用于贴标和后处理。",
    keywords: ["scara工作站2", "scara 工作站 2", "scara2", "sc-02", "贴标", "label", "labeling"],
  },
};

function matchesDevice(row, deviceKey) {
  const meta = DEVICE_META[deviceKey];
  const text = rowText(row).toLowerCase();
  return meta.keywords.some((keyword) => text.includes(String(keyword).toLowerCase()));
}

function selectedRows(tables, deviceKey) {
  const rows = tables.flatMap((table) => table.rows.map((row) => ({ ...row, __table: table.name })));
  const matched = rows.filter((row) => matchesDevice(row, deviceKey));
  return matched.length ? matched : rows;
}

function rowsText(rows) {
  return rows.map((row) => rowText(row)).join(" ");
}

export function buildOverviewModel(deviceTables, storeTables, selectedDevice = "warehouse") {
  const deviceRows = selectedRows(deviceTables, selectedDevice);
  const storeRows = storeTables.flatMap((table) => table.rows.map((row) => ({ ...row, __table: table.name })));
  const status = statusClassForRows(deviceRows, rowsText);

  return {
    selectedDevice,
    selectedMeta: DEVICE_META[selectedDevice],
    deviceCount: deviceTables.reduce((sum, table) => sum + table.rows.length, 0),
    storeCount: storeRows.length,
    sourceState: "hybrid",
    deviceRows,
    storeRows,
    deviceStatus: status,
    workflowStages: WORKFLOW_STAGES.map((stage) => ({ ...stage, label: stageLabel(stage.key) })),
  };
}

export function getDeviceMeta(deviceKey) {
  return DEVICE_META[deviceKey];
}

export function listDeviceKeys() {
  return Object.keys(DEVICE_META);
}
