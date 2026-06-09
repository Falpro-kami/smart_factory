---
name: product-production-analysis-report
description: Generate product production time analysis reports for the manufacturing_agent smart production-line ontology project. Use when the agent must analyze Data order/work-order history, product-process topology, process durations, production-time distribution, bottlenecks, or create a report from the product production analysis template.
---

# Product Production Analysis Report

Use this skill to generate a report for one product or a product family from the project data. Do not reuse example instance names, numbers, or prose from reference images. Use only current project data.

## Data Sources

Prefer these sources in order:

1. `Data.orderTree`: finished or archived orders and their split work orders.
2. `Data.deviceHistory`: device execution history, load curve, and station-level run information.
3. `Data.qualityTrace`: inspection records, label product codes, material batches, and part codes.
4. Product-process topology: Product -> Process flow, input materials, output parts, and process order.
5. Ontology current state: only for in-progress context; do not mix active orders into historical production-time statistics unless explicitly requested.

## Required Fields

For each order:

- order id, product name/id, order status
- order start time and end time
- split work orders

For each work order:

- work order id, process name/id, status
- assigned workstation/device
- start time and end time
- material batch or part references when available

## Calculations

Compute durations from actual start/end timestamps. If an explicit duration field exists, use it only when timestamps are unavailable.

- `order_total_duration = order_end_time - order_start_time`
- `process_duration = work_order_end_time - work_order_start_time`
- `process_avg_duration = average(process_duration by process)`
- `process_duration_share = process_avg_duration / sum(process_avg_duration)`
- `production_time_distribution = total duration grouped by order/batch`

Exclude records with missing or invalid start/end times from duration statistics, and list the exclusion count in the data-quality note.

## Neo4j Query Safety

When querying product-process topology with Cypher, compute sort keys before `RETURN`.

Use this pattern:

```cypher
MATCH (s)
WHERE any(label IN labels(s) WHERE toLower(label) = 'assemblystep')
WITH s, coalesce(s.stepId, s.order, s.name, s.process_name, 0) AS sort_key
RETURN elementId(s) AS step_node_id, properties(s) AS step_props
ORDER BY sort_key
```

Do not use `RETURN ... ORDER BY coalesce(s.stepId, s.order, 0)` because Neo4j can reject variables not projected before a `WITH/RETURN` boundary.

## Required Report Structure

1. Summary
   - product analyzed
   - number of orders/batches
   - average, minimum, and maximum total production time
   - main bottleneck process

2. Data Scope
   - data source names
   - time range
   - included/excluded record counts

3. Product-Process Topology
   - show the product -> process sequence
   - include each process name and assigned workstation when available
   - mention input material and output part relationships if present

4. Production Time Distribution
   - describe distribution across orders/batches
   - include table-ready values for order id, product, total duration, status
   - recommend a bar chart or histogram

5. Process Duration Analysis
   - include per-process average, min, max, count, and duration share
   - identify high-variance or long-duration processes
   - recommend stacked bar, box plot, trend line, and process-duration share chart when data supports them

6. Single-Run Timeline
   - choose the most representative or longest order
   - provide Gantt-ready rows: process, start, end, duration, workstation

7. Bottleneck And Improvement
   - bottleneck process and evidence
   - likely station/resource constraint
   - practical improvement suggestions

## Output Rules

- Write in Chinese unless the user asks otherwise.
- Keep conclusions tied to data.
- If data is insufficient, state exactly which field or table is missing.
- Do not fabricate product names, process names, durations, orders, or stations.
- Return report text plus chart-ready tables when the UI or user needs visualization.

