# 01 · 功能清单（总纲）

> 本文件是 **功能总纲**：模块编号、功能点编号、优先级、验收标准以本文为准。
> 后续 `02-architecture.md`、`03-api-contract.md`、`04-isolation.md`、`05-catalog.md`、`06-client.md`、`07-roadmap.md` 必须引用本文编号，不得另立编号体系。
> 统一前提见 `../PLAN-SPLIT.md`（**已归档**：仅引用其「已确认的前提」中的实测事实数据，任务分派部分已失效）。

## 1. 一句话定位

**把「重装 Windows 前这台机器装了哪些软件」变成一份云端可拉取、可校验的清单，重装后一键把安装包取回本地。**

解决什么问题（用户场景）：

| 阶段 | 现状痛点 | 本项目提供 |
|---|---|---|
| 重装前 | 装了几十个软件，靠记忆和截图整理，容易漏 | `scan` 自动读取 → `cloud push` 上报到云端，按账号 + 机器隔离保存 |
| 重装后 | 逐个上网找官网下载，链接失效、版本混淆、下到山寨包 | `cloud pull` 拉回清单 → 按目录直链 / winget 通道批量下载 → SHA256 校验 |

边界一句话：**只做「记录 + 取回」，不做「执行安装」**（理由见 §7）。

## 2. 模块总览

| 模块 | 名称 | 一句话职责 | 优先级 | 当前状态 |
|---|---|---|---|---|
| M1 | 读取 | 把本机已安装软件读成结构化清单，并尽量绑定精确 winget 包 ID | P0 | 已有 registry 读取 + 名称匹配；需强化 |
| M2 | 下载 | 按清单把每个软件翻译成「从哪下、怎么校验」并批量取回 | P0 | 已有直链 + winget 下载与 SHA256；需强化 |
| M3 | 隔离 | 用 account_id + device_id 双维度保证清单只有本人、本机能读写 | P0 | 未实现（本轮新增云端） |
| M4 | 汇总 | 维护「软件 → 下载来源」目录，补 winget 覆盖不到的部分 | P1 | 只有本地 `catalog.example.json`；需运营化 |

> **客户端 GUI 不在本表**：桌面界面设计见 [`08-client-ui.md`](08-client-ui.md)（`UI-01`~`UI-22` 独立编号，设计定稿、实现延后）。GUI 是**交付形态**而非新功能模块——它的每个能力都对应 M1/M2/M4 中的既有功能点，因此不占用本文件的模块编号。

优先级口径：**P0** = 缺了主流程走不通；**P1** = 主流程可用但体验/可靠性不达标；**P2** = 锦上添花，可延后。

## 3. 模块 M1 · 读取

职责：本机软件清单的采集与识别。复用 `src/software_reback/inventory.py`（三源注册表读取、过滤、去重合并）与 `winget.py`（表格解析、匹配）。

| 编号 | 功能点 | 说明 | 优先级 | 验收标准 |
|---|---|---|---|---|
| M1-01 | 注册表三源读取 | 读 `HKLM\...\Uninstall`、`HKLM\WOW6432Node\...\Uninstall`、`HKCU\...\Uninstall` 三处（与「设置 → 已安装的应用」同源） | P0 | 三条路径各自可独立遍历；任一键缺失时跳过不崩溃；本机样本读出 55 条（去重后） |
| M1-02 | 安装项过滤 | 丢弃无 `DisplayName`、`SystemComponent=1`、有 `ParentKeyName`（补丁/子项）的条目 | P0 | 单元测试覆盖 3 类过滤各 1 条，均不进入输出；无 `DisplayName` 条目不产生空名记录 |
| M1-03 | winget export 精确 ID | 用全路径 `%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe export -o <tmp>.json` 取包 ID（PATH 里没有 winget，必须全路径） | P0 | 本机样本导出 52 条 `PackageIdentifier`；生成的 json 可被 `json.load` 解析 |
| M1-04 | winget list 全量枚举（含 MSIX 与 Source 列） | 解析 `winget list` 表格，保留 `Id` / `Version` / `Source` 三列；`MSIX\...` 形态的 Id 与空 Source 的 `ARP\...` 形态都要能落表 | P0 | 本机样本**原始输出 155 行 / 数据行 153 行**（表头前有一个空行）；其中 `MSIX\` 前缀 72 行、Source 列为 `winget` 63 行；不含表头与分隔线 |
| M1-05 | winget export + winget list 双路融合 | export 给精确 ID，list 给全量名称→ID 映射；两路取并集并按归一化名对齐，export 优先 | P0 | 本机样本 55 条中 **≥50 条**能关联到 winget 包 ID；export 的 52 个 ID 在 list 中 52/52 可命中 |
| M1-06 | MSIX / Store 应用识别 | 识别 `winget list` 中 `MSIX\` 形态的条目（appx 家族名），标记 `source=msix`，不当作可下载项 | P0 | 本机样本识别出 72 条 MSIX/Store 应用；`source=msix` 条目在下载计划里一律 `skipped` 且 `detail` 写明「Store 应用走我的库」 |
| M1-07 | 用户级 vs 机器级安装判定 | 依据注册表源（`HKCU` → user，`HKLM` → machine）与 `winget list` 中 `ARP\User\...` / `ARP\Machine\...` 标记，写出 `install_scope` 字段 | P0 | 输出中 `install_scope` 只允许 `user` / `machine` / `unknown`；本机样本 `ARP\User\` 与 `ARP\Machine\` 条目判定与注册表源一致率 100% |
| M1-08 | 去重合并 | 同名同版本多条合并为一条，缺失字段互相补齐（复用 `merge_records`） | P0 | 同 `(归一化名, 版本)` 只保留 1 条；合并后 `publisher` / `install_location` 空字段被其他条补齐 |
| M1-09 | 名称匹配兜底 | 双路都拿不到 ID 时，按名称搜索 winget（精确轮 → 归一化轮，候选必须唯一） | P1 | 有歧义时（如 `Python 3.12` 与 `Python 3.13` 同时命中）返回未匹配，不猜；13 项名称匹配单元测试全绿 |
| M1-10 | 环境信息快照 | 清单头部写入 `schema_version: 2`、`generated_at`、Windows 版本、winget 版本、采集耗时、各源条数 | P1 | 头部字段齐全；`schema_version` 恒为 2；客户端能读 v1 清单并按 v2 升级输出 |
| M1-11 | 清单 schema v1 → v2 向后兼容 | v2 新增 `install_scope` / `winget_id` / `source` / `env`；读 v1 时字段补默认值 | P0 | 现有 `software.json`（v1，55 条）无需改动即可被新版读取，读入 55 条不报错 |

**M1 现状基线（本机样本，可复现）**

| 指标 | 数值 | 说明 |
|---|---|---|
| 注册表清单条目 | 55 | `software.json` |
| `winget export` 可用包 ID | 52 | 其余 8 个软件无法从任何源解析 |
| 按名称匹配覆盖率（现状） | 25%（14/55） | README 实测，41 条落 `skipped` |
| 双路融合覆盖率（目标） | ≥90%（≥50/55） | 主控实测：精确名 + 归一化关联 `winget list` 命中 50/55 = 90.9% |
| 未命中 5 条 | Chrome / Office 2019 / PUBG / 向日葵 / 游戏加加 | Chrome 无独立卸载项需另处理；其余属 winget 未收录或名称差异 |

## 4. 模块 M2 · 下载

职责：清单 → 下载动作。复用 `resolver.py`（四级优先级）、`downloader.py`（流式下载 + SHA256 + `.part` 原子改名）、`cli.py`（编排与报告）。

| 编号 | 功能点 | 说明 | 优先级 | 验收标准 |
|---|---|---|---|---|
| M2-01 | 云端拉清单 | `cloud pull` 用 Bearer token 拉取 `(account_id, device_id)` 下的清单，落盘为本地 `software.json` | P0 | 拉取后本地文件可被 `load_inventory` 读出且条数与云端一致；无 token 返回 401 |
| M2-02 | 目录直链下载 | 按软件目录 `url` 直链下载，支持 `file_name`、`sha256`（复用 `download_url`） | P0 | 单条直链下载成功且文件落在 `-d` 目录；`catalog.example.json` 能正常加载 |
| M2-03 | winget 通道下载 | 按包 ID 调 `winget download --id ... --exact`，把新增文件记入报告 | P0 | 成功时报告 `method=winget`、`target` 为新增文件路径；失败时 `status=failed` 且带 winget 输出尾部 |
| M2-04 | SHA256 校验 | `sha256` 非空即强校验，不匹配判失败且不留半成品 | P0 | 构造哈希不匹配用例 → 抛 `HashMismatch`，目录中不存在残留文件与 `.part` |
| M2-05 | 断点续传 | 已存在 `.part` 时用 `Range` 续传；服务器不支持（206 不返回）则整文件重下 | P1 | 中断后续传：最终 SHA256 与原文件一致；服务器忽略 Range 时仍能完成且不损坏 |
| M2-06 | 并发与限速 | 可配并发数（默认 3）与总速率上限；winget 通道串行（并发易冲突） | P1 | `--concurrency 4` 时不再出现「已存在目标文件」类错误；限速下实测平均速率不超过设定值 ±20% |
| M2-07 | 失败重试 | 网络类错误指数退避重试 3 次；哈希不匹配不重试 | P1 | 模拟首次 500 → 第二次 200 时最终 `ok`；哈希不匹配只尝试 1 次 |
| M2-08 | 下载报告 | 输出 `download-report.csv`（UTF-8 BOM），字段沿用 `name/version/method/status/target/detail`，失败时退出码 2 | P0 | 报告可被 Excel 直接打开不乱码；有失败项时 `exit code = 2` |
| M2-09 | 缓存复用 | 本地已存在且 SHA256 匹配的安装包直接跳过，报告记 `cached` | P2 | 二次执行时命中缓存条目 `status=cached` 且不发起网络请求 |
| M2-10 | 未解析条目进人工清单 | 无任何来源的记录写 `unresolved` 并汇总成待补清单 | P0 | 本机样本中未命中的记录 100% 出现在人工清单，且不允许被猜测填充 |
| M2-11 | 下载计划四级优先级固化 | 目录直链（可带 SHA256）> 记录自带包 ID > 名称匹配 > 未解析；顺序不得因新增来源而打乱 | P0 | 同一记录同时命中四级时只产出一条计划，且 `method=url`；4 条既有优先级单元测试保持全绿 |

## 5. 模块 M3 · 隔离

职责：云端单进程 HTTP 服务的账号与数据隔离（systemd --user，监听 `0.0.0.0:8084`）。详细设计见 `04-isolation.md`。

| 编号 | 功能点 | 说明 | 优先级 | 验收标准 |
|---|---|---|---|---|
| M3-01 | 账号注册 / 登录 | 用户名 + 密码注册与登录，密码只存 `salt + hash`，不存明文 | P0 | 注册后可登录拿到 token；数据库中检索不到明文密码（含日志） |
| M3-02 | token 与设备绑定 | token 绑定 `(account_id, device_id)`；**`device_id` 由服务端签发**（客户端自报的 ID 可被伪造重放，不采用） | P0 | 用 A 账号 token 携带 B 的 `device_id` 请求 → **404**；token 无 `device_id` 声明 → 401 |
| M3-03 | 清单按 (account_id, device_id) 隔离 | 资源键一律 `(account_id, device_id, ...)`，存储与查询都带这两个键 | P0 | 同一账号两台机器的清单互不可见：A 机 push 两版后，B 机 pull 拿到的是自己的版本 |
| M3-04 | 越权拒绝 | 伪造他人 token、篡改 `account_id` / `device_id`、跨用户读写全部拒绝 | P0 | 负面测试矩阵（`04-isolation.md`）全部用例返回 401/404（**跨账号/跨设备一律 404，不用 403**），**拦截率 100%** |
| M3-05 | 审计日志 | 记录每次认证、push、pull 的时间、`account_id`、`device_id`、来源 IP、结果 | P1 | 每条请求一条结构化日志；含账号/密码/token 的字段被掩码；可按 `account_id` 过滤 |
| M3-06 | 配额 | 单账号清单条数上限、单账户最大机器数、请求体大小上限 | P1 | 超限返回 413/429 且给出明确错误码；单账号机器数超限时拒绝新 `device_id` |
| M3-07 | 服务自启与存活 | systemd --user 单元 + `Linger=yes`（否则重启后不自启）；提供 `/healthz` | P0 | 重启 notebook 后 `systemctl --user is-active software-reback-cloud` 为 `active`；`curl /healthz` 返回 200 |

## 6. 模块 M4 · 汇总（软件目录）

职责：「软件 → 下载来源」目录的 schema、来源、合并与健康度。详见 `05-catalog.md`。

| 编号 | 功能点 | 说明 | 优先级 | 验收标准 |
|---|---|---|---|---|
| M4-01 | 目录 schema | 定义目录条目字段（`display_name` / `url` / `file_name` / `sha256` / `winget_id` / `silent_args` / 来源 / 更新时间）并给出版本号 | P0 | 现有 `catalog.example.json` 无需改写即可被新 schema 读取；缺 `display_name` 的条目被丢弃 |
| M4-02 | 条目来源与合并 | 来源分级：官方站点 > winget 仓库元数据 > 人工提交；同 `display_name` 冲突时按来源等级与更新时间取胜 | P0 | 同一条目两个来源冲突时结果确定且唯一，并可回溯到来源字段 |
| M4-03 | SHA256 维护 | 提供哈希登记与更新流程；无哈希条目标记 `sha256_missing` | P0 | 目录中带直链的条目 100% 有 `sha256` 字段（可为空但必须显式标记状态） |
| M4-04 | 失效检测 | 定期 HEAD 探测直链，记录状态码与时间；连续失败标记 `stale` | P1 | 失效链接在下一轮检测中变为 `stale`，并在报告/清单中可见 |
| M4-05 | 健康度度量 | 目录健康度 = 可用条目 / 总条目，按来源与失效分桶统计 | P1 | 每次检测产出一个健康度数字与分桶明细，可对比前后变化 |
| M4-06 | 贡献与审核流程 | 贡献者提交条目 → 审核（含哈希复核）→ 合并发布 | P2 | 条目从提交到发布有状态流转记录（`pending` / `approved` / `rejected`） |

## 7. 明确不做（Out of scope）

| 不做的事 | 为什么不做 |
|---|---|
| 静默安装执行（下发 `silent_args` 并真正安装、回传状态） | 「下载即执行」把供应链风险变成任意代码执行；本轮复用的是用户自己机器上的已记录来源，仍需人工确认 |
| 托管 / 二次分发第三方安装包 | 多数软件 EULA 禁止再分发；且需要额外存储介质，与「无需 U 盘」的定位冲突 |
| 接受用户临时输入 URL 拼接下载 | 只按**已记录**的来源下载，避免被诱导到任意地址 |
| 驱动、Windows 设置、PATH、字体、开发环境迁移 | 与「软件清单」不是同一层问题，强行合并会拖慢主线 |
| Store 应用自动还原 | `winget download` 拉 msstore 包实测易失败；交给 Microsoft Store「我的应用」更可靠 |
| 引入 Docker / 动现有 16 个容器 / 改端口占用 22/80/443/3080/5003/8080/8083/8090/9443 | 云端实测约束：只用 systemd --user 单进程，预留 8081-8089，本方案取 8084 |
| 依赖 GitHub raw / CDN（`github.com`、`cdn.jsdelivr.net`）分发目录 | notebook 出网受限，实测 000；只能走 pypi / npm 镜像与自建托管 |
| 自动开启 `Linger` 等改变主机全局行为的操作不加说明 | 属于需要人工确认的主机级配置，必须在文档中写明理由（见 `07-roadmap.md` 风险表） |

## 8. 端到端主流程

| 步骤 | 动作 | 使用功能点 | 产物 |
|---|---|---|---|
| 1 | 重装前：`scan` 读三源注册表并过滤去重 | M1-01, M1-02, M1-08 | 本地 `software.json`（55 条） |
| 2 | 采集 winget export 与 winget list，双路融合绑定 ID | M1-03, M1-04, M1-05, M1-06, M1-07 | 带 `winget_id` / `install_scope` 的清单（目标 ≥50 条可绑定） |
| 3 | 写环境快照，输出 `schema_version: 2` | M1-10, M1-11 | v2 清单 |
| 4 | 注册 / 登录，**服务端签发 `device_id`** 并拿到绑定 token | M3-01, M3-02 | `(account_id, device_id)` token |
| 5 | `cloud push` 上报清单，云端按双维度落库并写审计 | M3-03, M3-05 | 云端该机器最新一版清单 |
| 6 | 重装 Windows（本工具不参与） | — | — |
| 7 | 重装后：`cloud pull` 拉回清单 | M2-01, M3-04 | 本地 `software.json` |
| 8 | 解析来源：目录直链优先 → 记录自带 ID → 名称兜底 → 未解析 | M2-02, M2-03, M2-10 | 下载计划（`--dry-run` 可先看） |
| 9 | 批量下载（并发、续传、重试）并校验 SHA256 | M2-04, M2-05, M2-06, M2-07 | 本地安装包目录 |
| 10 | 输出下载报告；未解析条目进人工清单 | M2-08, M2-10 | `download-report.csv` |
| 11 | 目录补漏：把未命中的条目补进目录并登记哈希 | M4-01, M4-02, M4-03 | 目录新版本 |

## 9. 关键指标（可度量）

| 编号 | 指标 | 现状基线 | 目标 | 度量方式 |
|---|---|---|---|---|
| K1 | 清单识别覆盖率（55 条中能关联到 winget 包 ID 的比例） | 25%（14/55，仅名称匹配） | ≥90%（≥50/55）**且 `parse_errors == 0`** | 对同一台机器跑 `scan` → 同时统计 `winget_id` 非空条数**与** `stats.parse_errors`；两者都满足才算达标（见 `06-client.md` §2.4.1） |
| K2 | 包 ID 解析率（已知可解析软件的 ID 完整率） | 52 条 export ID 可用 | export 的 52 条 100% 落入清单 | 对比 export 输出与清单的 `PackageIdentifier` 集合 |
| K3 | 下载成功率（有来源条目） | 未统计（仅单机试跑） | ≥95%（预估，需 M3 完成后实测） | 报告中 `status=ok` / (`ok`+`failed`) |
| K4 | 目录命中率（未解析条目被目录覆盖的比例） | 0（目录仍为示例） | ≥50%（预估，需 M4 运营后统计） | 人工清单条数 / 人工清单中在目录里有条目的条数 |
| K5 | 越权攻击拦截率 | 不适用（云端未上线） | **100%** | `04-isolation.md` 负面测试矩阵全通过，0 例泄漏 |
| K6 | 服务存活（重启后自启） | 不适用 | 重启后 `/healthz` 返回 200 | `systemctl --user is-active` + `curl /healthz` |

## 10. 与现有代码的复用边界

| 功能点 | 复用现状 | 需要新增 |
|---|---|---|
| M1-01 ~ M1-02、M1-08 | 直接复用 `inventory.py` | 无 |
| M1-03 ~ M1-05 | 复用 `winget.py` 的解析思路 | export / list 双路采集与融合（`winget.py` 现无 export 支持） |
| M1-06 ~ M1-07、M1-10 ~ M1-11 | 无 | 新字段与 schema 升级 |
| M2-01 | 复用 `store.py` 的清单读写 | `cloud` 子命令与 HTTP 客户端 |
| M2-02 ~ M2-04、M2-08 | 直接复用 `downloader.py` / `resolver.py` / `cli.py` | 基本无 |
| M2-05 ~ M2-07、M2-09 | 无（当前为串行、无重试、无续传） | 下载器扩展 |
| M3-01 ~ M3-07 | 无 | 云端服务全新增 |
| M4-01 ~ M4-06 | 复用 `catalog.py` 的加载与 `normalize_name` 索引 | 目录 schema v2、健康度与流程 |
