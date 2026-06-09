export const NAVIGATION = [
  {
    section: "ONTOLOGY",
    items: [
      { label: "Devices", hash: "#/ontology/devices", description: "设备资产与运行状态" },
      { label: "Orders", hash: "#/ontology/orders", description: "订单树与拆分工单" },
      { label: "Materials", hash: "#/ontology/materials", description: "物料与库存信息" },
      { label: "Products", hash: "#/ontology/products", description: "产品定义与工艺模板" },
      { label: "Crafts", hash: "#/ontology/crafts", description: "工艺流程与能力关系" },
      { label: "Processes", hash: "#/ontology/processes", description: "产品工序节点" },
      { label: "Classes", hash: "#/ontology/classes", description: "本体类完整拓扑" },
      { label: "Relations", hash: "#/ontology/relations", description: "类关系管理" },
    ],
  },
  {
    section: "TOOLS",
    items: [
      { label: "Global Search", hash: "#/tools/search", description: "跨实体统一检索" },
      { label: "Reasoning Rules", hash: "#/tools/reasoning-rules", description: "推理规则参考" },
      { label: "Reports", hash: "#/tools/reports", description: "技能驱动报告" },
    ],
  },
  {
    section: "AI AGENT",
    items: [
      { label: "Production Agent", hash: "#/agent/console", description: "交互控制与信息获取" },
    ],
  },
  {
    section: "DATA",
    items: [
      { label: "Order History", hash: "#/data/orders", description: "订单与工单执行记录" },
      { label: "Device History", hash: "#/data/devices", description: "设备执行历史与负载曲线" },
      { label: "Quality Trace", hash: "#/data/quality", description: "质检、贴标与物料追溯" },
    ],
  },
];

export const ROUTE_META = {
  "/ontology/classes": {
    title: "Classes",
    breadcrumb: "Ontology / Classes",
    description: "查看包含设备、物料、订单、工单、产品和工艺的完整本体类拓扑。",
  },
  "/ontology/relations": {
    title: "Relations",
    breadcrumb: "Ontology / Relations",
    description: "管理智能产线本体类之间的关系定义。",
  },
  "/ontology/devices": {
    title: "Devices",
    breadcrumb: "Ontology / Devices",
    description: "查看设备资产、工位状态、当前任务和数据来源。",
  },
  "/ontology/orders": {
    title: "Orders",
    breadcrumb: "Ontology / Orders",
    description: "合并查看订单和拆分工单，包含状态、开始/结束时间和工单分配工站。",
  },
  "/ontology/work-orders": {
    title: "Work Orders",
    breadcrumb: "Ontology / Work_orders",
    description: "工单已合并到 Orders 页面，通过订单树展开查看。",
  },
  "/ontology/materials": {
    title: "Materials",
    breadcrumb: "Ontology / Materials",
    description: "物料、库位和库存周转信息。",
  },
  "/ontology/products": {
    title: "Products",
    breadcrumb: "Ontology / Products",
    description: "查看产品定义、工艺模板与包装要求。",
  },
  "/ontology/crafts": {
    title: "Crafts",
    breadcrumb: "Ontology / Crafts",
    description: "查看工艺流程节点、能力关系和工艺属性。",
  },
  "/ontology/processes": {
    title: "Processes",
    breadcrumb: "Ontology / Processes",
    description: "查看产品工序节点、物料使用与部件产出信息。",
  },
  "/tools/search": {
    title: "Global Search",
    breadcrumb: "Tools / Global Search",
    description: "跨设备、订单、工单、物料和产品的统一检索。",
  },
  "/tools/reasoning-rules": {
    title: "Reasoning Rules",
    breadcrumb: "Tools / Reasoning Rules",
    description: "查看 ontology 推理规则参考，供产线管控 Agent 生成推理说明和分析结论时使用。",
  },
  "/tools/reports": {
    title: "Report Studio",
    breadcrumb: "Tools / Reports",
    description: "通过 skill 指定格式、图表和分析内容制作报告。",
  },
  "/data/orders": {
    title: "订单工单历史",
    breadcrumb: "DATA / Orders",
    description: "查看订单历史以及拆分工单的开始时间、结束时间和结束状态。",
  },
  "/data/devices": {
    title: "设备运行历史",
    breadcrumb: "DATA / Devices",
    description: "查看设备执行工单历史与设备负载曲线展示模块。",
  },
  "/data/quality": {
    title: "质检追溯",
    breadcrumb: "DATA / Quality Trace",
    description: "查看质检工序产品历史、合格贴标产品编号与物料追溯信息。",
  },
  "/agent/console": {
    title: "AI Agent Console",
    breadcrumb: "AI Agent / Production Control Agent",
    description: "与产线管控 Agent 进行交互管理并获取信息。",
  },
};

