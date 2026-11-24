# 接口

- `GET /`：工作台。
- `GET /api/catalog`：阶段、字段和样例。
- `POST /api/stages/{stage}`：按阶段返回处理结果。
- `POST /api/runs`：执行完整批次并保存草稿。
- `GET /api/runs/{id}`：读取批次。
- `POST /api/runs/{id}/review`：签发或暂缓整批，提交 `decision`、`comment`、`expected_revision`。
- `PUT/POST /api/contract-limits`：按月录入房间合同上限，提交 `month` 与 `contract_limits`（房间号到 kWh/Wh 的映射或记录数组）。
- `POST /api/runs`：可在请求体带 `contract_limits`、`unit`（`kwh`/`wh`）与 `month`，计算即应用上限。
- `POST /api/runs/{id}/issue`：带 `building_id` 签发单栋（阻断返回 `409 GATE_BLOCKED`）；不带则签发同批全部可签楼栋，返回逐栋 `issued`/`blocked` 结果。同栋重复请求幂等返回同一 `posting_no`，不重复出账。兼容 `/sign`、`/postings`、`/issuances`、`/buildings/{bid}/issue` 等路径。
- `GET /api/runs/{id}/issuances`：读取该批各楼栋签发/出账结果。
- `GET /api/runs/{id}/evidence`：下载已签发证据。
- `GET /api/examples/{profile}`：下载样例。
- `GET /healthz`：健康检查。
