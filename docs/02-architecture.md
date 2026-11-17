# 02 架构说明（software-reback-cloud）

> 归属：文档 B（架构 + 接口契约）。本文只描述架构，不改代码、不部署。
> 基线：`PLAN-SPLIT.md`（**已归档**，仅引用其实测事实数据）、`README.md`（现有 CLI 行为）、`src/software_reback/*.py`（现有实现）。
> 术语沿用统一编号：**M1 读取 / M2 下载 / M3 隔离 / M4 汇总**。

## 0. 范围（做什么 / 不做什么）

| 做什么 | 不做什么（明确排除） |
|---|---|
| 单进程 HTTP 服务托管「账号 + 设备 + 清单 + 目录 + 下载决策」 | Docker / 容器 / 反向代理以外的任何守护进程 |
| 客户端复用现有 CLI，新增 `cloud` 子命令 | 重写 scan / download 逻辑 |
| 元数据与决策下发（直链 + SHA256，或 winget ID） | 托管安装包本体、二次分发、代理下载第三方文件 |
| 账号级 + 设备级双层隔离，token 绑定 `(account_id, device_id)` | 安装执行（静默参数下发与状态回传）—— 与现状一致，刻意不做 |
| SQLite 单文件存储 + 审计日志 | Postgres / Redis / 消息队列 / 对象存储 |
| 服务端 token 只落 SHA256 摘要 | 任何「能反查回原文 token」的存储方式 |
| 静态资源全部本地化 | 任何 GitHub raw / CDN 运行时引用（**实测 000 不可达**） |

## 1. 架构总览

```text
┌───────────────────────────── 客户端：Windows 主机 ─────────────────────────────┐
│ software-reback CLI（现有，扩展 cloud 子命令）                                  │
│  M1 读取   inventory.py / winget.py ──► software.json (schema_version=2)       │
│  M2 下载   catalog.py / resolver.py / downloader.py（复用，来源改为云端决策）    │
│  M3 隔离   device.py（新增：machine_id 指纹）＋ tokenstore.py（新增：本地 token）│
│  M4 汇总   cloud.py（新增：pull / resolve / contribute）                        │
│  配置：%APPDATA%\software-reback\{config.json,token.json,devices\*.json}        │
└───────────────────────────────┬────────────────────────────────────────────────┘
                                │ HTTP/1.1 + Bearer token（局域网 192.168.1.x）
                                │ 走局域网直连 8084；外网经 frp cloud1:20084
┌───────────────────────────────▼────── notebook 192.168.1.24 ───────────────────┐
│ systemd --user: software-reback-cloud.service（单进程，不碰 Docker）           │
│  0.0.0.0:8084  http.server.ThreadingHTTPServer（Python 3.12.3 标准库）         │
│  ┌────────── 路由层 api.py ──────────┐                                          │
│  │ /api/v1/* 只做：认证 → 参数校验 → 调用 service → 统一包络                 │
│  └───────┬───────────┬───────────────┘                                          │
│  ┌───────▼──────┐ ┌──▼─────────┐ ┌─────────────┐ ┌─────────────┐               │
│  │ auth (M3)    │ │ inventory  │ │ catalog (M4)│ │ audit (M3)  │               │
│  │ 注册/登录/   │ │ (M1 存量)  │ │ 快照/单条/  │ │ 操作日志    │               │
│  │ token 摘要校验│ │ 上报/拉取  │ │ 贡献/审核   │ │ 只追加      │               │
│  └───────┬──────┘ └──┬─────────┘ └──────┬──────┘ └──────┬──────┘               │
│          └───────────┴───────────┬──────┴───────────────┘                      │
│                                  ▼                                             │
│                  db.py：sqlite3（WAL，busy_timeout=5000，单写者）                │
│                  ~/apps/software-reback-cloud/data/app.db                       │
│                  tokens 表只存 sha256(token) —— 拖库拿不到可用凭证               │
└──────────────────────────────────┬─────────────────────────────────────────────┘
                                   │ 只读出网：pypi 200 / npm 镜像 200
                                   │ GitHub 000、cdn.jsdelivr.net 000 → 零外链
                        ┌──────────▼──────────┐        ┌────────────────────────┐
                        │ pypi（venv 装依赖） │        │ 客户端/服务器各自访问   │
                        └─────────────────────┘        │ 厂商官方下载地址        │
                                                       │ （服务端不中转文件）    │
                                                       └────────────────────────┘
```

关键点：**服务端只出决策，不出字节**。安装包由客户端直接从厂商官方地址或 winget 源取，这也是「不托管安装包」在架构上的体现。

## 2. 技术选型

约束来源：notebook 为 4 核 / 11G（**已用约 5G，剩约 6G**，跑着 Dify 14 + Plane 13 + Stirling + LibreTV）、Python 3.12.3、sqlite 3.45.1；出网实测 **pypi 200 / npm 镜像 200 / github.com 000 / cdn.jsdelivr.net 000**；现有容器一个都不能碰。**内存预算是硬指标（见 2.1）。**

| 层 | 选型 | 理由 | 放弃的方案及原因 |
|---|---|---|---|
| 运行时 | Python 3.12.3（系统自带）+ venv | 与现有代码同语言，可直接 `pip install -e` 复用 `src/software_reback` | Node/Go 后端：增加第二套工具链与体积；Go 需从 github 拉模块（不可达） |
| HTTP 服务 | `http.server.ThreadingHTTPServer` + `BaseHTTPRequestHandler` | 标准库、零依赖；单进程足够 1–3 台机器、QPS < 10 | uvicorn/FastAPI（pypi 可装，但为 <10 QPS 引入 ASGI 依赖不划算）；Flask（同理由）；nginx 反向代理（8084 只服务一个后端，frp 已做转发） |
| 路由 | 手写前缀匹配表（`METHOD + 路径正则 → handler`） | 30 行以内可测、无隐式魔法；接口数 < 25 | Django（ORM/模板/管理后台全用不到）；Starlette（依赖链条长） |
| 存储 | SQLite 3.45.1（WAL） | 单进程单写者天然无并发写冲突；单文件备份；支持 JSON1 与 `ON CONFLICT` upsert | Postgres（见决策 D2）；MySQL（同上）；纯 JSON 文件（无事务、无唯一约束、越权校验易漏） |
| 认证 | 自实现 HS256 JWT（`hmac`+`hashlib`）+ `hashlib.scrypt` 口令哈希 + token **只存 SHA256 摘要** | 标准库即可；token 需带 `account_id`/`device_id` 声明 | PyJWT（见下方「依赖与内存预算」，默认不引入）；session cookie（见决策 D3） |
| Web 前端 | **V1 不提供 Web UI**，仅 JSON API；若将来加 UI，资源**必须内联或本地静态文件** | cdn.jsdelivr.net 从 notebook **不可达(000)**，任何 CDN 引用都会变成空白页 | React/Vue + CDN：直接不可用；打包后走 CDN 的 SPA：同上；本地打包前端：本轮范围外 |
| 进程托管 | systemd `--user` unit | 无需 root；不碰 Docker 与 27+ 容器；`Restart=always` 自动拉起（**但 `Linger=no` 时重启不自启**，见 5.4） | Docker（见决策 D1）；`nohup` 脚本（无重启、无日志轮转） |
| 日志 | `logging` → journald（stdout）+ `logs/app.log`（RotatingFileHandler） | journald 免配置轮转；文件便于无 ssh 时排查 | logrotate 配置（多一个系统级组件） |
| 测试 | `unittest`（与现有 64 测试同一套） | 现有项目已用它，无 pytest 依赖 | pytest（不是必需，避免双框架） |

### 2.1 依赖与内存预算（硬指标）

实测内存：**11G 总量、已用约 5G**（Dify 14 容器 + Plane 13 容器 + Stirling + LibreTV 常驻），本服务可用余量按 **≤ 300MB 上限 / ≤ 100MB 常驻目标** 规划。

| 项 | 预算 | 依据 |
|---|---|---|
| Python 解释器常驻（CPython 3.12，无重框架） | 18–25 MB | `python3 -c 'pass'` 基线约 8–10MB，加载 `sqlite3`/`http.server`/`json` 后约 18MB |
| SQLite 页缓存（`PRAGMA cache_size=-16000`，即 16MB） | ≤ 16 MB | 数据量 < 10⁵ 行，无需更大缓存 |
| 每线程栈（`ThreadingHTTPServer`，并发 ≤ 8） | 8 × 约 8MB 虚拟、实际 RSS 约 1–2MB | 通过 `TasksMax=64` 与请求体上限收敛 |
| GZip 响应（目录快照压缩） | 瞬时，峰值 < 5 MB | 快照 JSON 约 200KB，压缩后 < 40KB |
| **合计 RSS 目标** | **< 100 MB** | `systemctl --user show -p MemoryCurrent` 验收，期望 < 104857600 |

**预算被打破时的处置规则（必须执行）**：

| 触发条件 | 处置 |
|---|---|
| 任一依赖安装后 `MemoryCurrent` > 100MB | 立即 `pip uninstall` 回退到标准库实现，并在本文档记录 |
| 需要引入带 C 扩展或 ORM（如 SQLAlchemy、Django、pandas）的依赖 | **一律拒绝**，改用手写 `sqlite3` + 参数化 SQL |
| 需要引入 ASGI 服务器（uvicorn 常驻约 40–60MB + 框架自身） | 拒绝；并发靠 `ThreadingHTTPServer` + 短连接，`QPS < 10` 场景足够 |
| 有人提议加后台任务队列（Celery/RQ） | 拒绝；改为 systemd timer 触发一次性脚本，跑完即退（内存归零） |
| 必须引入某依赖且替代不可行 | 先做峰值压测（`systemd-run --user -p MemoryMax=100M` 下跑 200 次请求），通过才允许 |

### 2.2 推荐最小依赖集

**服务端运行时第三方依赖：0 个。** 全部使用标准库：`http.server`、`sqlite3`、`hashlib`（`scrypt`/`sha256`）、`hmac`、`secrets`、`json`、`datetime`、`logging`、`gzip`、`base64`、`argparse`。

| 候选依赖 | 为什么可能值得引入 | 不引入的替代 | 本轮结论 |
|---|---|---|---|
| `PyJWT>=2.8` | 少踩 `base64url` 填充、`exp` 时区、算法白名单三个坑 | 自写 `_b64url` + `hmac.compare_digest`，约 45 行 + 6 个单测 | **不引入**（可装但没必要；纯 Python 约 3MB，属预算内却属可省） |
| `pyotp` | 后续 M3 二次验证（TOTP） | 自写 HOTP/TOTP 约 30 行 | 不引入（V1 不做 2FA） |
| `uvicorn` + `fastapi` | 自动 OpenAPI、并发模型更好 | 见 2.1 处置表 | **拒绝**（破坏内存预算） |
| 任意 JS 运行时/CDN 资源 | 前端组件 | 内联或本地静态文件随仓库 rsync | **拒绝**（`cdn.jsdelivr.net` 不可达 000） |

> 客户端侧沿用现状 `dependencies = []`；`cloud` 子命令用 `urllib` + `json` 实现即可，**不要**为客户端引入 `requests`。
> notebook 出网实测：**pypi 200 / npm 镜像 200 / github.com 000 / cdn.jsdelivr.net 000**。因此：`requirements.txt` 只能来自 pypi；**禁止** `pip install git+https://github.com/...`；**禁止** `npm` 构建期从 GitHub 拉 git 依赖。

## 3. 组件职责

| 模块 | 客户端（Windows，复用现有包） | 云端（notebook 单进程） | 对应文件 |
|---|---|---|---|
| M1 读取 | 注册表扫描 + `winget export` 双路取证，产出 `schema_version=2` 清单；**上报前**先落本地 `software.json`（离线兜底） | 接收清单，按 `(account_id, device_id, inventory_id)` 存版本；只做校验与存储，不做识别 | 客户端 `inventory.py`/`winget.py`（复用+扩展）；云端 `inventory_service.py`（新增） |
| M2 下载 | 消费云端决策（`method` 为 `url` 或 `winget` + `sha256`），复用 `downloader.download_url`（`.part` + 原子改名 + SHA256 强校验）与 `winget.download_with_winget` | 提供「下载决策」：按目录条目返回直链 + SHA256，或返回 `winget_id`；**不代理字节** | 客户端 `downloader.py`/`resolver.py`（复用）；云端 `download_service.py`（新增） |
| M3 隔离 | `device_id` 由机器指纹派生并存本地；token 存 `%APPDATA%` 并限权；每次请求携带 | Bearer token 验签 → 取出 `(account_id, device_id)`，**所有 SQL 必带 `account_id` 谓词**，`device_id` 路径参数必须属于当前账号 | 客户端 `device.py`/`tokenstore.py`（新增）；云端 `auth.py`/`audit.py`（新增） |
| M4 汇总 | `catalog pull` 拉快照到本地缓存，按 `display_name` 归一化索引（复用 `catalog.normalize_name`）；`catalog contribute` 提交新条目 | 目录版本化（`catalog_versions` + `etag` 增量）、单条查询、贡献审核队列、健康度字段 | 客户端 `catalog.py`（扩展）；云端 `catalog_service.py`（新增） |

## 4. 复用边界

| 现有文件 | 新架构中的位置 | 处理 | 说明 |
|---|---|---|---|
| `src/software_reback/models.py` | 客户端模型 → 上报载荷的字段来源 | **扩展** | 新增 `architecture`、`scope`(machine/user)、`registry_key`、`export_id`(=`package_id` 的新名)、`export_source`、`winget_match`(export/name/contrib/none)、`install_date`；`from_dict` 已按 `dataclasses.fields` 过滤未知键，天然向后兼容 |
| `src/software_reback/inventory.py` | 客户端 M1 | **复用** | `collect()`、`record_from_entry()`、`merge_records()`、`normalize_name()` 原样使用；仅在其后追加 export 合流步骤（`merge_records` 已把 `package_id` 纳入 `_completeness`，合流友好） |
| `src/software_reback/winget.py` | 客户端 M1（识别）与 M2（下载） | **复用+扩展** | 新增 `export_packages()`（解析 `winget export --output *.json` 的 `Sources[].Packages[].PackageIdentifier`，**必须用 `.exe` 全路径**，PATH 里没有）；`search_key()`/`pick_best()` 名称匹配降级为兜底 |
| `src/software_reback/downloader.py` | 客户端 M2 | **复用（零改动）** | `download_url` / `sha256_of_file` / `safe_file_name` / `build_ssl_context` 与 `.part` 原子改名逻辑全部保留；云端决策只是新的上游数据源 |
| `src/software_reback/resolver.py` | 客户端 M2 | **扩展** | `plan_for()` 新增最高优先级：**云端决策** > 目录直链 > 记录自带 `package_id` > 名称匹配 > unresolved；`DownloadPlan` 增加 `decision_id`/`confidence` |
| `src/software_reback/catalog.py` | 客户端 M4 本地缓存 | **扩展** | 新增 `from_snapshot()`（吃云端快照 payload 转 `CatalogEntry`）与 `save_snapshot()`；`load_catalog`/`find_entry`/`normalize_name` 复用，`CatalogEntry` 增加 `entry_id`/`status`/`scope` |
| `src/software_reback/store.py` | 客户端清单读写 | **扩展** | `SCHEMA_VERSION` 升到 2；`load_inventory` 需能读 v1（按 03 文档 6.2 补默认字段）；`write_report` 的 `REPORT_FIELDS` 增加 `source`/`decision_id`（追加在末尾，不破坏现有 CSV 消费方） |
| `src/software_reback/cli.py` | 客户端入口 | **扩展** | 新增 `cloud` 子命令组：`login/logout/register/device/push/pull/catalog/contribute`；现有 `scan`/`download` 参数不破坏 |
| `src/software_reback/__main__.py` | 入口 | 复用 | 不改 |
| `tests/*`（64 项） | 回归基线 | **不改** | 任何新改动必须保持 64 项全绿；新测试另建文件 |
| `pyproject.toml` | 打包 | 扩展 | 服务端作为独立包 `cloud/`（服务器依赖隔离），客户端依赖仍为空 |

云端新增代码建议目录（本轮不落地，仅定边界）：

```text
server/software_reback_cloud/
  __main__.py  api.py  router.py  auth.py  db.py
  inventory_service.py  catalog_service.py  download_service.py  audit.py
  migrations/001_init.sql
```

## 5. 部署拓扑

### 5.1 目录布局

```text
~/apps/software-reback-cloud/
├── app/                 # 服务端代码（本地 rsync 推入；notebook 不可达 github.com，禁止 git clone / pip git+https）
├── venv/                # python3.12 -m venv（实测可用）；pip install -r requirements.txt 只从 pypi 拉（实测 200）
├── data/
│   ├── app.db           # SQLite 主库（UMask=0077 → chmod 600）
│   └── backups/app-YYYYMMDD.db   # 每日 03:30 的 .backup 快照（sqlite3 在线备份，不用 cp）
├── logs/
│   ├── app.log          # RotatingFileHandler 10MB × 5
│   └── access.log
└── etc/config.json      # 端口、限流阈值、内存预算（不含任何真实 token / 密钥）
~/.config/software-reback-cloud/
├── jwt_secret           # 32 字节随机（chmod 600，setup 脚本一次性生成，不进仓库）
└── .env                 # 环境变量覆盖项（chmod 600）
```

### 5.2 systemd --user unit（完整片段）

`~/.config/systemd/user/software-reback-cloud.service`：

```ini
[Unit]
Description=software-reback cloud API (single process, stdlib http.server)
Documentation=file:///%h/apps/software-reback-cloud/README.md
After=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=%h/apps/software-reback-cloud
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=%h/apps/software-reback-cloud/app
Environment=SRC_DATA_DIR=%h/apps/software-reback-cloud/data
Environment=SRC_LOG_DIR=%h/apps/software-reback-cloud/logs
Environment=SRC_BIND=0.0.0.0:8084
Environment=SRC_JWT_SECRET_FILE=%h/.config/software-reback-cloud/jwt_secret
ExecStart=%h/apps/software-reback-cloud/venv/bin/python -m software_reback_cloud
Restart=always
RestartSec=3
KillSignal=SIGTERM
TimeoutStopSec=15
StandardOutput=journal
StandardError=journal
SyslogIdentifier=srcloud
# 资源上限：4 核机器（已跑 27+ 容器），单进程留 1 核余量；内存按 100MB 目标卡死
CPUQuota=100%
MemoryMax=128M
MemoryHigh=96M
TasksMax=64
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=%h/apps/software-reback-cloud/data %h/apps/software-reback-cloud/logs
UMask=0077

[Install]
WantedBy=default.target
```

> `MemoryHigh=96M` / `MemoryMax=128M` 是硬闸：一旦某次改动让常驻内存超预算，**systemd 会直接 OOM-kill 并 `Restart=always` 拉起**，表现为服务周期性重启 —— 这正是希望被立刻发现的信号（配合 `journalctl --user -u software-reback-cloud | grep -i oom`）。

启用与自检（在 notebook 上执行，用户名为 `hdturk`）：

```bash
sudo loginctl enable-linger hdturk             # 开机自启的前提；见 5.4
systemctl --user daemon-reload
systemctl --user enable --now software-reback-cloud.service
systemctl --user status software-reback-cloud.service --no-pager
ss -ltnp | grep 8084                           # 期望: LISTEN 0.0.0.0:8084
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8084/api/v1/health   # 期望: 200
systemctl --user show -p MemoryCurrent software-reback-cloud.service          # 期望 < 104857600
loginctl show-user hdturk -p Linger            # 期望: Linger=yes
journalctl --user -u software-reback-cloud -n 50 --no-pager
```

### 5.3 监听与端口

| 项 | 值 | 依据 |
|---|---|---|
| 服务名 | `software-reback-cloud` | PLAN-SPLIT 统一术语 |
| 监听 | `0.0.0.0:8084` | 8081–8089 为 frp 预留段，本方案取 8084 |
| frp 映射 | `cloud1:20084 → 192.168.1.24:8084` | 既有映射规则（2008x → 808x），外网访问同端口意图 |
| 已占用端口（不得使用） | 22/80/443/3080/5003/8080/8083/8090/9443 | `ss -ltnp` 实测 |
| 健康检查 | `GET /api/v1/health`（免认证，只回 `{ok,data:{status,version}}`） | 供 frp / 监控探活 |
| 并发 | `ThreadingHTTPServer`，`daemon_threads=True`，连接超时 30s，并发线程上限 8 | 单进程多线程 + 100MB 预算足够；不代理大文件（见 8） |

### 5.4 `Linger=no` 的风险与处理（**已实测确认，必须处理**）

实测：`loginctl show-user hdturk -p Linger` → **`Linger=no`**。含义：`systemd --user` 实例随 `hdturk` 的**最后一个 session 退出而销毁**，因此

- **notebook 重启后服务不会自动启动**（用户实例根本没被拉起，`enabled` 也不生效）；
- ssh 全部断开且无残留会话后，服务可能在数分钟内被 logind 杀掉，`Restart=always` 也救不回来；
- 表现为「昨天还好好的，今天连不上」，且 journal 里没有任何崩溃记录 —— 排查成本最高的一类故障。

| 方案 | 做法 | 取舍 |
|---|---|---|
| **A（推荐）开启 linger** | `sudo loginctl enable-linger hdturk`（等价 `Linger=yes`），随后 `systemctl --user enable software-reback-cloud.service` | ✅ 开机即自启、无 session 也常驻、断 ssh 不影响；❌ 需一次 **sudo**（一次性，不碰容器/网络配置）；代价是常驻约 60MB |
| **B 维持 `Linger=no`** | 每次重启后手动 `systemctl --user start`，并保证有人长期在线（tmux + ssh） | ✅ 不需要 sudo、进程随登录会话生灭更「干净」；❌ **重启即不可用**，必须人工干预，不适合作为长期云端；不适合「重装 Windows 期间还要拉清单」的场景 |
| C 迁到 system 级 unit（`/etc/systemd/system/`） | 加 `User=hdturk`，`systemctl enable --now` | ✅ 开机自启且不依赖 linger；❌ 同样要 sudo，且偏离「systemd --user」约定，需另写 `User=`/`Group=`，与 PLAN-SPLIT 不符 → 仅作为 A 被拒时的备选 |

**结论**：部署验收必须包含 A；若组织策略禁止 sudo，则**必须在 07-roadmap 中把 B 的「重启后手动拉起」写成显式运维步骤**，并在客户端加入「云端不可达 → 降级到本地 `software.json`」的兜底（见 D10 与 7.1）。

**验证方式**（三选二即可判定）：

```bash
loginctl show-user hdturk -p Linger        # 期望: Linger=yes
# 断开所有 ssh 会话，等 3 分钟后再从别的机器：
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.1.24:8084/api/v1/health   # 期望: 200
# 重启 notebook 后（不登录）：
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.1.24:8084/api/v1/health   # 期望: 200
```

## 6. 关键设计决策

| # | 决策 | 背景 | 选择 | 影响 |
|---|---|---|---|---|
| D1 | 不用 Docker | notebook 上 27+ 容器常驻（Dify 14 + Plane 13 + Stirling + LibreTV），11G 内存已用约 5G；用户明确「不碰现有 16 个容器」 | systemd `--user` 单进程直跑 venv | ✅ 零容器侵入、常驻 < 100MB（目标值，见 2.1）、不抢既有编排资源；❌ 无镜像化一致性，部署靠 rsync + `daemon-reload`；**`Linger=no` 必须处理**（5.4） |
| D2 | SQLite 而非 Postgres | 单进程、单写者、数据量级 < 10⁵ 行；余量约 6G，Postgres 常驻 150MB+ 并额外占 5432 端口 | SQLite 3.45.1 + WAL + `busy_timeout=5000` + `cache_size=-16000` | ✅ 备份即复制文件、无额外守护进程与端口；❌ 无法水平扩展、无原生行级权限，**隔离必须由 SQL 谓词保证**（M3 负面测试兜底） |
| D3 | Bearer token 而非 session cookie | 客户端是 CLI（`urllib`），无浏览器 cookie jar；cookie 会引入 CSRF 与 SameSite 语义；frp 转发 HTTP 无 TLS 时 `Secure` cookie 也无法生效 | `Authorization: Bearer <HS256 JWT>`，声明含 `sub=account_id`、`did=device_id`、`exp`、`jti`；**库里只存 token 的 SHA256 摘要** | ✅ CLI 一句话携带、可逐设备吊销、**拖库也拿不到可用 token**；❌ token 泄漏即等于该设备身份，需本地限权（8 节） |
| D4 | 按设备维度隔离 | 一人多机；重装前后是「同一逻辑机器、不同物理状态」；只看账号会让 A 机读 B 机清单 | 资源键 `(account_id, device_id, ...)`，token 绑定单一 `device_id` | ✅ 清单/贡献/审计全部可按机归属，负面测试可逐条证明；❌ 换机需 `device transfer`，否则旧机数据不可见 |
| D5 | 清单上报优先 `winget export` ID | 实测：注册表 55 条，名称匹配只中 14/55（25.5%）；`winget export` 给出 52 条精确 ID | 识别优先级 `export_id` > 目录 `display_name` > 名称匹配兜底 > unresolved；**`inventory_items.export_id` 必须是独立列** | ✅ 可解析率 50/55 = **90.9%**；❌ 依赖 winget v1.29.380 与 `.exe` 全路径调用 |
| D6 | 不托管安装包本体 | 多数厂商 EULA 禁止再分发；磁盘与带宽不应为它准备；README 已明确「不缓存、不再分发」 | 服务端只返回下载决策 `{method:"url", url, sha256}` 或 `{method:"winget", winget_id}` | ✅ 无法务风险、存储恒定在 MB 级、8084 不会被大文件拖垮；❌ 下载成功率取决于厂商站点，需目录 `health` 字段与客户端重试 |
| D7 | 目录版本化 + `etag` 增量 | 目录会被多人贡献；客户端需低带宽同步 | `catalog_versions` 递增版本号 + 快照 `etag`；`If-None-Match` 命中回 304 | ✅ 二次拉取通常 < 1KB；❌ 需维护版本号与 `change_seq`，写路径必须串行（SQLite 单写者天然满足） |
| D8 | 贡献走审核队列而非直写 | 目录直接决定客户端下载什么，被投毒等于批量投毒 | 贡献默认 `status=pending`；账号自己的条目可 `scope=private` 立即生效 | ✅ 单账号可自用，公共目录不被单人污染；❌ 公共目录初期靠人工审核 |
| D9 | token 只存摘要 | 数据库文件在磁盘上，备份会被复制；原文 token 等价于长期凭证 | `tokens.token_sha256` 存 `sha256(raw)`，登录时返回原文一次，之后只比对摘要 | ✅ 拿到 `app.db` 也无法冒用；❌ 服务端**无法**为用户「重新显示」token，丢了只能重新登录（这是可接受的） |
| D10 | 提供 `cloud push` 的离线兜底 | `Linger=no` 时云端可能不在线，而重装前恰恰最需要拿到清单 | 先落本地 `software.json`，再上报；上报失败只告警不阻塞 | ✅ 云端故障不阻断重装流程；❌ 多一份本地副本需纳入 `.gitignore`（现状已如此） |

## 7. 数据流时序

### 7.1 链路 A：重装**前**上报（客户端 → 云端）

```text
用户            CLI(cloud push)         M1 读取              云端 8084                SQLite
 │  push  ─────────►│                     │                     │                       │
 │                  │ 1 取本地 token      │                     │                       │
 │                  │   校验 exp/device   │                     │                       │
 │                  │ 2 已登录? 否───────►│ login 提示退出      │                       │
 │                  │ 3 scan ────────────►│                     │                       │
 │                  │                     │ 3a 注册表 55 条     │                       │
 │                  │                     │    (winreg)         │                       │
 │                  │                     │ 3b winget export    │                       │
 │                  │                     │  --output *.json    │                       │
 │                  │                     │    → 52 条精确 ID   │                       │
 │                  │                     │ 3c 合流/去重→v2     │                       │
 │                  │ 4 先落本地 backup.json ◄┤                   │                       │
 │                  │ 5 POST /inventories ──────────────────────►│ 6 验签 parse claims   │
 │                  │    Idempotency-Key: <sha256(report)>       │ 7 校验 body vs token  │
 │                  │                                            │   device_id 不一致→E_DEVICE_MISMATCH
 │                  │                                            │ 8 事务: inventory 行  │
 │                  │                                            │   + N 条 items ──────►│ BEGIN IMMEDIATE
 │                  │                                            │ 9 写 audit_logs ─────►│ COMMIT
 │                  │◄────────── 201 {ok:true, data:{inventory_id, version, items_count, resolved_count, unresolved_count}}
 │◄── 打印上报摘要 ─┤                                            │                       │
 │                  │ (失败/超时) 不再重试 → 本地 backup.json 就是兜底                    │
```

要点：**先落本地、再上报**；上报失败不阻塞用户重装；`Idempotency-Key` + `content_sha256` 双重去重，防重复提交产生多版本。

### 7.2 链路 B：重装**后**拉取（客户端 → 云端 → 官方源）

```text
用户         CLI(cloud pull)          云端 8084                官方站点/winget 源
 │ pull  ─────────►│                     │                         │
 │                 │ 1 POST /devices/register（重装后 dev 指纹同，复用 device_id）│
 │                 │ 2 GET /inventories?device_id=...  ──────────►│
 │                 │◄── 最新 version=n 的清单（v2）                 │
 │                 │ 3 写入本地 software.json（备份为 .prev）        │
 │                 │ 4 GET /catalog/snapshot?etag=... ───────────►│
 │                 │◄── 200 全量 或 304（If-None-Match 命中）       │
 │                 │ 5 POST /catalog/resolve （批量，≤200 条）─────────►│
 │                 │       body: {device_id, items:[{display_name, version, export_id, source}]}
 │                 │◄── {decisions:[{decision_id, method:"url"|"winget"|"unresolved", url, sha256, winget_id, confidence, reason}], summary}
 │                 │ 6 复用 resolver/downloader 执行下载              │
 │                 │     url  → GET 直链（服务端不中转）──────────────►│
 │                 │     winget → winget download --id ...  ─────────────────►│
 │                 │ 7 SHA256 校验失败→重试或标记 failed（不落半成品）│
 │                 │ 8 生成 download-report.csv（复用 store.write_report）│
 │◄── 汇总输出 ────┤                     │                         │
```

要点：拉取路径只做「读 + 决策」，第 6 步之后的字节流**不经过云端**；这也让 8084 不会被大文件下载拖垮。

## 8. 安全边界

| 边界 | 具体做法 | 验证手段 |
|---|---|---|
| 网络面 | 只监听 `0.0.0.0:8084`（局域网内可达），**不做公网 DNS/证书**；对外仅经 frp 映射（`cloud1:20084`）。HTTP 无 TLS 是已知取舍：局域网内可接受，**若开放到公网必须先上 TLS** | `ss -ltnp` 里该端口只属于本进程；`curl http://192.168.1.24:8084/api/v1/health` 返回 200，`https` 同端口无服务 |
| 认证面 | HS256 JWT，密钥在 `~/.config/software-reback-cloud/jwt_secret`（`chmod 600`，不进仓库）；`access_token` TTL 12h；`jti` 入库以支持单 token 吊销。**服务端 `tokens` 表只存 `sha256(raw_token)`，不存原文**——即使 `app.db` 或备份被拷走，也无法重放成可用凭证 | 伪造 token / 改 `sub` / 过期 token 分别返回 `E_UNAUTHENTICATED`、`E_UNAUTHENTICATED`、`E_TOKEN_EXPIRED`；`sqlite3 app.db 'SELECT * FROM tokens LIMIT 2'` 里**看不到**任何可用的 JWT 原文 |
| 口令面 | 口令用 `hashlib.scrypt(n=2**14, r=8, p=1)` + 16 字节随机 salt 存储；登录失败按账号限流 5 次 / 15 分钟 | `accounts.password_hash` 永不为明文；连续 6 次错误登录返回 `E_RATE_LIMITED` |
| 越权面（M3 核心） | 每条 SQL 必带 `account_id`；路径里的 `device_id` 必须满足 `devices.account_id = claims.sub`；否则 `E_FORBIDDEN`。**不靠「查到了就返回」**——统一用 `WHERE account_id = ? AND device_id = ?`，命中 0 行即 `E_FORBIDDEN`（避免用 404/403 差异泄漏资源存在性） | 04 文档负面测试矩阵：伪造他用户 token、篡改 `device_id`、跨账号读清单，必须全部 4xx 且库内无变更 |
| 口令牌存储（客户端） | `%APPDATA%\software-reback\token.json`，写入后 `icacls` 仅授予当前用户；**不写日志、不进 `software.json`、不进 `download-report.csv`** | `cloud status` 输出 token 指纹（`sha256` 前 8 位）而非原文 |
| 完整性 | 直链条目必须带 `sha256` 才可下载；客户端 `downloader.py` 先写 `.part`、校验通过才 `os.replace`，失败 `unlink` | `download-report.csv` 中 `status=failed` 且目录无残留；现有 64 测试已覆盖 `HashMismatch` |
| 数据面（个人信息） | 清单纯元数据（软件名/版本/发行商）属个人信息，不入 git（`software.json` 已在 `.gitignore`）；服务端 `app.db` 靠 `UMask=0077`；`install_location` 是可选字段，**默认不上报**（避免泄漏 `d:\hdt\...` 这类用户名路径） | `SELECT install_location FROM inventory_items LIMIT 5` 期望全为 `NULL` 或空 |
| 法律面 | **服务端不存储、不缓存、不代理任何第三方安装包字节**；只给「官方地址 + 哈希」。多数厂商 EULA 禁止再分发，因此架构上连中转口都没有 | 代码中不存在流式转发路由；`/api/v1/catalog/resolve` 只返回 JSON 决策 |
| 审计 | 所有写操作与个人数据读取追加 `audit_logs`（`account_id`/`device_id`/`action`/`target`/`result`），只追加不更新 | `GET /api/v1/audit/logs` 能按 `action=inventory.push` 找回该设备历史 |

## 9. 风险与待确认

| 风险 | 影响 | 缓解 |
|---|---|---|
| **`Linger=no`（已实测）** | **重启后不自动启动**；session 全退出后服务被 logind 回收 | 5.4 方案 A（`sudo loginctl enable-linger hdturk`）；部署验收必须含「重启+断 ssh 后仍 200」；方案 B 时客户端走 D10 离线兜底 |
| 无 TLS（仅局域网 HTTP） | 同网段可嗅探 token | 仅限可信局域网；开公网前必须 TLS，或改用 frp `stcp`；token TTL 缩短到 2h |
| 内存余量只有约 6G | 依赖膨胀会拖垮同机 27+ 容器 | 2.1 的 100MB 预算 + `MemoryMax=128M` 硬闸；处置规则已固定 |
| 直链失效 | 下载失败率上升 | 目录 `health` 字段 + 客户端失败回退到 `winget_id` |
| 5 个软件任何源都解析不到（55 - 50） | 永远 `unresolved` | 报告里单列「人工清单」，人工下载（与现状一致） |
| 单进程阻塞 | 慢客户端占线程 | `ThreadingHTTPServer` + 30s 超时 + `TasksMax=64`；不代理大文件已规避主因 |
| **notebook 不可达 github.com(000) / cdn.jsdelivr.net(000)** | 无法用 GitHub raw 的 schema、CDN 的前端资源 | 所有 schema 与静态资源随仓库 rsync 到 `app/`，**运行时零外链**；`pip` 只允许 pypi 源 |
| winget 版本漂移 | `export --output` 字段变化导致解析失败 | 解析层对未知字段宽容（只取 `PackageIdentifier`），失败降级为名称匹配 |
