export const FALLBACK_DEVICE_TABLES = [];

export const FALLBACK_STORE_TABLES = [];

export const REPORT_TEMPLATES = [
  {
    ontologyId: "smart-production-ontology",
    id: "RPT-001",
    title: "生产运行日报模板",
    format: "PDF + Dashboard",
    charts: ["设备状态分布", "订单达成率", "库存预警"],
    sections: ["摘要", "关键指标", "风险点", "行动建议"],
  },
  {
    ontologyId: "smart-production-ontology",
    id: "RPT-002",
    title: "产线分析周报模板",
    format: "PPT",
    charts: ["工单进度趋势", "OEE 趋势", "工序瓶颈图"],
    sections: ["产能利用", "瓶颈分析", "质量事件", "改进建议"],
  },
  {
    ontologyId: "smart-production-ontology",
    id: "RPT-PRODUCTION-ANALYSIS",
    title: "产品生产分析报告模板",
    format: "Markdown + Dashboard",
    skillPath: "skills/product-production-analysis-report/SKILL.md",
    charts: ["产品生产用时分布图", "工序用时堆叠条形图", "工序用时箱线分析", "单次生产甘特图", "工序平均用时占比"],
    sections: ["分析目标", "数据口径", "产品-工序拓扑流程", "生产用时分布", "各工序用时分析", "瓶颈判断", "改进建议"],
  },
];

export const GENERATED_REPORTS = [
  {
    ontologyId: "smart-production-ontology",
    id: "RPT-PRODUCTION-ANALYSIS-001",
    title: "产品生产分析报告 - 立方堆",
    summary: "基于 Data 订单工单历史、设备运行历史和产品-工序拓扑生成的生产用时分析报告。",
    status: "Active",
    kind: "generated",
    format: "Markdown",
    source: "AI Agent",
    createdAt: "2026-05-15T00:00:00",
    skillPath: "skills/product-production-analysis-report/SKILL.md",
    filePath: "skills/product-production-analysis-report/产品生产分析报告_立方堆.md",
  },
];

export const TOOL_HISTORY = [
  { ontologyId: "smart-production-ontology", time: "2026-05-07 10:22", action: "全局检索", detail: "检索立体仓库相关设备与工单。" },
  { ontologyId: "smart-production-ontology", time: "2026-05-07 09:48", action: "生成报告", detail: "生成生产运行日报并包含设备与库存图表。" },
  { ontologyId: "smart-production-ontology", time: "2026-05-07 09:16", action: "设备状态", detail: "刷新 device / store 数据接口。" },
];

export const AGENT_THREADS = [
  {
    ontologyId: "smart-production-ontology",
    id: "AG-01",
    title: "产线管控Agent / 今日排产",
    status: "Active",
    summary: "跟踪工单、订单和库存约束。",
  },
  {
    ontologyId: "smart-production-ontology",
    id: "AG-02",
    title: "质量巡检Agent / 异常复盘",
    status: "Idle",
    summary: "汇总质检事件与异常停机原因。",
  },
];
