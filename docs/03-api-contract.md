# 03 接口契约（software-reback-cloud API v1）

> 归属：文档 B。本文是**可直接照着实现**的契约：字段名、类型、错误码、幂等键、DDL 全部固定。
> Base URL：`http://192.168.1.24:8084/api/v1`（局域网直连）；外网经 frp `cloud1:20084`。
> 服务端形态：单进程 `http.server`（Python 3.12.3）+ SQLite 3.45.1，**不代理任何安装包字节**。
> 示例均为完整包络；重复的 `request_id` 用 `"..."` 省略。

## 1. 通用约定

| 项 | 约定 |
|---|---|
| 协议 / 编码 | HTTP/1.1 明文（仅局域网，见 02 文档第 8 节）；`UTF-8`，`Content-Type: application/json; charset=utf-8` |
| 认证 | `Authorization: Bearer <token>`；**除 `/health`、`/accounts/register`、`/accounts/login` 外全部必需** |
| 请求体 | 必须 `application/json`（不接受 form-data）；上限 1 MiB（清单上报）/ 64 KiB（其他），超限 `E_PAYLOAD_TOO_LARGE` |
| 响应压缩 | 客户端发 `Accept-Encoding: gzip` 时，`/catalog/snapshot` 与 `/inventories/*` 返回 `Content-Encoding: gzip` |
| 时间格式 | **ISO 8601 带时区**；服务端统一输出 UTC `2026-11-15T14:16:33Z`，接受 `+08:00` 并入库前归一 |
| 分页 | `?limit=50&cursor=<opaque>`；`limit` 默认 50、上限 200；响应含 `data.page = {limit, next_cursor, has_more}`；**不用 offset**（避免漂移） |
| 排序 | 默认 `created_at DESC`；`/catalog/snapshot` 全量固定按 `display_name` 升序 |
| 请求追踪 | 客户端可发 `X-Request-Id`；服务端回写（未发则生成 UUID4）并存入 `audit_logs.request_id` |
| 版本 | 路径 `/api/v1`；服务端**忽略未知字段**，字段只增不改（见第 7 节） |
| 速率 | 全局 60 req/min/token；登录 5 次/15min/账号；超限 `E_RATE_LIMITED` + `Retry-After` |

### 1.1 幂等性（明确规则）

| 接口类型 | 幂等机制 | 语义 |
|---|---|---|
| 所有 `POST`（产生资源） | **`Idempotency-Key` 必填**，`^[A-Za-z0-9_-]{16,64}$` | 服务端按 `(account_id, idempotency_key)` 唯一索引；同键重放**不执行**，直接返回首次落库的响应体与状态码 |
| `POST /inventories` | `Idempotency-Key` **+ 业务唯一键** `(account_id, device_id, content_sha256)` | 换了 key 但内容相同，仍返回原版本并置 `deduplicated: true`，**不产生新版本号** |
| `POST /devices/register` | `Idempotency-Key` + `(account_id, device_id)` | `upsert`，重复注册 `created: false` |
| `POST /catalog/contributions` | `Idempotency-Key` + `(account_id, device_id, key_hash, payload_hash)` | 同内容重复提交返回同一条 `contribution_id` |
| `GET` / `DELETE` | 天然幂等 | `DELETE` 对不存在资源返回 `200` 且 `deleted: 0` |

未带 `Idempotency-Key` 的 `POST` 一律 `400 E_IDEMPOTENCY_KEY_REQUIRED` —— **不提供「缺失即放行」的降级**，避免重复写库。

## 2. 响应包络与错误码

成功：**`{"ok": true, "data": {...}, "error": null, "request_id": "<uuid4>"}`**
失败：**`{"ok": false, "data": null, "error": {"code": "E_NOT_FOUND", "message": "资源不存在或无权访问", "detail": {"resource": "inventory"}}, "request_id": "<uuid4>"}`**

> **404/403 分工（M0 已定案）**：凡「按 ID 取某个资源」的路径，跨账号与不存在**共用 404 `E_NOT_FOUND`**，响应体逐字节一致；403 `E_FORBIDDEN` 只用于能力规则拒绝（无写权限、`jti` 归属不符）。理由见 `04-isolation.md` §3 的时序侧信道分析。

| `code` | HTTP | 含义 | 客户端动作 |
|---|---|---|---|
| `E_UNAUTHENTICATED` | 401 | 缺 `Authorization` / 格式错 / 签名不符 / 摘要不在库 | 清本地 token，提示 `cloud login` |
| `E_TOKEN_EXPIRED` | 401 | `exp` 已过 | 重新登录（**不自动刷新**，见 3.1） |
| `E_TOKEN_REVOKED` | 401 | `jti` 被吊销（logout 或强制下线） | 重新登录 |
| `E_DEVICE_MISMATCH` | 401 | 请求体/路径的 `device_id` ≠ token 声明的 `did`（**同账号内**） | 修正 `device_id` 或重注册设备 |
| `E_FORBIDDEN` | 403 | **仅用于「已通过归属校验、但操作被能力规则拒绝」**：无 catalog 写权限、`jti` 不属于当前账号、`device_unbound`。**跨账号/跨设备访问资源一律不用 403**（见下行） | 不重试 |
| `E_NOT_FOUND` | 404 | **资源不存在与无权访问共用此码**，响应体完全一致（防枚举侧信道）。跨账号、同账号跨设备、资源确实不存在，三者一律返回 404 `E_NOT_FOUND` | 不重试 |
| `E_VALIDATION` | 400 | 参数非法（缺失/类型错/枚举越界/`items` 空或超限） | 修正请求，不自动重试 |
| `E_IDEMPOTENCY_KEY_REQUIRED` | 400 | 写接口缺 `Idempotency-Key` | 补上重试 |
| `E_IDEMPOTENCY_CONFLICT` | 409 | 同 key 但请求体不同 | 换新 key |
| `E_CONFLICT` | 409 | 业务冲突（邮箱已存、设备已属他人、版本回退），看 `detail.reason` | 按 reason 处理 |
| `E_QUOTA_EXCEEDED` | 429 | 配额超限（设备 > 5、清单版本 > 100/设备、条目 > 2000/清单、贡献 > 50/天） | 不重试 |
| `E_RATE_LIMITED` | 429 | 限流（含登录失败计数） | 按 `Retry-After` 退避 |
| `E_PAYLOAD_TOO_LARGE` | 413 | 请求体超上限 | 裁剪后重试（如不再上报 `install_location`） |
| `E_METHOD_NOT_ALLOWED` | 405 | 路径存在但方法不对 | 修客户端 |
| `E_SCHEMA_UNSUPPORTED` | 400 | 清单 `schema_version` 超过服务端上限 | 降级到支持的版本重报 |
| `E_INTERNAL` | 500 | 未预期错误（含 SQLite 锁超时） | 指数退避重试 1 次 |
| `E_DEPENDENCY_UNAVAILABLE` | 503 | SQLite 不可写 / 磁盘满 / 启动中 | 退避重试，超 3 次转离线模式 |

## 3. 接口清单

| 方法 | 路径（相对 `/api/v1`） | 用途 | 认证 | 幂等 |
|---|---|---|---|---|
| GET | `/health` | 存活探针 | 否 | 天然 |
| POST | `/accounts/register` | 注册账号 | 否 | `Idempotency-Key` + email 唯一 |
| POST | `/accounts/login` | 登录换取 token | 否 | **不幂等**（每次新 `jti`） |
| POST | `/accounts/logout` | 吊销当前 token | 是 | 天然 |
| GET | `/accounts/me` | 查当前账号与配额 | 是 | 天然 |
| POST | `/devices/register` | 设备注册/绑定（重装后复用同一 `device_id`） | 是 | `Idempotency-Key` + `(account,device)` |
| GET | `/devices` | 本账号设备列表 | 是 | 天然 |
| POST | `/devices/{device_id}/heartbeat` | 心跳 | 是 | 天然（覆盖式） |
| DELETE | `/devices/{device_id}` | 解绑设备（级联吊销其 token） | 是 | 天然 |
| POST | `/inventories` | **上报当前机器清单**（schema v2） | 是 | `Idempotency-Key` + `content_sha256` |
| GET | `/inventories` | 拉取指定设备**最新**清单 | 是 | 天然 |
| GET | `/inventories/{inventory_id}` | 拉取指定版本 | 是 | 天然 |
| GET | `/inventories/versions` | **机器清单历史版本**列表 | 是 | 天然 |
| GET | `/catalog/snapshot` | **目录快照**（etag + 增量） | 是 | 天然 |
| GET | `/catalog/entries/{entry_id}` | 查询单个软件 | 是 | 天然 |
| GET | `/catalog/lookup` | 按 `display_name` 查单个软件 | 是 | 天然 |
| POST | `/catalog/contributions` | 提交目录贡献 | 是 | `Idempotency-Key` + payload hash |
| GET | `/catalog/contributions` | 查自己的贡献 | 是 | 天然 |
| POST | `/catalog/resolve` | **批量获取下载决策** | 是 | 天然（只读计算） |
| GET | `/audit/logs` | 查自己的操作日志 | 是 | 天然 |

> 共 20 个端点。**没有** `/download/{id}` 文件流接口 —— 下载决策只返回 JSON（法律边界，见 02 文档第 8 节）。
> `account_id` 前缀统一为 **`acct_`**（与 `04-isolation.md` 一致）；`device_id` 前缀 `dev_`，`inventory_id` 前缀 `inv_`，`entry_id` 前缀 `cat_`。

### 3.1 为什么不提供 refresh token

| 备选 | 结论 |
|---|---|
| access + refresh 双 token | **不做**：单进程 + 本地 CLI，refresh 会多出「refresh 也泄漏」与「轮换竞态」两类问题，收益仅省一次输密码 |
| 长寿命 access token | **不做**：泄漏窗口等于 TTL，与 02 文档 D3 冲突 |
| **选中：单 token，TTL 12h，过期重新登录** | `cloud login` 走 `--username/--password` 或环境变量 `SRC_PASSWORD`；V1 不做「记住凭据」 |

## 4. 详细定义

| # | 接口 | 请求参数 / 请求体 | 成功 | 主要错误 |
|---|---|---|---|---|
| 4.1 | `GET /health`（无认证） | — | 200 | `503 E_DEPENDENCY_UNAVAILABLE`（`db != ok`） |
| 4.2 | `POST /accounts/register`（无认证） | `email` ≤254 唯一、`password` 10–128、`display_name` ≤64（默认 email 前缀） | 201 | `400 E_VALIDATION`、`409 E_CONFLICT`（`reason="email_taken"`）、`429 E_RATE_LIMITED` |
| 4.3 | `POST /accounts/login`（无认证） | `email`、`password`、`device_id`、`device_label` | 200 | `401 E_UNAUTHENTICATED`（**不区分账号是否存在**）、`401 E_DEVICE_MISMATCH`、`429 E_RATE_LIMITED` |
| 4.4 | `POST /accounts/logout` | `jti`、`all_devices` | 200 | `403 E_FORBIDDEN`（`jti` 不属于当前账号 —— 能力拒绝，非资源访问） |
| 4.5 | `GET /accounts/me` | — | 200 | — |
| 4.6 | `POST /devices/register` | 见下方示例 | 200 | `409 E_CONFLICT`（已属他人，**不泄漏对方账号**）、`429 E_QUOTA_EXCEEDED`、`400 E_VALIDATION` |
| 4.7 | `GET /devices` | `limit,cursor` | 200 | — |
| 4.8 | `POST /devices/{device_id}/heartbeat` | `agent_version`、`inventory_dirty` | 200 | `401 E_DEVICE_MISMATCH`、`404 E_NOT_FOUND`（设备不属于当前账号） |
| 4.9 | `DELETE /devices/{device_id}` | — | 200 | `404 E_NOT_FOUND`（设备不属于当前账号） |
| 4.10 | `POST /inventories`（核心） | 见 4.10 | 201 | `400 E_VALIDATION`、`400 E_SCHEMA_UNSUPPORTED`、`401 E_DEVICE_MISMATCH`、`409 E_IDEMPOTENCY_CONFLICT`、`413 E_PAYLOAD_TOO_LARGE`、`429 E_QUOTA_EXCEEDED`（版本 > 100） |
| 4.11 | `GET /inventories`（核心） | `device_id`（必填）、`version`、`include_items`（默认 true）、`items_limit`（默认 500） | 200 | `404 E_NOT_FOUND`（同账号无清单 / `device_id` 不属于当前账号，两者不区分） |
| 4.12 | `GET /inventories/{inventory_id}`、`GET /inventories/versions` | `device_id,limit,cursor` | 200 | `404 E_NOT_FOUND`（不存在、跨账号、跨设备三者一致） |
| 4.13 | `GET /catalog/snapshot`（核心） | `If-None-Match`、`since_seq`、`limit` | 200 / **304** | `400 E_VALIDATION`（`since_seq` > 当前 `change_seq`） |
| 4.14 | `GET /catalog/entries/{entry_id}`、`GET /catalog/lookup` | `display_name` | 200 | `404 E_NOT_FOUND`（不存在或 private 且非本人，不区分） |
| 4.15 | `POST /catalog/contributions`、`GET /catalog/contributions` | `key_hash`、`entry`、`scope`、`note` | 201 | `400 E_VALIDATION`（`url` 与 `winget_id` 都空；`sha256` 非 64 hex）、`409 E_CONFLICT`、`429 E_QUOTA_EXCEEDED`（> 50/天） |
| 4.16 | `POST /catalog/resolve` | `device_id`、`items[]`（≤ 200） | 200 | `400 E_VALIDATION`、`404 E_NOT_FOUND`（`device_id` 不属于当前账号） |
| 4.17 | `GET /audit/logs` | `action,from,to,limit,cursor` | 200 | — |

### 4.1 ~ 4.9 请求与响应示例

**4.1** `{"request_id": "a1b2c3d4-0000-4000-8000-000000000001", "ok": true, "error": null, "data": {"status": "up", "version": "1.0.0", "schema_max": 2, "db": "ok", "uptime_s": 4213}}`

**4.2 请求** → **响应 201**（**首个注册账号自动获得 `role=owner`（可审核目录贡献），其后默认 `member`**）

```json
{"email": "hdturk@example.com", "password": "Str0ng-Passphrase-Example", "display_name": "hdturk"}
```

```json
{"request_id": "a1b2c3d4-0000-4000-8000-000000000002", "ok": true, "error": null, "data": {"account_id": "acct_01HQ2X3Y4Z5A6B7C8D9E0F1G2H", "email": "hdturk@example.com", "display_name": "hdturk", "role": "owner", "created_at": "2026-11-15T14:20:00Z"}}
```

**4.3 请求** → **响应 200**

```json
{"email": "hdturk@example.com", "password": "Str0ng-Passphrase-Example", "device_id": "dev_7f3a9c21b4e5", "device_label": "ThinkPad-X1"}
```

```json
{"request_id": "...", "ok": true, "error": null, "data": {"token": "<JWT>", "token_type": "Bearer", "expires_at": "2026-11-16T02:20:00Z", "account": {"account_id": "acct_01HQ2X3Y4Z5A6B7C8D9E0F1G2H", "email": "hdturk@example.com", "role": "owner"}, "device": {"device_id": "dev_7f3a9c21b4e5", "status": "active"}, "jti": "5c1f0e83-7a4b-4c39-9a10-2b6f7e8d9c01"}}
```

服务端行为：① 按 `email` 取 `accounts`，`scrypt` 校验 `password_hash`，失败计数入库（5 次/15 分钟）；② 签发 HS256 JWT，claims 为 `{"iss":"software-reback-cloud","sub":"<account_id>","did":"<device_id>","jti":"<uuid4>","iat":...,"exp":...}`；③ **`tokens` 表只写 `sha256(raw_token)`、`jti`、`account_id`、`device_id`、`expires_at`，不落原文** —— 拖库或备份泄漏也拿不到可用凭证，服务端也无法「重新显示」token（02 文档 D9）；④ 返回给客户端的 `token` 是唯一一份原文。

**4.4 ~ 4.9 响应**（按接口取子集：logout→`revoked`；delete→`deleted`+`revoked_tokens`；heartbeat→`last_seen_at`+`server_time`；register→`created`+`first_seen_at`）
`DELETE` 级联吊销该设备全部 token，`inventories` 保留但置 `device_deleted=1`。

```json
{"request_id": "...", "ok": true, "error": null, "data": {"revoked": 1, "deleted": 1, "revoked_tokens": 3, "device_id": "dev_7f3a9c21b4e5", "label": "ThinkPad-X1", "status": "active", "created": false, "first_seen_at": "2026-11-15T14:25:00Z", "last_seen_at": "2026-11-15T14:30:00Z", "server_time": "2026-11-15T14:30:00Z"}}
```

**4.5** `{"request_id": "...", "ok": true, "error": null, "data": {"account_id": "acct_01HQ2X3Y4Z5A6B7C8D9E0F1G2H", "email": "hdturk@example.com", "display_name": "hdturk", "role": "owner", "device_count": 2, "capabilities": {"schema_max": 2, "catalog_incremental": true}, "quota": {"max_devices": 5, "max_inventories_per_device": 100, "max_items_per_inventory": 2000}}}`

**4.6 请求**（重装后指纹不变，是 `upsert`；首次 `created:true`）

```json
{"device_id": "dev_7f3a9c21b4e5", "label": "ThinkPad-X1", "os": "Windows 11 Pro 26H2", "os_version": "10.0.26200", "arch": "x64", "hostname": "X1-CARBON", "fingerprint_algo": "sha256(machineguid+machineguid_uuid+volume_serial)", "agent_version": "0.2.0"}
```

**4.7 `GET /devices` 响应 200**

```json
{"request_id": "...", "ok": true, "error": null, "data": {"items": [{"device_id": "dev_7f3a9c21b4e5", "label": "ThinkPad-X1", "os": "Windows 11 Pro 26H2", "status": "active", "last_seen_at": "2026-11-15T14:25:00Z", "latest_inventory_id": "inv_01HQ3A", "latest_inventory_at": "2026-11-15T14:26:11Z"}], "page": {"limit": 50, "next_cursor": null, "has_more": false}}}
```

**4.8 心跳请求** `{"agent_version": "0.2.0", "inventory_dirty": false}`

### 4.10 `POST /inventories`（清单上报，核心）

请求头需带 `Authorization`、`Idempotency-Key`（16–64 位）、`Content-Type`。

```json
{"schema_version": 2, "device_id": "dev_7f3a9c21b4e5", "generated_at": "2026-11-15T14:26:11+08:00", "client": {"agent": "software-reback", "agent_version": "0.2.0", "platform": "windows", "winget_version": "v1.29.380"}, "source_summary": {"registry_count": 55, "export_count": 52, "export_errors": 8}, "os": {"name": "Windows 11 Pro", "version": "10.0.26200", "arch": "x64"}, "items": [{"index": 0, "display_name": "Notepad++ (64-bit x64)", "version": "8.9.8.1", "publisher": "Notepad++ Team", "install_date": "2026-03-02", "scope": "machine", "architecture": "x64", "registry_key": "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Notepad++", "source": "registry", "export_id": "Notepad++.Notepad++", "export_source": "winget", "winget_match": "export", "catalog_entry_id": null}, {"index": 1, "display_name": "微信", "version": "3.9.12.17", "publisher": "Tencent Technology(Shenzhen) Company Limited", "install_date": "", "scope": "machine", "architecture": "x64", "registry_key": "HKLM\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\WeChat", "source": "registry", "export_id": "Tencent.WeChat", "export_source": "winget", "winget_match": "export", "catalog_entry_id": "cat_01HQ9Z"}, {"index": 2, "display_name": "NVIDIA 图形驱动程序 566.03", "version": "566.03", "publisher": "NVIDIA Corporation", "install_date": "", "scope": "machine", "architecture": "x64", "registry_key": "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{B2FE1952-0186-46C3-BAEC-A80AA35AC5B8}", "source": "registry", "export_id": "", "export_source": "", "winget_match": "none", "catalog_entry_id": null}]}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `schema_version` | int | 是 | v2 固定 `2`；服务端接受 1、2 |
| `device_id` | string | 是 | **必须等于 token 的 `did`**，否则 `E_DEVICE_MISMATCH` |
| `generated_at` | string | 是 | 采集时间（ISO 8601） |
| `client.winget_version` | string | 否 | 排查识别覆盖率漂移 |
| `source_summary.export_count` | int | 否 | `winget export` 命中条数（本机实测 52） |
| `items[].export_id` | string | **强烈建议** | **`winget export` 的精确 `PackageIdentifier`**；识别率 25.5% → **90.9%（50/55）** 的关键列，必须独立成列，不得合并进 `display_name` |
| `items[].winget_match` | enum | 是 | `export`（精确）/ `name`（名称兜底）/ `contrib`（目录贡献）/ `none` |
| `items[].source` | enum | 是 | 与现有 `SoftwareRecord.source` 一致：`registry` / `winget` / `store` |
| `items[].scope` | enum | 否 | `machine` / `user`（对应 HKLM / HKCU） |
| `items[].install_location` | string | 否 | **默认不上报**（含用户名路径，属隐私） |
| `items[].package_id` | string | 否 | 兼容 v1 字段名，等价于 `export_id`（两者取一存入 `export_id`） |

```json
{"request_id": "...", "ok": true, "error": null, "data": {"inventory_id": "inv_01HQ3A4B5C6D7E8F9G0H1J2K3M", "device_id": "dev_7f3a9c21b4e5", "version": 7, "created_at": "2026-11-15T14:26:12Z", "content_sha256": "3f8a1d2c9b4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8", "items_count": 55, "resolved_count": 50, "unresolved_count": 5, "deduplicated": false, "ignored_fields": []}}
```

服务端处理顺序（单事务 `BEGIN IMMEDIATE`）：① 认证取 `(account_id, device_id)` 并校验 body 的 `device_id` 一致；② 校验 `items` 数量 1–2000，计算 `content_sha256`（每个 item 按字段名升序序列化为 `json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`，**数组按上报顺序**拼接后取 `sha256(...).hexdigest()`，算法须两端一致）；③ `(account_id, device_id, content_sha256)` 已存在则返回既有版本 + `deduplicated: true`，不新增行；④ 否则 `version = COALESCE(MAX(version),0)+1`，写 `inventories` + N 行 `inventory_items`；⑤ 写 `audit_logs(action='inventory.push', target=inventory_id)`。

### 4.11 `GET /inventories`（清单拉取，核心）

```json
{"request_id": "...", "ok": true, "error": null, "data": {"inventory_id": "inv_01HQ3A4B5C6D7E8F9G0H1J2K3M", "device_id": "dev_7f3a9c21b4e5", "version": 7, "is_latest": true, "schema_version": 2, "generated_at": "2026-11-15T06:26:11Z", "created_at": "2026-11-15T14:26:12Z", "content_sha256": "3f8a1d2c9b4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8", "items_count": 55, "items": [{"index": 0, "display_name": "Notepad++ (64-bit x64)", "version": "8.9.8.1", "publisher": "Notepad++ Team", "export_id": "Notepad++.Notepad++", "export_source": "winget", "winget_match": "export", "source": "registry", "scope": "machine", "architecture": "x64", "catalog_entry_id": null}, {"index": 1, "display_name": "微信", "version": "3.9.12.17", "publisher": "Tencent Technology(Shenzhen) Company Limited", "export_id": "Tencent.WeChat", "export_source": "winget", "winget_match": "export", "source": "registry", "scope": "machine", "architecture": "x64", "catalog_entry_id": "cat_01HQ9Z"}], "page": {"limit": 500, "next_cursor": "eyJpIjo1MDB9", "has_more": true}}}
```

**4.12 `GET /inventories/versions?device_id=...&limit=20&cursor=`**（`/{inventory_id}` 响应结构同 4.11）

```json
{"request_id": "...", "ok": true, "error": null, "data": {"items": [{"version": 7, "inventory_id": "inv_01HQ3A4B5C6D7E8F9G0H1J2K3M", "items_count": 55, "resolved_count": 50, "created_at": "2026-11-15T14:26:12Z"}, {"version": 6, "inventory_id": "inv_01HQ2Z9Y8X7", "items_count": 53, "resolved_count": 48, "created_at": "2026-11-01T09:02:44Z"}], "page": {"limit": 20, "next_cursor": null, "has_more": false}}}
```

### 4.13 `GET /catalog/snapshot`（目录快照，核心）

未变更 → `304 Not Modified`（无 body）；有变更 → `200` + `ETag: "catv12-3f8a1d2c"`。

```json
{"request_id": "...", "ok": true, "error": null, "data": {"catalog_version": 12, "etag": "catv12-3f8a1d2c", "updated_at": "2026-11-15T13:00:00Z", "change_seq": 1487, "count": 3, "entries": [{"entry_id": "cat_01HQ9Z", "display_name": "微信", "normalized_name": "微信", "publisher": "Tencent", "url": "https://dldir1.qq.com/weixin/Windows/WeChatSetup.exe", "file_name": "WeChatSetup.exe", "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", "winget_id": "", "silent_args": "/S", "architecture": "x64", "scope": "public", "status": "approved", "confidence": 0.95, "health": "healthy", "last_verified_at": "2026-11-14T20:00:00Z", "contributor_account_id": "acct_01HQ2X3Y4Z5A6B7C8D9E0F1G2H", "sources": ["manual"], "change_seq": 1487}, {"entry_id": "cat_01HQ9Y", "display_name": "NVIDIA App", "normalized_name": "nvidia app", "publisher": "NVIDIA", "url": "", "file_name": "", "sha256": "", "winget_id": "Nvidia.App", "silent_args": "-s", "architecture": "x64", "scope": "public", "status": "approved", "confidence": 0.9, "health": "healthy", "last_verified_at": "2026-11-10T00:00:00Z", "contributor_account_id": "acct_01HQ2X3Y4Z5A6B7C8D9E0F1G2H", "sources": ["winget_export", "manual"], "change_seq": 1466}, {"entry_id": "cat_01HQ9X", "display_name": "Office 专业增强版 2019", "normalized_name": "office 专业增强版 2019", "publisher": "Microsoft", "url": "https://example.com/office2019.img", "file_name": "office2019.img", "sha256": "", "winget_id": "", "silent_args": "/configure config.xml", "architecture": "x64", "scope": "private", "status": "pending", "confidence": 0.4, "health": "unknown", "last_verified_at": null, "contributor_account_id": "acct_01HQ2X3Y4Z5A6B7C8D9E0F1G2H", "sources": ["manual"], "change_seq": 1471}]}}
```

增量响应（`since_seq` 模式）把 `entries` 换成 `upserts` + `deletions`：

```json
{"request_id": "...", "ok": true, "error": null, "data": {"catalog_version": 12, "etag": "catv12-3f8a1d2c", "updated_at": "2026-11-15T13:00:00Z", "from_seq": 1460, "to_seq": 1487, "upserts": [{"entry_id": "cat_01HQ9Z", "display_name": "微信", "status": "approved", "change_seq": 1487}], "deletions": [{"entry_id": "cat_01HQ7A", "change_seq": 1480}]}}
```

规则：`private` 条目**只对 `contributor_account_id` 可见**（隔离，他人拿到 `entry_id` 也是 **404 `E_NOT_FOUND`**，与「条目不存在」不可区分）；`pending` 公共条目仍下发但客户端**默认不自动下载**（报告里列「待确认」）；`sources` 是派生字段（来自 `catalog_entry_sources`），不单独存。

**4.14 `GET /catalog/entries/{entry_id}` / `GET /catalog/lookup?display_name=...`** —— 单条结构同 4.13 的元素；lookup 归一化后精确匹配，未命中返回 `null` 而非 404（便于批量查询）。

```json
{"request_id": "...", "ok": true, "error": null, "data": {"match": "exact", "entry": {"entry_id": "cat_01HQ9Z", "display_name": "微信", "status": "approved"}}}
```

**4.15 `POST /catalog/contributions`** —— `key_hash` = `sha256(normalized_name + "|" + architecture)[:16]`，客户端算、服务端复算；`normalized_name` 复用现有 `catalog.normalize_name` 规则（折叠空白、去括号说明、去尾部版本号、`casefold`）。

```json
{"key_hash": "9a8b7c6d5e4f3021", "entry": {"display_name": "微信", "publisher": "Tencent", "url": "https://dldir1.qq.com/weixin/Windows/WeChatSetup.exe", "file_name": "WeChatSetup.exe", "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", "winget_id": "", "silent_args": "/S", "architecture": "x64"}, "scope": "public", "note": "官方直链，实测 2026-11-14 可下载"}
```

```json
{"request_id": "...", "ok": true, "error": null, "data": {"contribution_id": "con_01HQAA", "entry_id": "cat_01HQAZ", "status": "pending", "scope": "public", "created_at": "2026-11-15T14:40:00Z"}}
```

### 4.16 `POST /catalog/resolve`（下载决策，核心）

```json
{"device_id": "dev_7f3a9c21b4e5", "items": [{"display_name": "微信", "version": "3.9.12.17", "export_id": "Tencent.WeChat", "source": "registry"}, {"display_name": "NVIDIA 图形驱动程序 566.03", "version": "566.03", "export_id": "", "source": "registry"}]}
```

```json
{"request_id": "...", "ok": true, "error": null, "data": {"decisions": [{"display_name": "微信", "decision_id": "dec_01HQAB", "method": "url", "url": "https://dldir1.qq.com/weixin/Windows/WeChatSetup.exe", "file_name": "WeChatSetup.exe", "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", "winget_id": "", "match": "catalog_exact", "confidence": 0.95, "health": "healthy", "requires_hash_check": true}, {"display_name": "NVIDIA 图形驱动程序 566.03", "decision_id": "dec_01HQAC", "method": "unresolved", "url": "", "file_name": "", "sha256": "", "winget_id": "", "match": "none", "confidence": 0.0, "health": "unknown", "reason": "无目录条目，且 export_id 为空（进入人工清单）"}], "summary": {"total": 2, "url": 1, "winget": 0, "unresolved": 1}}}
```

决策优先级（与 02 文档 D5 一致）：`export_id` 精确 → 目录 `display_name` 归一化 → 目录的 `winget_id` → 名称匹配（**服务端不做，交给客户端**）→ `unresolved`。
`method=url` 时 `requires_hash_check=true`：**客户端必须校验 `sha256`**，为空则拒绝下载（与 `downloader.download_url` 现有语义一致）。

**4.17 `GET /audit/logs`** —— **只能查到 `account_id = sub` 的记录。**

```json
{"request_id": "...", "ok": true, "error": null, "data": {"items": [{"log_id": 9123, "account_id": "acct_01HQ2X3Y4Z5A6B7C8D9E0F1G2H", "device_id": "dev_7f3a9c21b4e5", "action": "inventory.push", "target": "inv_01HQ3A4B5C6D7E8F9G0H1J2K3M", "result": "ok", "request_id": "a1b2c3d4-0000-4000-8000-000000000009", "created_at": "2026-11-15T14:26:12Z"}], "page": {"limit": 50, "next_cursor": null, "has_more": false}}}
```

`action` 枚举：`account.register` / `account.login` / `account.logout` / `device.register` / `device.delete` / `device.heartbeat` / `inventory.push` / `inventory.read` / `catalog.read` / `catalog.contribute` / `catalog.resolve` / `audit.read`。

## 5. 数据模型（SQLite DDL）

隔离约定：**每张含用户数据的表都必须有 `account_id`**，设备级资源另加 `device_id`；外键显式声明 `ON DELETE`。

```sql
PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 5000;
PRAGMA cache_size = -16000;  -- 16MB，配合 100MB 内存预算

-- 账号
CREATE TABLE accounts (
  account_id TEXT PRIMARY KEY,                  -- 'acct_' + ulid
  email TEXT NOT NULL COLLATE NOCASE,
  password_hash TEXT NOT NULL,                   -- scrypt$n$r$p$salt$hash，绝不存明文
  display_name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner','member')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  created_at TEXT NOT NULL, last_login_at TEXT);
CREATE UNIQUE INDEX ux_accounts_email ON accounts(email COLLATE NOCASE);

-- 设备（隔离字段：account_id + device_id）
CREATE TABLE devices (
  device_id TEXT NOT NULL,                        -- 'dev_' + 指纹前 16 hex
  account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
  label TEXT NOT NULL DEFAULT '', os TEXT NOT NULL DEFAULT '', os_version TEXT NOT NULL DEFAULT '',
  arch TEXT NOT NULL DEFAULT '', hostname TEXT NOT NULL DEFAULT '',
  fingerprint_algo TEXT NOT NULL DEFAULT '', agent_version TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','deleted')),
  first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
  PRIMARY KEY (account_id, device_id));           -- 归属校验的第一道门
CREATE UNIQUE INDEX ux_devices_id_global ON devices(device_id);  -- 防跨账号复用同一指纹

-- token：只存 SHA256 摘要，不存原文（威胁缓解：拖库不可重放）
CREATE TABLE tokens (
  jti TEXT PRIMARY KEY,                           -- uuid4，等同 token id
  account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
  device_id TEXT NOT NULL,
  token_sha256 TEXT NOT NULL,                     -- sha256(raw_token) hex，唯一
  issued_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT, last_used_at TEXT,
  FOREIGN KEY (account_id, device_id) REFERENCES devices(account_id, device_id) ON DELETE CASCADE);
CREATE UNIQUE INDEX ux_tokens_sha ON tokens(token_sha256);
CREATE INDEX ix_tokens_owner ON tokens(account_id, device_id, expires_at);

-- 清单版本
CREATE TABLE inventories (
  inventory_id TEXT PRIMARY KEY,                  -- 'inv_' + ulid
  account_id TEXT NOT NULL, device_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  schema_version INTEGER NOT NULL CHECK (schema_version IN (1,2)),
  content_sha256 TEXT NOT NULL,
  generated_at TEXT NOT NULL, created_at TEXT NOT NULL,
  client_meta TEXT NOT NULL DEFAULT '{}',         -- JSON：winget_version 等
  source_summary TEXT NOT NULL DEFAULT '{}',      -- JSON：registry_count / export_count
  os_meta TEXT NOT NULL DEFAULT '{}',
  items_count INTEGER NOT NULL DEFAULT 0, resolved_count INTEGER NOT NULL DEFAULT 0,
  unresolved_count INTEGER NOT NULL DEFAULT 0, device_deleted INTEGER NOT NULL DEFAULT 0,
  idempotency_key TEXT,
  FOREIGN KEY (account_id, device_id) REFERENCES devices(account_id, device_id) ON DELETE CASCADE);
CREATE UNIQUE INDEX ux_inv_version ON inventories(account_id, device_id, version);
CREATE UNIQUE INDEX ux_inv_content ON inventories(account_id, device_id, content_sha256); -- 业务唯一键
CREATE INDEX ix_inv_latest ON inventories(account_id, device_id, version DESC);

-- 清单条目：export_id 是关键列（识别率 25.5% → 90.9%）
CREATE TABLE inventory_items (
  item_id INTEGER PRIMARY KEY AUTOINCREMENT,
  inventory_id TEXT NOT NULL REFERENCES inventories(inventory_id) ON DELETE CASCADE,
  account_id TEXT NOT NULL, device_id TEXT NOT NULL,       -- 冗余隔离列，便于单表越权校验
  idx INTEGER NOT NULL,                                    -- idx = 上报时的 items[].index
  display_name TEXT NOT NULL, normalized_name TEXT NOT NULL, -- 后者由服务端归一化计算
  version TEXT NOT NULL DEFAULT '', publisher TEXT NOT NULL DEFAULT '', install_date TEXT NOT NULL DEFAULT '',
  scope TEXT NOT NULL DEFAULT 'machine' CHECK (scope IN ('machine','user')),
  architecture TEXT NOT NULL DEFAULT '', registry_key TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'registry',
  export_id TEXT NOT NULL DEFAULT '',                      -- winget export 的 PackageIdentifier；v1 的 package_id 落这里
  export_source TEXT NOT NULL DEFAULT '',                  -- winget / msstore
  winget_match TEXT NOT NULL DEFAULT 'none' CHECK (winget_match IN ('export','name','contrib','none')),
  catalog_entry_id TEXT REFERENCES catalog_entries(entry_id) ON DELETE SET NULL,
  install_location TEXT NOT NULL DEFAULT '',               -- 默认空：隐私
  UNIQUE (inventory_id, idx));
CREATE INDEX ix_items_inv ON inventory_items(account_id, device_id, inventory_id);
CREATE INDEX ix_items_export ON inventory_items(export_id) WHERE export_id <> '';

-- 目录条目（private / pending 条目只对贡献人可见）
CREATE TABLE catalog_entries (
  entry_id TEXT PRIMARY KEY,                      -- 'cat_' + ulid
  key_hash TEXT NOT NULL,                         -- sha256(normalized_name + '|' + architecture)[:16]
  display_name TEXT NOT NULL, normalized_name TEXT NOT NULL,
  publisher TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', file_name TEXT NOT NULL DEFAULT '',
  sha256 TEXT NOT NULL DEFAULT '',                -- 空 = 不可下载（强制客户端拒绝）
  winget_id TEXT NOT NULL DEFAULT '', silent_args TEXT NOT NULL DEFAULT '', architecture TEXT NOT NULL DEFAULT 'x64',
  scope TEXT NOT NULL DEFAULT 'public' CHECK (scope IN ('public','private')),
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  confidence REAL NOT NULL DEFAULT 0.0 CHECK (confidence >= 0 AND confidence <= 1),
  health TEXT NOT NULL DEFAULT 'unknown' CHECK (health IN ('healthy','degraded','dead','unknown')),
  last_verified_at TEXT,                          -- NULL = 从未校验
  contributor_account_id TEXT REFERENCES accounts(account_id) ON DELETE SET NULL,
  catalog_version INTEGER NOT NULL DEFAULT 0,     -- 最近一次变更所属版本
  change_seq INTEGER NOT NULL DEFAULT 0,          -- 全局单调，用于增量
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  CHECK (url <> '' OR winget_id <> ''));          -- 至少一个来源
CREATE UNIQUE INDEX ux_cat_key_owner ON catalog_entries(scope, contributor_account_id, key_hash);
CREATE UNIQUE INDEX ux_cat_public_approved ON catalog_entries(key_hash)  -- 同一软件只能一条已批准
  WHERE scope = 'public' AND status = 'approved';
CREATE INDEX ix_cat_norm ON catalog_entries(normalized_name, status);
CREATE INDEX ix_cat_seq ON catalog_entries(change_seq);

-- 目录来源（派生 `sources` 字段；同一 key 可被多条路径共同证实）
CREATE TABLE catalog_entry_sources (
  entry_id TEXT NOT NULL REFERENCES catalog_entries(entry_id) ON DELETE CASCADE,
  account_id TEXT,                                -- 贡献者；manual 必填，自动采集可为空
  source TEXT NOT NULL CHECK (source IN ('manual','winget_export','registry')),
  evidence TEXT NOT NULL DEFAULT '',              -- 例如导出机器数、命中次数
  seen_at TEXT NOT NULL,
  PRIMARY KEY (entry_id, source, account_id));

-- 目录版本（etag 来源）
CREATE TABLE catalog_versions (
  catalog_version INTEGER PRIMARY KEY,
  etag TEXT NOT NULL UNIQUE,                      -- 'catv12-3f8a1d2c'
  change_seq INTEGER NOT NULL, entry_count INTEGER NOT NULL, published_at TEXT NOT NULL,
  published_by TEXT REFERENCES accounts(account_id) ON DELETE SET NULL);

-- 审计（只追加，无 UPDATE/DELETE 路径）
CREATE TABLE audit_logs (
  log_id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id TEXT NOT NULL, device_id TEXT,       -- 有 device_id 的可按机过滤
  action TEXT NOT NULL, target TEXT NOT NULL DEFAULT '',
  result TEXT NOT NULL,                           -- ok / denied / error
  error_code TEXT NOT NULL DEFAULT '', request_id TEXT NOT NULL,
  ip TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE INDEX ix_audit_owner ON audit_logs(account_id, created_at DESC);
```

**归属校验必需的字段**（实现时必须逐条落到 `WHERE`）：

| 校验 | SQL 谓词 |
|---|---|
| 账号归属 | `WHERE account_id = ?`（`?` = token `sub`） |
| 设备归属 | `WHERE account_id = ? AND device_id = ?`，命中 0 行 → `E_NOT_FOUND`（404，不用 403） |
| token 归属 | `WHERE token_sha256 = ? AND revoked_at IS NULL AND expires_at > ?` |
| 私有目录隔离 | `WHERE (scope = 'public' AND status = 'approved') OR contributor_account_id = ?` |
| 清单条目越权 | `WHERE account_id = ? AND device_id = ? AND inventory_id = ?` |

## 6. 清单 schema v2

| v1 字段（现有 `software.json`） | v2 位置 | 兼容策略 |
|---|---|---|
| `schema_version: 1` | `schema_version: 2` | 服务端接受 1、2；v1 入库前走 6.1 迁移 |
| `software[]` / `name` | `items[]` / `items[].display_name` | 迁移时改名 |
| `version` / `publisher` / `install_location` / `source` | 同名保留 | `install_location` 入库前**清空**（隐私默认） |
| `package_id` | `items[].export_id` | 非空时 `winget_match='name'`（v1 的 ID 来自名称匹配），否则 `none` |
| — | `items[].index` / `scope` / `architecture` / `registry_key` | 默认 `下标` / `machine` / `""` / `""` |
| — | `export_source` / `winget_match` / `catalog_entry_id` | 默认 `""` / 见上 / `null` |
| — | `device_id` / `client` / `source_summary` / `os` | `device_id` 由请求上下文补，其余给 `{}` |

### 6.1 v1 → v2 迁移（服务端入库前，幂等；客户端 `store.load_inventory()` 同规则补齐）

```python
def migrate_v1_to_v2(v1: dict, device_id: str) -> dict:
    items = []
    for i, rec in enumerate(v1.get("software") or []):
        pid = str(rec.get("package_id") or "").strip()
        items.append({
            "index": i, "display_name": rec.get("name", ""), "version": rec.get("version", ""),
            "publisher": rec.get("publisher", ""), "install_date": "", "scope": "machine",
            "architecture": "", "registry_key": "", "source": rec.get("source", "registry"),
            "export_id": pid, "export_source": "winget" if pid else "",
            "winget_match": "name" if pid else "none", "catalog_entry_id": None,
        })
    return {"schema_version": 2, "device_id": device_id, "generated_at": v1.get("generated_at"),
            "client": {"agent": "software-reback", "migrated_from": 1},
            "source_summary": {"registry_count": len(items), "export_count": 0, "export_errors": 0},
            "os": {}, "items": items}
```

v2 完整示例见 4.10（3 条覆盖三类：export 命中、export 命中且有目录条目、完全 unresolved）。

## 7. 版本与兼容

| 规则 | 说明 |
|---|---|
| 路径版本 | `/api/v1`；破坏性变更才开 `/api/v2`，v1 至少并行 6 个月 |
| 字段只增不改 | 只加字段，不改语义、不改类型、不删字段；**客户端必须忽略未知字段** |
| 枚举扩展 | `source` / `winget_match` / `method` / `health` 可新增值；客户端遇未知值按「未知」处理，不报错 |
| 错误码扩展 | 未知 `E_*` 一律按「不可重试」处理并打印 `code` |
| 能力声明 | `GET /accounts/me` 的 `capabilities` 告诉客户端可用能力 |
| 客户端降级 | `schema_max < 2` → 发 v1 形态并提示升级；`catalog_incremental=false` → 全量拉快照 |
| 云端不可用降级 | 连接失败 / `E_DEPENDENCY_UNAVAILABLE` / `503` → 离线模式，只读本地 `software.json` + `catalog.json`（02 文档 D10） |
| `User-Agent` | 客户端必须发 `software-reback/0.2.0 (windows)`，服务端据此统计与灰度 |
| 弃用告警 | 弃用接口在响应头 `Sunset: Wed, 01 Apr 2026 00:00:00 GMT` 标注，并写入 `audit_logs` |

## 8. 一页速查表

| # | 方法 | 路径 | 认证 | 关键参数 | 成功码 | 幂等键 |
|---|---|---|---|---|---|---|
| 1 | GET | `/health` | — | — | 200 | — |
| 2 | POST | `/accounts/register` | — | `email,password,display_name` | 201 | `Idempotency-Key` |
| 3 | POST | `/accounts/login` | — | `email,password,device_id,device_label` | 200 | 否（新 `jti`） |
| 4 | POST | `/accounts/logout` | ✓ | `jti,all_devices` | 200 | 天然 |
| 5 | GET | `/accounts/me` | ✓ | — | 200 | — |
| 6 | POST | `/devices/register` | ✓ | `device_id,label,os,arch,fingerprint_algo` | 200 | `Idempotency-Key` |
| 7 | GET | `/devices` | ✓ | `limit,cursor` | 200 | — |
| 8 | POST | `/devices/{device_id}/heartbeat` | ✓ | `agent_version` | 200 | 天然 |
| 9 | DELETE | `/devices/{device_id}` | ✓ | — | 200 | 天然 |
| 10 | POST | `/inventories` | ✓ | `schema_version=2,items[]`（含 `export_id`） | 201 | `Idempotency-Key` + `content_sha256` |
| 11 | GET | `/inventories` | ✓ | `device_id,version?,include_items` | 200 | — |
| 12 | GET | `/inventories/{inventory_id}` | ✓ | `include_items` | 200 | — |
| 13 | GET | `/inventories/versions` | ✓ | `device_id,limit,cursor` | 200 | — |
| 14 | GET | `/catalog/snapshot` | ✓ | `If-None-Match,since_seq,limit` | 200 / 304 | — |
| 15 | GET | `/catalog/entries/{entry_id}` | ✓ | — | 200 | — |
| 16 | GET | `/catalog/lookup` | ✓ | `display_name` | 200 | — |
| 17 | POST | `/catalog/contributions` | ✓ | `key_hash,entry,scope,note` | 201 | `Idempotency-Key` |
| 18 | GET | `/catalog/contributions` | ✓ | `status,limit,cursor` | 200 | — |
| 19 | POST | `/catalog/resolve` | ✓ | `device_id,items[]`（≤200） | 200 | 天然（只读） |
| 20 | GET | `/audit/logs` | ✓ | `action,from,to,limit,cursor` | 200 | — |

**客户端最小实现顺序**：`login` → `devices/register` → `inventories`(POST)；重装后 `inventories`(GET) → `catalog/snapshot` → `catalog/resolve` → 复用现有 `download`。
