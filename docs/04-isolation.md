# 04 隔离设计（M3）与越权自动验证

> 归属：子任务 C。上游约束见 `PLAN-SPLIT.md`，接口契约见 `03-api-contract.md`（本文件不重复定义 JSON 字段，只引用）。
> 一句话结论：**隔离不是「代码里记得加 `where`」，而是「不加 `where` 就查不出数据」**——用 SQLite 约束 + 统一 `assert_owned` + 35 条越权矩阵用例（+1 条并发用例）把越权堵死，且可一条命令复现。

## 0. 前提与不变量

| 项 | 取值（已确认，不得改动） | 对本设计的影响 |
|---|---|---|
| 运行形态 | notebook 上的**单进程 HTTP 服务 + SQLite**，由 **systemd --user** 托管，**不使用 Docker** | 无跨进程锁问题；但 `ThreadingHTTPServer` 有**并发**问题，隔离必须做在「每请求独立连接」层面；测试不得依赖容器编排 |
| Linger | **`Linger=no`**（实测 `loginctl show-user hdturk`）→ 重启后用户级服务**不会自动拉起** | 见 0.1 部署风险：验收测试不能假设服务常驻 |
| 监听 | `0.0.0.0:8084`（预留 8081–8089，frp 已映射） | 本机测试一律绑 `127.0.0.1:0` 随机端口，不占用 8084 |
| 存储 | 单文件 SQLite（WAL 模式） | 所有隔离条件必须下推到 SQL，应用层过滤只能作为第二道 |
| 认证 | `Authorization: Bearer <token>`，token 绑定 `(account_id, device_id)`；**不使用 session cookie** | 身份只来自 token，**绝不来自请求体**；无 Cookie 即无 CSRF 面、无跨设备 Cookie 串用面 |
| 资源键 | `(account_id, device_id, resource_id)` | 清单归属设备；账号只做「聚合与列举」 |
| 客户端 | 现有 CLI（`src/software_reback/`），`unittest` + 依赖注入风格 | 新测试沿用 `sys.path.insert(src)` + 可注入函数，零第三方依赖 |
| 出网 | notebook 不能访问 github / CDN，pypi 可用 | 测试**不联网**、不依赖真实 notebook，全部本地 `127.0.0.1` 起服务 |

### 0.1 部署风险：`Linger=no` 对隔离验收的影响

| 项 | 说明 |
|---|---|
| 风险 | 用户级 systemd 服务随登录会话存活；notebook 重启（掉电、内核升级）后**服务不会自动拉起**，端口 8084 不再监听 |
| 对测试的影响 | 验收**不得**假设「服务一直在跑」。所有隔离用例在 `setUpClass` 内**自建进程内服务端**（`127.0.0.1` 随机端口），与 notebook 上是否常驻无关；需要打真实 notebook 的冒烟测试必须显式标注为「前置条件：服务已手动拉起」，失败原因记为 `service_unavailable` 而不是「隔离失败」 |
| 对隔离语义的影响 | 服务不可达时客户端**必须失败关闭**：拿不到 token/清单就报错退出，**绝不**回落到「用上一次缓存的清单」或「用空账号目录」。否则重启后会把别的账号目录当默认写入点——这是 T5/T6 在运维层面的变种 |
| 缓解（运维，不在本轮范围） | `loginctl enable-linger hdturk`（需 sudo）或在 root systemd 注册 system service；无论哪种，隔离设计不依赖服务是否常驻 |

三条硬不变量（任何后续改动不得违反）：

1. `INV-1` 任何业务 SQL 的 `WHERE` 必须同时含 `account_id = ?` 与（设备级资源）`device_id = ?`。
2. `INV-2` 任何响应体不得包含不属于 token 上下文的 `account_id` / `device_id` / `storage_path`。
3. `INV-3` 任何被拒请求（401/403/404/429）都必须先落审计、再返回响应。

## 1. 威胁模型

| 编号 | 威胁 | 攻击者能力 | 影响 | 对应防御 |
|---|---|---|---|---|
| T1 | 伪造/盗用他人 token | 拿到或猜到一个合法 token；能改任意请求头 | 读走他人清单 | HMAC-SHA256 签名 + 常量时间比较；token 只在 `auth_session` 存哈希；盗用可 revoke（层 1） |
| T2 | 篡改清单 ID / 设备 ID 越权读取 | 已知他人 `inventory_id` 或 `device_id`（可枚举，形如 `dev_0001`） | 越权读、越权覆盖 | ID 全量随机（`secrets.token_hex(12)`）；`assert_owned` + SQL 双条件（层 2/3） |
| T3 | 跨账号读写（IDOR） | 合法账号 A 用自己 token 指向 B 的资源 | 数据泄露/污染 | 层 2 归属校验；跨账号一律 404 |
| T4 | token 泄露后长期可用 | 从客户端配置/日志/截图拿到 token | 长期冒用 | 过期 `exp`（默认 30 天）+ `auth_session` 可撤销 + `issued_at` 失效下水线 |
| T5 | 同账号下设备间串清单 | 用户的 device-1 客户端误带 device-2 上下文 | 覆盖另一台机器清单，重装后装错软件 | 请求体里的 `device_id` 一律丢弃，以 token 为唯一来源；拉取接口强制 `?device_id=` 且必须等于 token 内值 |
| T6 | 下载缓存串包 | 用户 A 下载后，B 请求同名软件 | B 装到 A 的文件（可能是恶意同名包） | 本地目录按 `account_id/device_id` 分树 + 文件名带 `sha256` 前缀；服务端不返回文件本体、只返回 URL+sha256 |
| T7 | 目录投毒（写入恶意 URL） | 普通用户对共享 catalog 提交条目 | 全员下载恶意安装包 | catalog 写入仅 `admin`；URL scheme 白名单（仅 https）+ 拒绝内网/环回地址 + 可选 sha256 强制 |
| T8 | 重放攻击 | 抓到一条合法请求原样重发 | 权限内重复写入、覆盖新清单 | 请求签名带 `ts` + `nonce`（5 分钟窗口）+ 幂等键；写入按 `updated_seq` 单调递增 |
| T9 | 枚举账号/设备 | 遍历 `inv_0001..inv_0100`、探测 `/devices/{id}` | 摸清用户规模、拿到他人 ID 供 T2 使用 | ID 随机；跨账号统一 404；响应长度对齐；可选全局限速 |
| T10 | 审计缺失导致事后无法追溯 | 无（运维视角） | 出事无法定责、无法证明隔离生效 | 每次拒绝落 `audit_log`；`unittest` 直接断言审计行（第 4 节 E1–E4） |
| T11 | **Bearer token 明文落库**（token 存 SQLite 被拿到，即长期冒用） | 能读到数据库文件（备份泄漏、误 `cat`、`/var/lib` 被复制到别的机器、调试时 `sqlite3` 导出） | 全量账号被冒用，且与原用户无法区分 | **只存 `sha256(token)` 摘要，不存原文**；校验时对来 token 求摘要比对（`hmac.compare_digest`）；token 明文只在响应里出现一次，服务端日志脱敏为 `tok_***<末4位>` |
| T12 | **客户端 token 存留**（Windows 侧落盘位置不当） | 读客户端磁盘的另一用户/恶意软件 | 同上，但影响单设备 | token 落 `%LOCALAPPDATA%\software-reback\token`（每用户私有目录），权限继承用户 ACL；`--token-file` 可指定；日志与 `download-report.csv` 不含 token |

## 2. 隔离分层设计

### 2.1 层 1 认证层：账号 ↔ 设备绑定

**防住**：T1、T4、T8、T11。认证方案固定为 **Bearer token + 绑定 `(account_id, device_id)`**（不引入 session cookie，见 `02-architecture.md`）。token 是唯一身份来源。

- 签发：`scan register` 用一个一次性 `enroll_code`（账号维度）换取 `(account_id, device_id)` 对应的 token；`device_id` 由服务端生成，不由客户端自报。
- token 结构（不透明串，服务端可解析）：

```
tok_<b64url(account_id|device_id|session_id|exp|jti)>.<hmac_sha256_hex(payload, server_secret)>
```

- 校验顺序（任一步失败即 401，且**不透露走到哪一步**）：格式 → 签名（`hmac.compare_digest`）→ `exp` → `auth_session` 存在且 `revoked_at IS NULL`。
- **token 不存明文**（针对 T11）：`auth_session` 只有一个 `token_hash TEXT NOT NULL UNIQUE` 列，值为 `sha256(token_hex)`；校验第四步比对的是哈希。验收期可用 `sqlite3 db "SELECT token_hash FROM auth_session"` 确认无 `tok_` 前缀明文。
- 日志脱敏：请求日志写 `tok_***<末 4 位>`；`Authorization` 头永不写进 `audit_log`。
- 重放：写入类请求必须带 `X-Sign-Ts` 与 `X-Sign-Nonce`，`(session_id, nonce)` 唯一索引冲突即 409。

### 2.2 层 2 授权层：每个请求必须做归属校验

**防住**：T2、T3、T5。规则只有一条：**任何按 ID 取资源的 handler，第一行必须是 `assert_owned(...)`，返回值才能用**。

```python
# src/software_reback/cloud/authz.py （示意，伪代码）
ROOT = "__root__"   # 账号级资源（如账号信息）的 device 占位

def assert_owned(conn, token_ctx, resource_type, resource_id, *, device_scope=None):
    ctx = require_token(conn, token_ctx)          # 层 1：401
    if resource_type in DEVICE_LEVEL:
        require_device(ctx, device_scope)          # 403/400：token 的 device 必须匹配
    row = RESOLVERS[resource_type](conn, resource_id, ctx.account_id)  # SQL 自带 account 条件
    if row is None:
        audit(conn, ctx, "deny", reason="not_found", res=resource_type, rid=resource_id)
        raise NotFound("resource_not_found")       # 404，不区分「不存在」与「不是你的」
    if resource_type in DEVICE_LEVEL and row["device_id"] != ctx.device_id:
        audit(conn, ctx, "deny", reason="device_mismatch", ...)
        raise NotFound("resource_not_found")       # 同账号跨设备也报 404，避免设备枚举
    audit(conn, ctx, "allow", ...)
    return row
```

要点：`RESOLVERS` 返回的 SQL 本身已带 `account_id = ?`，`assert_owned` 的 `device_id` 比较是**第二道**，不是唯一一道。

### 2.3 层 3 存储层：越权在 SQL 层就无法命中

**防住**：T2、T3、T9，并兜住层 2 的编码疏漏。

```sql
-- 账号：token 内的 account_id 外键
CREATE TABLE account(
  account_id  TEXT PRIMARY KEY,            -- acct_<token_hex(12)>
  label       TEXT NOT NULL,
  role        TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin')),
  created_at  TEXT NOT NULL
);

-- 会话：Bearer token 只存摘要，不存明文（T11）
CREATE TABLE auth_session(
  session_id TEXT PRIMARY KEY,             -- sess_<token_hex(12)>
  account_id TEXT NOT NULL,
  device_id  TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,         -- sha256(token) 十六进制，永不存 token 原文
  issued_at  TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  FOREIGN KEY(account_id, device_id) REFERENCES device(account_id, device_id)
);
CREATE INDEX idx_session_scope ON auth_session(account_id, device_id);

-- 设备：一台机器一条；重装前后是两条不同记录
CREATE TABLE device(
  device_id   TEXT PRIMARY KEY,            -- dev_<token_hex(12)>
  account_id  TEXT NOT NULL REFERENCES account(account_id),
  hostname    TEXT NOT NULL DEFAULT '',
  relinked_at TEXT,
  UNIQUE(device_id, account_id)            -- 让子表能复合外键指回来
);

-- 清单：归属是 (account_id, device_id)，两者同表冗余存储，便于复合外键
CREATE TABLE inventory(
  inventory_id TEXT PRIMARY KEY,           -- inv_<token_hex(12)>
  account_id   TEXT NOT NULL,
  device_id    TEXT NOT NULL,
  seq          INTEGER NOT NULL,           -- 单调递增，用于拒绝旧清单覆盖新清单
  schema_version INTEGER NOT NULL DEFAULT 2,
  payload_json BLOB NOT NULL,
  created_at   TEXT NOT NULL,
  UNIQUE(inventory_id, account_id, device_id),
  FOREIGN KEY(account_id, device_id) REFERENCES device(account_id, device_id)
);

-- 清单行（查询入口，避免整块 JSON 全量扫描）
CREATE TABLE inventory_item(
  inventory_id TEXT NOT NULL,
  account_id   TEXT NOT NULL,
  device_id    TEXT NOT NULL,
  name         TEXT NOT NULL,
  version      TEXT NOT NULL DEFAULT '',
  FOREIGN KEY(inventory_id, account_id, device_id)
    REFERENCES inventory(inventory_id, account_id, device_id) ON DELETE CASCADE
);
CREATE INDEX idx_item_scope ON inventory_item(account_id, device_id, inventory_id);

-- 审计：拒绝也要能查
CREATE TABLE audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL, account_id TEXT, device_id TEXT, session_id TEXT,
  action TEXT NOT NULL, outcome TEXT NOT NULL CHECK(outcome IN ('allow','deny')),
  reason TEXT NOT NULL DEFAULT '', resource_type TEXT, resource_id TEXT,
  remote_addr TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_audit_scope ON audit_log(account_id, at);
```

> 前缀 `acct_` / `dev_` / `inv_` 只做日志可读性，**不承担安全语义**；安全来自 96 bit 随机数。

**安全查询 vs 危险查询**（同一个 handler，两种写法）：

```python
# ✅ 安全：account + device 双条件，找不到即 404；参数化
SAFE = """SELECT inventory_id, account_id, device_id, seq, schema_version, payload_json
            FROM inventory
           WHERE inventory_id = ? AND account_id = ? AND device_id = ?"""

def get_inventory(conn, ctx, inventory_id):
    row = conn.execute(SAFE, (inventory_id, ctx.account_id, ctx.device_id)).fetchone()
    if row is None:
        raise NotFound("resource_not_found")
    return row

# ❌ 危险：只按裸 ID 查，靠调用方「记得」再比较 account_id
UNSAFE = "SELECT * FROM inventory WHERE inventory_id = ?"

def get_inventory_bad(conn, ctx, inventory_id):
    row = conn.execute(UNSAFE, (inventory_id,)).fetchone()   # 越权行已经读出内存
    if row and row["account_id"] == ctx.account_id:          # 忘了这行就整库泄露
        return row
    raise NotFound("resource_not_found")
```

防劣化措施（可静态检查，见 5.6）：`tests/test_isolation.py::SqlHygieneTest` 用正则扫描 `src/software_reback/cloud/*.py`，出现 `WHERE inventory_id = ?"` 这类**不带 account 条件**的字面 SQL 即失败。

### 2.4 本地文件系统层隔离（客户端）

**防住**：T6。云端不存安装包本体（沿用 README「不托管、不再分发」），所以串包风险在客户端磁盘。

```
downloads/
  acct_9f.../
    dev_3ab.../            # 当前机器
      chrome-131.0.6778.86__9f3c0a1b2d4e.msi     # 文件名 = <safe_file_name>__<sha256 前 12 位>
      meta.json                                    # {sha256, source_url, fetched_at, device_id}
    dev_77c.../            # 另一台机器（重装前）
      ...
```

- 目录函数固定：`dest_dir = base / account_id / device_id`，且 `assert dest_dir.resolve().is_relative_to((base/account_id).resolve())`，杜绝 `device_id` 里的 `..`。
- 同名不同哈希 → 不同文件；同名同哈希 → 复用并校验 `sha256_of_file`（复用现有 `downloader.sha256_of_file`）。
- 下载仍走现有 `download_url`：先写 `.part`、SHA256 校验通过才 `os.replace`，失败不留残留——这条已有 64 项测试中的用例覆盖，新隔离只加「落哪个目录、叫什么名」。

## 3. 归属校验伪代码（顺序不可反）

```python
def assert_owned(conn, token_ctx, resource_type, resource_id):
    # ① 先验 token：401 —— 在此之前不读任何业务表
    ctx = verify_token(conn, token_ctx)
    if ctx is None:
        raise Unauthorized("invalid_token")          # 不区分：格式错 / 签名错 / 过期

    # ② 再验设备：token 声明的 device 是否存在且属于该 account（403 不进业务表）
    if not device_belongs_to(conn, ctx.account_id, ctx.device_id):
        audit_deny(conn, ctx, "device_unbound", resource_type, resource_id)
        raise Forbidden("device_unbound")

    # ③ 再验资源归属：SQL 双条件，命中即「存在且在范围内」
    row = fetch_scoped(conn, resource_type, resource_id, ctx.account_id, ctx.device_id)
    if row is None:
        audit_deny(conn, ctx, "not_found_or_foreign", resource_type, resource_id)
        raise NotFound("resource_not_found")         # 跨账号与不存在在响应上完全一致

    # ④ 最后才查数据
    payload = row["payload_json"]
    audit_allow(conn, ctx, resource_type, resource_id)
    return payload
```

**为什么顺序不能反**（时序侧信道）：

- 若先查资源再验 token：不存在的资源**立刻**返回，存在的资源要多花一次鉴权。攻击者遍历 ID 时，**响应时间差 = 资源存在性预言机**，配合 T2 的 ID 可枚举就能把用户规模、清单 ID 全部摸出来。
- 若先验资源归属再验设备：同账号下可以区分「资源存在但属于别设备」与「资源不存在」，泄露用户有几台机器。
- 因此固定为「鉴权开销恒定 → 业务访问只发生在鉴权通过后 → 资源不存在与越权共用同一路径、同一错误码、同一 `Content-Length`」。
- 落地要求：404 与 403 分支都**必须先写 `audit_log` 再返回**（避免「审计写盘时间」成为新的差异），审计写入与响应在同一事务提交点前后固定位置。
- 测试约束：B1/B2/B3 用例不只断言状态码，还断言**状态码分布一致 + 响应体字节长度一致**；时间差只在本地 loopback 上做「不超 15 倍中位数」的宽松断言（机器抖动大，硬卡耗时会 flaky）。

## 4. 越权验证用例矩阵（核心）

约定：账号 `A`（`acct_a`，设备 `dev_a1` / `dev_a2`）、账号 `B`（`acct_b`，设备 `dev_b1`）。下文 `token(A,dev)` 表示绑定该账号设备的 token（Bearer，不用 Cookie）。期望响应体统一 `{"error": {"code": "...", "message": "..."}}`（字段定义以 `03-api-contract.md` 为准）。

| 用例 | 场景 | 前置条件 | 操作 | 期望结果 | 断言点 |
|---|---|---|---|---|---|
| P1 | A 读自己清单成功 | `dev_a1` 已上报 1 份清单 `inv_a1`（2 条软件） | `GET /v1/inventory/inv_a1`，`token(A,dev_a1)` | 200 | `status==200`；`body["inventory_id"]=="inv_a1"`；`len(body["software"])==2`；DB `inventory` 行数不变 |
| P2 | A 在另一设备读自己清单成功 | `dev_a2` 也上报了 `inv_a2` | `GET /v1/inventory/inv_a2`，`token(A,dev_a2)` | 200 | `status==200`；`device_id` 字段 == `dev_a2`；`software` 名称集合与上报一致 |
| P3 | A 从账号维度列举自己的设备 | A 有 2 台设备 | `GET /v1/accounts/me/devices`，`token(A,dev_a1)` | 200 | `{d["device_id"] for d in body}=={"dev_a1","dev_a2"}`；不含任何 `dev_b*` |
| P4 | A 无 token 访问 | server 起好 | `GET /v1/inventory/inv_a1`，无 `Authorization` | 401 | `status==401`；`error.code=="token_missing"`；`WWW-Authenticate` 以 `Bearer` 开头 |
| P5 | 空 token | — | `Authorization: Bearer `（尾部空白） | 401 | `status==401`；`error.code=="token_missing"`；响应体不含 `Traceback` |
| P6 | 格式错误 token | — | `Authorization: Bearer not-a-token` | 401 | `status==401`；`error.code=="token_malformed"` |
| P7 | 篡改签名 | 复制 `token(A,dev_a1)` | 改 payload 最后一个 base64url 字符后请求 | 401 | `status==401`；`error.code=="token_bad_signature"`；审计 `reason="bad_signature"` 行数 +1 |
| P8 | 过期 token | 用 `exp=now-60` 的签发函数造 token | 请求 | 401 | `status==401`；`error.code=="token_expired"`（与 P6/P7 可区分）；审计 `reason="expired"` |
| P9 | 撤销后 token 失效 | 调 `POST /v1/auth/logout` 撤销会话 | 再用旧 token 请求 | 401 | `status==401`；`error.code=="token_revoked"`；`auth_session.revoked_at IS NOT NULL` |
| P10 | token 不以明文落库（T11） | 已签发 `token(A,dev_a1)` | 直接查库并 dump 日志文件 | 只有摘要 | `SELECT token_hash FROM auth_session` 全部匹配 `^[0-9a-f]{64}$`；库文件字节里 `token.encode()` **不出现**；日志里 `Authorization` 已脱敏 |
| N1 | 跨账号读清单 | `inv_b1` 存在 | `GET /v1/inventory/inv_b1`，`token(A,dev_a1)` | **404**（不是 403） | `status==404`；`error.code=="resource_not_found"`；`"inv_b1" not in body_json_str`；`body` 不出现 B 的任何软件名 |
| N2 | 跨账号覆盖清单 | `inv_b1` 存在 | `PUT /v1/inventory/inv_b1`，`token(A,dev_a1)` | 404 | `status==404`；`SELECT payload_json FROM inventory WHERE inventory_id='inv_b1'` 与请求前**逐字节相同**；`seq` 未变 |
| N3 | 跨账号列举 | — | `GET /v1/accounts/acct_b/inventories`，`token(A,dev_a1)` | 404 | `status==404`；`error.code=="resource_not_found"`；响应不含 `acct_b` |
| D1 | 跨设备读（同账号） | `inv_a2` 属 `dev_a2` | `GET /v1/inventory/inv_a2`，`token(A,dev_a1)` | 404 | `status==404`；`error.code=="resource_not_found"`；与 N1 的**状态码与 `error.code` 完全一致** |
| D2 | 跨设备列举 | `dev_a2` 存在 | `GET /v1/inventory?device_id=dev_a2`，`token(A,dev_a1)` | 403 | `status==403`；`error.code=="device_mismatch"`（同账号可见，允许区分） |
| D3 | 请求体塞他人 device_id | `token(A,dev_a1)` | `POST /v1/inventory`，body 含 `{"device_id":"dev_a2", ...}` | 2xx 但写入 `dev_a1` | 响应 `device_id=="dev_a1"`；DB `SELECT count(*) FROM inventory WHERE device_id='dev_a2'` 不增加；body 里的 `dev_a2` 不出现在任何行 |
| D4 | 批量上报混入他人资源 | `token(A,dev_a1)` | `POST /v1/inventories/batch`，items 里 1 条正常 + 1 条 `device_id=dev_b1` | 400，整批不落库 | `status==400`；`error.code=="body_device_mismatch"`；`inventory` 行数不变（批处理必须全成功或全失败） |
| D5 | 设备指纹不合规 | — | 上报 body `device_id` = `../../etc/passwd` | 400 或 2xx 覆盖 | 若覆盖：响应 `device_id` 形如 `^dev_[0-9a-f]{24}$`；若拒绝：`error.code=="invalid_device_id"`；客户端落盘路径不含 `..` |
| B1 | 遍历清单 ID | 库里只有 `inv_a1`、`inv_b1` | 遍历 `inv` + `0000..0099`，`token(A,dev_a1)` | 100 次全 404 | 状态码集合 `== {404}`；`error.code` 集合 `== {"resource_not_found"}`；响应体长度集合大小 `== 1` |
| B2 | 遍历设备 ID | — | `GET /v1/devices/dev_b1`，`token(A,dev_a1)` | 404 | `status==404`；与不存在设备 `dev_ffff` 响应体**完全相同** |
| B3 | 响应时间无明显差异 | 同上 100 个 ID | 每 ID 重复 5 次取中位数 | 无可区分差异 | `max(median) <= 15 * min(median)`；且 404 与 200 的成功请求均不被 `Retry-After` 混淆 |
| R1 | 重放旧写入 | 已提交过一次 `PUT` 请求 | 原样重发（同 ts/nonce） | 409 | `status==409`；`error.code=="nonce_replayed"`；`inventory` 行数与内容不变 |
| R2 | 旧清单回滚覆盖 | `dev_a1` 当前 `seq=7` | `PUT` 带 `seq=5` | 409 | `status==409`；`error.code=="stale_seq"`；DB 该行 `seq` 仍为 7 |
| C1 | 客户端缓存串包 | A/B 各下载同名 `7zip.msi`（内容不同） | 在同一个 `downloads/` 根下分别执行 download | 两个文件路径与哈希都不同 | `path_a.parent.parts[-2:]==("acct_a","dev_a1")`；`path_b.parent.parts[-2:]==("acct_b","dev_b1")`；`sha256_of_file(path_a)!=sha256_of_file(path_b)`；两文件互不覆盖 |
| C2 | 缓存命中必须校验哈希 | `dev_a1` 目录已有 `7zip__<h>.msi`，磁盘内容被改 | 再次下载同软件 | 重新下载或报哈希失败 | `sha256_of_file(target)==catalog_sha256`；若改坏则 `status=="failed"` 且 `.part` 不存在 |
| C3 | 路径逃逸 | 恶意 `device_id`/`file_name` | `dest_for(base, "../../x", "dev")` | 拒绝或落回根下 | `str(path.resolve()).startswith(str(base.resolve()))`；抛 `ValueError` 亦可（用 `assertRaises`） |
| K1 | catalog 投毒：`javascript:` | 普通用户 token | `POST /v1/catalog/entries`，`url="javascript:alert(1)"` | 403（无写权限）+ 即便有权限也 400 | `status in (400,403)`；`error.code in {"forbidden","unsafe_url_scheme"}`；catalog 表行数不变 |
| K2 | catalog 投毒：内网地址 | admin token（模拟误操作） | `url="http://192.168.1.1/x.msi"` | 400 | `status==400`；`error.code=="unsafe_url_host"`；行数不变 |
| K3 | catalog 投毒：`file://` / `ftp://` | 任意 token | `url="file:///etc/passwd"` | 400 | `error.code=="unsafe_url_scheme"`；不落库 |
| K4 | catalog 投毒：HTTP 明文 | 任意 token | `url="http://example.com/a.msi"` | 400（仅允许 https） | `error.code=="unsafe_url_scheme"` |
| K5 | 合法 URL 放行 | admin | `url="https://example.com/a.msi"`，`sha256=<64hex>` | 201 | `status==201`；DB 行数 +1；下载计划里该条目 `sha256` 非空 |
| E1 | 跨账号读落审计 | 已跑 N1 | 查 `audit_log` | 一条 deny | 新增行满足 `outcome=="deny"`、`reason=="not_found_or_foreign"`、`account_id=="acct_a"`、`resource_id=="inv_b1"` |
| E2 | 每个越权用例都有审计 | 按顺序跑 P4–P8、N1–N3、D1–D5、B1 | 统计 | 数量对齐 | `deny` 行数 == 被拒请求数；**不存在 `outcome=="deny"` 但 `at` 为空或 `resource_type` 为空的行** |
| E3 | 正向请求也有审计 | 已跑 P1 | 查 `audit_log` | 一条 allow | `outcome=="allow"`，`resource_id=="inv_a1"`，`at` 可解析为 ISO8601 |
| E4 | 审计不可被客户端删除 | `token(A,dev_a1)` | `DELETE /v1/audit/1`、`GET /v1/audit?account_id=acct_b` | 404/405，且查不到他人 | A 只能读到自己的审计行：`all(r["account_id"]=="acct_a" for r in body)` |

合计 **35 条**（P1–P10 正向/认证/落库 10 条，N 3 条，D 5 条，B 3 条，R 2 条，C 3 条，K 5 条，E 4 条），另加并发用例（5.4）与 `SqlHygieneTest`，合计 **36 个 `test_*` 方法**；覆盖任务要求的全部 10 个威胁面 + 新增的 T11/T12。

### 4.1 错误码总表（与断言一一对应）

| HTTP | `error.code` | 触发用例 | 说明 |
|---|---|---|---|
| 401 | `token_missing` | P4、P5 | 不带/空 `Authorization` |
| 401 | `token_malformed` | P6 | 不以 `tok_` 开头、不含 `.` |
| 401 | `token_bad_signature` | P7 | HMAC 不匹配 |
| 401 | `token_expired` | P8 | `exp < now` |
| 401 | `token_revoked` | P9 | 会话已撤销 |
| 403 | `device_unbound` | —（层 2 步②） | token 的 device 不属于该 account |
| 403 | `device_mismatch` | D2 | 查询参数 `device_id` 与 token 不一致 |
| 403 | `forbidden` | K1 | 无 catalog 写权限 |
| 404 | `resource_not_found` | N1–N3、D1、B1、B2 | 不存在与无权访问共用 |
| 400 | `body_device_mismatch` | D4 | 批量上报混入其他设备 |
| 400 | `invalid_device_id` | D5 | 形态不合规 |
| 400 | `unsafe_url_scheme` / `unsafe_url_host` | K1–K4 | catalog URL 校验 |
| 409 | `nonce_replayed` / `stale_seq` | R1、R2 | 重放与旧序号 |

## 5. 自动化验证方案

### 5.1 测试组织

| 文件 | 内容 | 是否随本轮实现 |
|---|---|---|
| `tests/test_isolation.py` | 第 4 节全部用例（P/N/D/B/R/C/K/E）+ 并发用例（5.4）+ `SqlHygieneTest` | 必须 |
| `tests/test_cloud_server.py` | 服务端 handler 正常路径（健康检查、上报、拉取） | 可选，已有则复用 |
| `src/software_reback/cloud/{store_schema.py,authz.py,tokens.py,urlguard.py}` | 被测试的实现模块 | 下一轮实现 |

- 沿用现有风格：文件头 `sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))`，`unittest` + `unittest.mock`（标准库），**不引入 pytest / requests**；HTTP 用 `urllib.request`。
- 临时服务端仿照 `tests/test_downloader.py` 的 `_Server`：`socketserver.TCPServer(("127.0.0.1", 0), handler)` + 守护线程，端口随机，跑完 `shutdown()`。
- SQLite 用 `:memory:` 或 `tempfile.TemporaryDirectory()` 单测文件，**每个 case 一个全新库**（`setUp` 里建表 + 夹具），用例之间零耦合。

### 5.2 测试夹具：「2 账号 × 各 2 设备 × 各 1 清单」

```python
ACCOUNTS = ("acct_a", "acct_b")
DEVICES = {"acct_a": ("dev_a1", "dev_a2"), "acct_b": ("dev_b1", "dev_b2")}

def build_fixture(conn):
    """返回 {(account, device): inventory_id}，并把 token 一起返回。"""
    ids, tokens = {}, {}
    for account in ACCOUNTS:
        conn.execute("INSERT INTO account(account_id,label,created_at) VALUES(?,?,?)",
                     (account, account, "2026-11-15T00:00:00Z"))
        for device in DEVICES[account]:
            conn.execute("INSERT INTO device(device_id,account_id,hostname) VALUES(?,?,?)",
                         (device, account, f"pc-{device}"))
            inv = f"inv_{account[-1]}{device[-2:]}"
            conn.execute("INSERT INTO inventory(inventory_id,account_id,device_id,seq,"
                         "schema_version,payload_json,created_at) VALUES(?,?,?,?,?,?,?)",
                         (inv, account, device, 1, 2,
                          json.dumps({"software": [{"name": f"app-{device}-1"},
                                                   {"name": f"app-{device}-2"}]}),
                          "2026-11-15T00:00:00Z"))
            ids[(account, device)] = inv
            tokens[(account, device)] = issue_token(account, device, exp=int(time.time()) + 600)
    conn.commit()
    return ids, tokens
```

### 5.3 完整测试函数示例（跨账号越权 + 404 + 审计）

```python
class CrossAccountTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.server, self.base = make_test_server()   # 内存库 + 随机端口
        self.ids, self.tokens = build_fixture(self.conn)
        self.inv_b1 = self.ids[("acct_b", "dev_b1")]

    def test_read_foreign_inventory_is_404_and_audited(self):
        deny_before = audit_count(self.conn, outcome="deny")

        status, body, _ = http_get(
            f"{self.base}/v1/inventory/{self.inv_b1}",
            token=self.tokens[("acct_a", "dev_a1")],
        )

        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "resource_not_found")
        self.assertNotIn(self.inv_b1, json.dumps(body, ensure_ascii=False))
        self.assertNotIn("app-dev_b1-1", json.dumps(body, ensure_ascii=False))

        deny_after = audit_count(self.conn, outcome="deny")
        self.assertEqual(deny_after, deny_before + 1)          # 每个越权尝试一条
        last = self.conn.execute(
            "SELECT account_id, device_id, reason, resource_type, resource_id "
            "FROM audit_log WHERE outcome='deny' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(last[:2], ("acct_a", "dev_a1"))
        self.assertEqual(last[2], "not_found_or_foreign")
        self.assertEqual((last[3], last[4]), ("inventory", self.inv_b1))
        # INV-1：B 的清单一个字节没被改动
        self.assertEqual(self.conn.execute(
            "SELECT payload_json FROM inventory WHERE inventory_id=?", (self.inv_b1,)).fetchone()[0],
            json.dumps({"software": [{"name": "app-dev_b1-1"}, {"name": "app-dev_b1-2"}]}))
```

### 5.4 并发测试（无串数据）

思路：单进程多线程是真实形态，测试必须**真的并发**，不能串行调用。

- 起服务端时用 `socketserver.ThreadingTCPServer`，并为它加锁（`ThreadingMixIn` 断连时 `server_close()` 不 join 线程会抛 `ResourceWarning`，属已知行为）：每请求取**独立连接**（`sqlite3.connect(db, check_same_thread=False, timeout=5)` + 每请求新 cursor），不共享 cursor。
- 50 个线程并发写入：`acct_c` 下的 `dev_c1..dev_c25` 各 2 个线程同时上报（同设备并发写入是真实场景：客户端重试 + 用户同时点两次），每条清单内含唯一标记 `MARK-<i>`；另 25 个线程并发拉取本设备清单。
- 结束后逐个校验：

```python
def test_concurrent_writes_do_not_cross(self):
    errors, ids = [], {}
    def writer(i):
        try:
            _, body, _ = http_post(self.base + "/v1/inventory", token=self.tokens_c[i],
                                   payload={"schema_version": 2,
                                            "software": [{"name": f"MARK-{i}-1"}]})
            ids[i] = body["inventory_id"]
        except Exception as exc:      # 线程里的异常不会让 unittest 失败，必须收集
            errors.append((i, exc))

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(50)]
    for t in threads: t.start()
    for t in threads: t.join()
    self.assertEqual(errors, [])

    self.assertEqual(len(set(ids.values())), 50)                       # ID 两两不同
    for i, inv in ids.items():
        row = self.conn.execute("SELECT account_id, device_id, payload_json "
                                "FROM inventory WHERE inventory_id=?", (inv,)).fetchone()
        self.assertEqual(row[1], f"dev_c{i % 25}")                     # 归属设备正确
        names = {item["name"] for item in json.loads(row[2])["software"]}
        self.assertEqual(names, {f"MARK-{i}-1"})                       # 只有自己的标记
        self.assertEqual(self.conn.execute(
            "SELECT count(DISTINCT device_id) FROM inventory_item WHERE inventory_id=?",
            (inv,)).fetchone()[0], 1)
```

补充断言：`SELECT count(*) FROM inventory_item WHERE device_id=? AND name NOT LIKE ?` 每设备为 0；`sqlite3` 出现 `database is locked` 视为失败（说明连接/事务隔离没做好）。

### 5.5 一键验证命令与期望输出

命令沿用项目既有风格（`PLAN-SPLIT.md` 证据行：`python -m unittest discover -s tests` = 64 OK）：

```powershell
python -m unittest tests.test_isolation -v      # 只跑隔离
python -m unittest discover -s tests -v         # 全量回归（既有 64 条 + 隔离）
```

期望输出（隔离套件）：

```
test_missing_token_is_401 (tests.test_isolation.AuthTest) ... ok
...
test_token_hash_is_not_plaintext (tests.test_isolation.TokenAtRestTest) ... ok
...
test_read_foreign_inventory_is_404_and_audited (tests.test_isolation.CrossAccountTest) ... ok
...
Ran 36 tests in 4.1s

OK
```

全量期望：**既有 64 条继续全绿** + 隔离 36 条 = **100 条，`Ran 100 tests ... OK`，返回码 0**（有失败时 unittest 返回码为 1，可直接接 CI）。

### 5.6 覆盖率门槛与回归门槛

| 对象 | 门槛 | 理由 |
|---|---|---|
| `src/software_reback/cloud/authz.py` | 行覆盖 **100%**，分支覆盖 ≥ 95% | 归属校验漏一个分支就是漏洞 |
| `src/software_reback/cloud/tokens.py` | ≥ 95% | 签名/过期/撤销/摘要比对四条路径必须都测 |
| `src/software_reback/cloud/urlguard.py` | 100%（scheme/host 两个判定函数） | T7 投毒只在这两处拦 |
| 客户端 `paths.dest_for` / 命名函数 | 100% | T6 串包只在这里拦 |
| 隔离相关整体 | ≥ 90% | 见命令 |

```powershell
python -m coverage run --source=src/software_reback/cloud -m unittest tests.test_isolation
python -m coverage report --fail-under=90
```

- `coverage` 是唯一允许的开发期依赖（**不进** `pyproject.toml` 的 `dependencies`；notebook 上 pypi 可用，可装进 venv）。
- 静态防劣化：`SqlHygieneTest` 扫描 `cloud/*.py` 的 SQL 字面量，`WHERE ... = ?` 中出现 `inventory_id`/`device_id` 却不含 `account_id` → 失败。
- **回归门槛（不可放宽）：既有 64 条测试必须继续全绿。** 任何改动——包括隔离新代码——跑 `python -m unittest discover -s tests -v` 必须看到 `Ran 100 tests ... OK`、返回码 0；**64 条里任何一条变红都不许合并**（说明改动破坏了现有 CLI 行为，例如 `download_url` 的 `.part`/原子改名语义、`run_download` 的依赖注入签名）。
- **合并门槛：100 条全绿 + 覆盖率达标 + `SqlHygieneTest` 通过，三条同时满足才允许合并。**

## 6. 验收清单（隔离功能算完成）

- [ ] `python -m unittest tests.test_isolation -v` → `Ran 36 tests` 且 `OK`
- [ ] `python -m unittest discover -s tests -v` → `Ran 100 tests ... OK`，返回码 0；**其中既有 64 条全部仍为 ok**
- [ ] 隔离用例在「服务未常驻」环境下可跑：全部自建进程内服务端（`127.0.0.1` 随机端口），不读 notebook 的 8084
- [ ] 服务不可达时客户端**失败关闭**（报错退出，不回落到缓存清单或空账号目录）
- [ ] 跨账号读/写/列举一律 **404 `resource_not_found`**，响应体不含目标资源 ID 与任何他人软件名
- [ ] 同账号跨设备读其清单 → 404；`?device_id=` 与 token 不符 → 403 `device_mismatch`
- [ ] 请求体携带的 `device_id` **永不生效**（D3 断言 DB 中该设备行数不变）
- [ ] 401 的五个错误码（`token_missing` / `token_malformed` / `token_bad_signature` / `token_expired` / `token_revoked`）可区分
- [ ] `auth_session` 只有 `token_hash` 列，`SELECT token_hash FROM auth_session` 无 `tok_` 前缀明文；服务端日志中 `Authorization` 已脱敏
- [ ] 每个被拒请求在 `audit_log` 恰好新增 1 行 `deny`，含 `account_id`/`resource_id`/`reason`/`at`
- [ ] `SqlHygieneTest` 通过（无「裸 ID 查询」SQL）
- [ ] catalog 写入仅 admin；`javascript:` / `file:` / `http:` / `192.168.x.x` / `127.0.0.1` 全部 400
- [ ] 客户端 `dest_for` 产出路径必在 `downloads/<account_id>/<device_id>/` 下，文件名含 sha256 前缀；C1/C3 用例通过
- [ ] 50 线程并发写入后逐条校验归属，无串数据、无 `database is locked`
- [ ] `coverage report --fail-under=90` 通过，`authz.py` 行覆盖 100%
- [ ] README 增补「隔离如何自证」一节，指向本文件与上述命令
- [ ] `PLAN-SPLIT.md` 第 12 行「隔离强度」一行可被直接引用：伪造 token / 篡改 ID / 跨用户读写 → 全部拒绝，且由上述 35 条矩阵用例 + 并发用例证明

## 7. 不做什么（范围外）

| 不做 | 原因 | 何时才需要加 |
|---|---|---|
| 多租户计费/配额 | 单用户自建、账号数是个位数，计费没有对象 | 对外开放注册后 |
| OAuth 第三方登录 | 引入 IdP 依赖，而 notebook 出网受限（github 不可达），OAuth 回调调试成本远高于收益 | 有组织级 SSO 需求时；届时仍是「认证换 token」，层 2/3 不变 |
| RBAC 角色体系 | 当前只有两种能力：`user`（读写自己的清单）/`admin`（写共享 catalog）。两个角色用一个 `role` 字段即可，引入 RBAC 引擎只会增加「策略写错导致越权」的面 | 出现「团队共享清单」「只读审计员」这类**第三种**能力时，再引入 `role` + `permission` 两表 |
| 加密存储（SQLCipher / 字段级加密） | 当前威胁模型只覆盖「有网络访问权的用户」（T1–T10）与「能读到 DB 文件但不能反向破解 token」（T11，已用 `sha256` 摘要缓解）。单机自建、磁盘属于同一信任域，加密密钥最终也落在同一台机器上，收益≈0 | ①机房托管/云主机共享磁盘 ②`/var/lib` 备份上云 ③清单里出现凭证类字段。届时用 SQLCipher 或在 `payload_json` 层做 AES-GCM，密钥走 systemd `LoadCredential` |
| 用 session cookie 替代 Bearer token | 已确认的架构决策就是 Bearer token 绑定 `(account_id, device_id)`；cookie 反而引入 CSRF 与「同一浏览器多设备串用 Cookie」两个新面 | 不做 |
| WAF / 全局限速 | 单账号场景枚举收益低；B3 已用「响应无差异」降低枚举价值 | 对外开放且出现刷接口行为时，加 `nginx limit_req` 或进程内令牌桶 |
| 安装执行鉴权 | 项目刻意不做安装执行（README「未实现的部分」） | 永远不做 |
| 跨设备清单同步/合并 | 与「重装前后各自独立」的产品语义冲突 | 用户明确提出「多机合并视图」时，那是在层 3 之上加只读聚合视图，不改归属 |
