# 07 · 实施路线图

> 功能点编号来源：`01-features.md`（总纲）。本文只做排期、依赖与验证，不重新定义功能。
> 统一基线见 `../PLAN-SPLIT.md`：代码基线 `G:\git\software-reback` 已有可运行 CLI（64 测试全绿，复用不重写）；云端 notebook `192.168.1.24`（Ubuntu 24.04 / Python 3.12 / 4 核 / 11G，已用 5G）；pypi 可达，`github.com` 不可达；落地形态 systemd --user 单进程，端口 `8084`。
> 工作量单位：**人日（预估）**。凡标「预估」的数字都是计划值，不是实测值。
>
> ⚠ **开工前必读**：`README.md` 的「评审结论：云端定位需要重新确认」一节指出，云端（M1）解决的是换机/多人这类**衍生需求**，而非原始需求（单人重装）。**M1 是否现在就做，需项目负责人确认**；M2/M3/M4 的价值不受影响，可独立推进。下表按「全部做」的完整路线列出，若选推迟 M1，则 M2 可直接接在 M0 之后。

## 1. 里程碑总览

| 里程碑 | 名称 | 目标 | 核心交付物 | 依赖 | 工作量（人日，预估） | 退出标准 |
|---|---|---|---|---|---|---|
| M0 | 基线与契约冻结 | 锁死 schema、接口、错误码、隔离键，避免并行返工 | `01`~`07` 六份文档定稿；`03-api-contract.md` 的 6 个接口签名冻结 | 无 | 2–3 | **✅ 已完成（2026-11-17）**：4 处口径冲突已定案，`schema_version: 2`、资源键 `(account_id, device_id, ...)`、错误码表在文档间完全一致 |
| M1 | 云端骨架与隔离 | 起一个能被证明隔离的 HTTP 服务 | systemd --user 单元 + `/healthz`；注册/登录；token 绑定设备；push/pull；审计日志；负面测试矩阵全绿 | M0 | 5–7 | `curl /healthz` = 200；负面测试矩阵 100% 拒绝；重启后服务 `active` |
| M2 | 读取强化 | 把覆盖率从 25% 拉到 ≥90% | `winget export` + `winget list` 双路融合；MSIX 识别；`install_scope`；清单 v2 | M0（字段已冻结） | 3–5 | 本机 55 条中 ≥50 条带 `winget_id` **且 `parse_errors == 0`**；72 条 MSIX 被识别并标记跳过 |
| M3 | 下载强化 | 让下载可中断、可重试、不失真 | 断点续传、并发限速、失败重试、缓存复用 | M2 | 4–6 | 人为断网续传后 SHA256 一致；报告成功率达目标；单条失败不中断整批 |
| M4 | 目录运营 | 补上 winget 覆盖不到的尾巴，跑通目录维护 | 目录 schema v2、来源合并、SHA256 状态、失效检测、健康度、贡献审核 | M2、M3 | 6–8 | 目录含 ≥15 条真实条目（预估）；失效检测能产出健康度数字；新增条目可追溯到来源 |
| M5 | 加固与验收 | 全套回归 + 端到端验收 | 回归清单、验收脚本、风险回看 | M1–M4 | 3–4 | §5 全部命令通过；K1–K6 指标留档 |

合计：**23–33 人日（预估）**。

> **依赖变更说明**：原表中 M3 依赖「M1、M2」，M2 依赖「M1（需要云端存 v2）」。评审后调整为 **M3 只依赖 M2**——断点续传、并发、重试、缓存全部是本地下载器能力，与云端无关；M2 的 v2 清单也可直接落本地文件。这样 **M2 → M3 → M4 构成一条不依赖云端的完整可用链路**（13–19 人日）。

## 2. 任务分解（功能点 → 里程碑）

| 功能编号 | 里程碑 | 任务 | 依赖 |
|---|---|---|---|
| — | M0 | 冻结 6 个 HTTP 接口（注册/登录/push/pull/health/审计查询）与错误码表 | — |
| — | M0 | 冻结清单 `schema_version: 2` 字段集与 v1 兼容读取规则 | — |
| — | M0 | 冻结隔离资源键 `(account_id, device_id, ...)` 与 token 声明结构 | — |
| M3-01 | M1 | 账号注册 / 登录（密码 `salt + hash`，禁止明文落库与落日志） | M0 |
| M3-02 | M1 | token 生成与 `(account_id, device_id)` 绑定校验 | M3-01 |
| M3-03 | M1 | 清单存储按 `(account_id, device_id)` 分键（SQLite，单机足够） | M0 |
| M3-04 | M1 | 越权拒绝：伪造 token / 篡改 ID / 跨用户读写 | M3-02、M3-03 |
| M3-05 | M1 | 审计日志（结构化，敏感字段掩码，可过滤） | M3-01 |
| M3-06 | M1 | 配额（机器数 / 条目数 / 请求体大小） | M3-03 |
| M3-07 | M1 | systemd --user 单元 + `Linger=yes` + `/healthz` | M0 |
| M1-03 | M2 | `winget export` 采集（全路径调用，读 json） | M0 |
| M1-04 | M2 | `winget list` 解析（保留 Id / Version / Source） | M0 |
| M1-05 | M2 | 双路融合：export 优先，list 补全，归一化名对齐 | M1-03、M1-04 |
| M1-06 | M2 | MSIX / Store 应用识别（`MSIX\` 前缀 → 标记跳过） | M1-04 |
| M1-07 | M2 | `install_scope` 判定（注册表源 + `ARP\User\`/`ARP\Machine\`） | M1-04 |
| M1-09 | M2 | 名称匹配兜底保持（仅双路都失败时启用） | M1-05 |
| M1-10 | M2 | 环境快照（Windows 版本、winget 版本、采集耗时、各源条数） | M1-03、M1-04 |
| M1-11 | M2 | schema v1 → v2 兼容读取 | M0 |
| M1-01/02/08 | M2 | 回归现有三源读取、过滤、去重（不改行为，只加测试） | — |
| M1-05 | M2 | 采集落地：`scan` 一次运行同时调 export + list，输出 v2 清单（单进程，~1–2 分钟，与现有 `--enrich` 量级相当，预估） | M1-03、M1-04 |
| M2-01 | M3 | `cloud pull` 接入下载入口（先 pull 再 plan）—— **仅在 M1 已实施时需要**；未上云端时直接用本地 `software.json` | M3-02、M1-11 |
| M2-05 | M3 | 断点续传（`Range` + 206 回退全量） | — |
| M2-06 | M3 | 并发与限速（默认 3 并发；winget 通道串行） | M2-05 |
| M2-07 | M3 | 失败重试（网络类退避 3 次；哈希失败不重试） | M2-05 |
| M2-08 | M3 | 报告扩展（保持字段兼容，退出码约定不变） | M2-07 |
| M2-09 | M3 | 缓存复用（本地哈希匹配则跳过） | M2-04 |
| M2-02/03/04/10 | M3 | 回归直链、winget 通道、SHA256、人工清单 | — |
| M2-11 | M3 | 下载计划四级优先级固化并加测试（防止新增目录来源打乱顺序） | M2-02、M4-01 |
| M4-01 | M4 | 目录 schema v2（含来源、更新时间、状态字段） | M0 |
| M4-02 | M4 | 来源分级与冲突合并规则 | M4-01 |
| M4-03 | M4 | SHA256 登记与 `sha256_missing` 状态 | M4-01 |
| M4-04 | M4 | 失效检测（HEAD 探测 + `stale` 标记） | M4-01 |
| M4-05 | M4 | 健康度度量与分桶统计 | M4-04 |
| M4-06 | M4 | 贡献与审核状态流转 | M4-02、M4-03 |
| K1–K6 | M5 | 指标留档与回归 | M1–M4 |
| — | M5 | 端到端验收（重装前 → 重装后模拟） | M1–M4 |

## 3. 依赖顺序图

```
M0 基线与契约冻结 ──┬──> M2 读取强化 ──> M3 下载强化 ──> M4 目录运营 ──> M5 加固与验收
(已完成)            │   (双路融合 / v2 清单)   (续传/并发/重试)   (补 winget 尾巴)
                    │
                    └──> M1 云端骨架与隔离 ──（可选，确认需要换机/多人后再做）
```

**关键变化**：M2 → M3 → M4 → M5 是一条**不依赖云端**的完整链路（13–19 人日），可立即开工并交付可用工具。M1 作为并行支线，按需启动。

缩进树（并行关系与硬依赖）：

```
M0  基线与契约冻结（✅ 已完成）
├─(1) M2 读取强化 ──> M3 下载强化 ──> M4 目录运营 ──> M5 加固与验收
│        M1-05 双路融合产出 winget_id
│        └─> M4 只补「双路融合后仍解析不到」的条目
└─(2) M1 云端骨架与隔离（可选支线）
         M3-02 token 绑定
         └─> 若实施，M3 增加 M2-01「cloud pull 接入下载入口」

硬规则：M0 已完成，其余可开工。
        若做 M1，M3 需额外接 M2-01（cloud pull）；若不做 M1，M2-01 跳过。
        M4-04 / M4-05（失效检测、健康度）需 M3 完成，才有真实下载数据可统计。
```

**为什么是这个顺序：**

| 结论 | 理由 |
|---|---|
| 契约必须先冻结（M0 第一） | 云端（M1）与客户端（M2）由不同人并行；接口/字段一改，两边都要返工。冻结成本 2–3 人日，改一次的成本远高于此。**已完成** |
| **M1 可推迟，M2/M3/M4 不依赖它** | 云端解决换机/多人（衍生需求）；M2 的 v2 清单可落本地文件，M3 的续传/并发/重试是本地下载器能力，M4 是目录维护。三者构成不依赖云端的完整可用链路（13–19 人日） |
| M1 与 M2 可并行 | 二者只共享 M0 冻结的 schema 与错误码；M2 的产物是 v2 清单，不依赖服务实现 |
| M2 与 M3 要合流才测得了 | M3 的「下载强化」需要真实 v2 清单做样本；用 v1 清单（无 `winget_id` / `install_scope`）测续传与并发意义不大 |
| M4 在 M2/M3 之后 | 目录要补的正是「M2 双路融合后仍解析不到」的条目；先做目录等于盲目维护（现状 41 条 `skipped` 里有多少本来就该由 winget export 解决，未知） |
| M5 最后 | 指标与端到端验收需要全部模块就位 |

## 4. 风险表

| 风险 | 影响 | 概率 | 缓解措施 |
|---|---|---|---|
| notebook 出网受限（`github.com` / `cdn.jsdelivr.net` 不可达，实测 000） | 依赖 GitHub raw / CDN 的资源全部拉不到；安装失败排查困难 | 高（已实测） | 只用 pypi（已验证可装）与 npm 镜像；目录与文档不自建 CDN 依赖；任何从 GitHub 取数据的方案一律否决 |
| winget 输出格式不稳定（非 JSON、列宽随控制台变化） | 解析失败导致覆盖率掉回 25% | 中 | 复用现有 `parse_table` 的表头对齐 + 包 ID 特征兜底切分；每类命令都有固定样本的单元测试；解析失败时降级到下一路来源而不是报错 |
| 第三方安装包 EULA 与再分发 | 目录托管安装包本体可能违法 | 中 | 目录只存 URL 与 SHA256，不托管、不缓存安装包（与 README 一致）；贡献流程要求填写来源与版权说明 |
| 目录数据腐化（链接失效） | 目录命中率高但下载失败率高，用户信任下降 | 高（直链天然失效） | M4-04 定期 HEAD 探测 + `stale` 标记；报告里区分「无来源」与「来源失效」；一条目录记录保留备用来源 |
| 单机单账号场景下的隔离过度设计 | 多一层 `device_id` 校验，调试与上手成本上升 | 中 | 隔离只做最小必要（token 声明两个键、查询强制带键）；提供一键生成并保存 `device_id` 的命令；不做角色/权限矩阵 |
| `systemd --user` 的 `Linger=no` 导致重启不自启 | 重装后拉清单时云端不可用，主流程断裂 | 高（默认即 no） | 部署时执行 `loginctl enable-linger <user>`，并在文档里写明这是**主机级配置**、需人工确认；验收项固定包含「重启后 `systemctl --user is-active` = active」 |
| 4 核 11G 已用 5G，资源余量有限 | 并发请求下服务 OOM 或被 OOM killer 杀 | 中 | 单进程 + SQLite；请求体大小上限；不做后台大批任务；压测上限写死在验收里 |
| 端口冲突（22/80/443/3080/5003/8080/8083/8090/9443 已占用） | 服务起不来 | 低 | 固定用预留段 8081-8089 内的 `8084`，启动前 `ss -ltnp` 复核 |
| 我方直链下载在既有样本中失败过（如指向 GitHub Releases 的包） | 下载成功率达不到目标 | 中 | 失败条目归入目录人工清单（M2-10），由目录提供可用的官方直链；不重试无意义的失效源 |

## 5. 每个里程碑的验证方式

命令统一在 notebook 上执行（客户端命令在 Windows 上执行），前缀说明：`SRV` = `ssh` 到 `192.168.1.24`；`WIN` = 本机 PowerShell。

### M0 · 基线与契约冻结
```text
WIN> Select-String -Path docs\*.md -Pattern 'M[1-4]-\d{2}' | Measure-Object
WIN> python -m unittest discover -s tests          # 基线必须仍然是 64 OK
```
通过标准：6 份文档齐全；功能点编号在 `01` 中定义、在其他文档中被引用时无未定义编号；测试仍为 64 OK（本轮不改代码，必须不变）。

### M1 · 云端骨架与隔离
```text
SRV> systemctl --user is-active software-reback-cloud      → active
SRV> curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8084/healthz   → 200
SRV> ss -ltnp | grep 8084                                   → 0.0.0.0:8084
SRV> python -m pytest tests_cloud/test_isolation.py -v      → 负面矩阵全 passed（0 failed）
SRV> sudo reboot; # 重启后再查一次
SRV> loginctl show-user <user> | grep Linger                → Linger=yes
```
通过标准：服务处于 `active`；`/healthz` 返回 200；越权负面矩阵 100% 拒绝（K5 = 100%）；重启后自动拉起（`Linger=yes`）。

### M2 · 读取强化
```text
WIN> winget export -o $env:TEMP\e.json --accept-source-agreements   # 52 条 ID（PATH 里没有 winget 时用 %LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe 全路径）
WIN> $env:PYTHONPATH="src"; python -m software_reback scan -o software.json
WIN> python -c "import json;d=json.load(open('software.json',encoding='utf-8'));print(d['schema_version'],len(d['software']),sum(1 for s in d['software'] if s.get('winget_id')))"
```
通过标准：输出 `2 55 <n>` 且 `n` **≥50**（K1 ≥90%）；MSIX 条目标记跳过数 = 72（K 侧记录）；未命中项恰为 Chrome / Office 2019 / PUBG / 向日葵 / 游戏加加 5 条。

### M3 · 下载强化
```text
WIN> $env:PYTHONPATH="src"; python -m software_reback cloud pull -o software.json
WIN> python -m software_reback download -i software.json -d downloads --dry-run
WIN> python -m software_reback download -i software.json -d downloads --concurrency 4
WIN> echo $LASTEXITCODE   → 0 表示无 failed 项
WIN> certutil -hashfile downloads\<样本>.exe SHA256   # 与目录 sha256 比对一致
```
通过标准：`--dry-run` 计划中无 `unresolved` 的 winget 源被错误降级；报告 `ok` 占比达到 K3 目标；人为断网后续传文件哈希与原始一致；有失败项时退出码 2。

### M4 · 目录运营
```text
SRV> python -m software_reback_catalog health --catalog catalog.json
     → 输出 {total, available, stale, sha256_missing, health_pct}
SRV> python -m software_reback_catalog probe --catalog catalog.json --dry-run
     → 逐条输出 HTTP 状态码，失败条目标记 stale
```
通过标准：所有带直链条目都有哈希状态（`ok` / `sha256_missing`）；失效检测能产出健康度数字；新增条目 100% 可追溯到来源字段。

### M5 · 加固与验收
```text
WIN> python -m unittest discover -s tests                                    → 64+ OK
SRV> systemctl --user restart software-reback-cloud && curl -s .../healthz    → 200
```
通过标准：K1–K6 六项指标全部留档（含现状值与目标值）；端到端流程（重装前 scan → push → 模拟重装清空本地 → pull → download）走通一次。

## 6. 本轮不做什么

| 不做 | 说明 |
|---|---|
| 不部署、不改服务器 | notebook 上不启服务、不动 systemd、不执行 `enable-linger` |
| 不改现有代码 | `src/` 与 `tests/` 保持现状，64 测试结果必须不变 |
| 不动现有 16 个容器与 Docker | 与 `PLAN-SPLIT.md` 前提一致 |
| 不写真实密码 / token / 私钥 | 示例一律占位符（如 `Authorization: Bearer <TOKEN>`） |
| 不做安装执行与安装包托管 | 范围外（见 `01-features.md` §7） |
| **不做客户端 GUI** | 设计已定稿于 [`08-client-ui.md`](08-client-ui.md)，但**未排入本路线图**。启动条件见该文档 §9.3：需先完成双路融合（覆盖率 ≥90%）、下载强化、目录 ≥15 条真实条目 |
| 不承诺工期 | 本文件所有工作量均为**预估**，需实际排期确认 |
