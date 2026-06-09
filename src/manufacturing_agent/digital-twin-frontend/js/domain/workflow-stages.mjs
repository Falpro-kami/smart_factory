export const WORKFLOW_STAGES = [
  { key: "outbound", label: "出库", color: "amber" },
  { key: "processing", label: "加工", color: "cyan" },
  { key: "inspection", label: "质检", color: "blue" },
  { key: "labeling", label: "贴标", color: "green" },
  { key: "inbound", label: "入库", color: "green" },
];

export function stageLabel(key) {
  return WORKFLOW_STAGES.find((stage) => stage.key === key)?.label || key;
}

export function statusClassForRows(rows, rowText) {
  const text = String(rowText(rows)).toLowerCase();
  if (["告警", "故障", "异常", "alarm", "error", "fault"].some((value) => text.includes(value.toLowerCase()))) {
    return "alarm";
  }

  const statusText = text.replace(/\s+/g, "");
  if (["1", "true", "run", "running", "online", "正常", "运行", "启动"].some((value) => statusText.includes(value))) {
    return "online";
  }

  if (["0", "false", "idle", "standby", "stop", "stopped", "待机", "停止", "停机"].some((value) => statusText.includes(value))) {
    return "idle";
  }

  return "online";
}
