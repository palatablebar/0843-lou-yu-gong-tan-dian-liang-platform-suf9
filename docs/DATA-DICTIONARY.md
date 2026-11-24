# 字段定义

| 字段 | 类型 | 说明 |
|---|---|---|
| `building_id` | text | 业务字段 |
| `meter_id` | text | 主键 |
| `room_id` | text | 业务字段 |
| `area_m2` | decimal | 业务字段 |
| `start_reading` | decimal | 业务字段 |
| `end_reading` | decimal | 业务字段 |
| `main_kwh` | decimal | 业务字段 |

空字符串、`-`、`NA`、`null` 和 `未提供` 按空值处理。金额字段在整理层转为整数分或整数最小单位；日期按 ISO 日期解析；带时间的字段按本地时间解析。标识字段保持为文本，前导零不会被去除。

## 合同上限与签发扩展

- 合同上限可通过 `POST /api/runs` 的 `contract_limits`（或 `limits`/`caps`）录入，也可放在 CSV 的可选扩展列（如 `contract_limit_kwh`）。录入按 kWh，内部换算为整数瓦时；`contract_limits_wh` 按瓦时。
- 楼栋结果额外提供：`shares`、`allocations[].shared/cap/capped`、`shortfall`（同义 `gap`/`difference`/`pending_amount`，留待核差额 Wh）、`meter_balanced`、`issuable`、`issue_blocker`。
- 签发记录字段：`posting_no`（单号）、`status=ISSUED`、`building_id`、`amount_wh`、`idempotency_key`；同一 `(run_id, building_id)` 重试只返回原记录。
