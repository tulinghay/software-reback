# 05 · 软件汇总 / 目录维护（M4）

> 服务对象：M1 读取、M2 下载。目录是「补漏入口」，解决 winget 覆盖不到的部分。
> 定稿依据：`PLAN-SPLIT.md`（统一基线）+ `README.md`（实测覆盖率）+ 本机 winget v1.29.380 实测。
> 仓库内唯一相关代码：`src/software_reback/catalog.py`（现有 `CatalogEntry` 6 个字段、以 `display_name` 归一化为键）。

## 1. 定位与边界

| 项 | 结论 | 理由 |
|---|---|---|
| 存什么 | 元数据：去哪下（`url` / `winget_id` / `msstore_id`）、怎么校验（`sha256` / `size`）、怎么识别（`match_keys` / `publisher`） | 与现有 `catalog.py` 定位一致 |
| 不存什么 | **安装包本体**。目录里没有任何 `.exe` / `.msi` / 二进制 blob | 再分发受 EULA 限制：多数商业软件（Office、微信、NVIDIA 驱动、Steam）EULA 明确禁止第三方再分发；仓库公开即构成再分发 |
| 为什么「不托管」还能用 | 只记官方地址，用户机器自己从官方源拉 | 这也是现有工具「不需要额外存储介质」的前提（README 开头） |
| 合规红线 | 不收破解站、网盘直链、「绿色版」、带捆绑安装器的聚合站 | 见 §11 |
| 与清单的关系 | 清单（`software.json`，55 条）记录「装了什么」；目录记录「怎么弄回来」。二者靠匹配键关联，**清单里不内嵌目录数据** | 清单属个人信息（`software.json` 已在 `.gitignore`），目录是公共数据可共享 |

## 2. 条目 schema v2（`catalog_version: 2`）

现有 `CatalogEntry` 只有 `display_name / url / file_name / sha256 / winget_id / silent_args`，问题有三个：用显示名当主键（改名即失效）、没有别名（微信/Weixin/WeChat）、没有版本与健康度。v2 补齐。

| 字段 | 类型 | 必填 | 用途 / 说明 |
|---|---|---|---|
| `entry_id` | string | 是 | **稳定主键**，形如 `cat-cn-weixin-universal`。一旦分配永不变更；显示名、URL、版本都可改，主键不能改 |
| `display_name` | string | 是 | 人类可读名，**只用于展示**，不作索引键（现有实现拿它当键，是 v2 要修的） |
| `match_keys` | string[] | 是（≥1） | 别名数组，大小写/全半角/多余空白归一化后比较。解决「微信 / Weixin / WeChat / WeChatSetup」 |
| `publisher` | string | 否 | 用于消歧（同名不同厂商），也用于与注册表 `Publisher` 交叉验证 |
| `install_scope` | enum | 否 | `machine` / `user` / `any`，对应注册表 HKLM / HKCU。用于同名多条目区分（如 VS Code System 与 User） |
| `channel` | enum | 是 | `direct` / `winget` / `msstore`，**由校验器派生**，不由人填 |
| `url` | string | 条件 | `channel=direct` 时必填；必须是 `https://` |
| `file_name` | string | 条件 | `channel=direct` 时必填（含扩展名），用于落盘命名与 `safe_file_name` 校验 |
| `sha256` | string(64 hex) | 建议 | 空值允许（见 §7），非空即强校验 |
| `size` | integer | 否 | 字节数，用于 Content-Length 一致性与断点续传总长校验 |
| `winget_id` | string | 条件 | `channel=winget` 时必填，来自 `winget export` 的精确 ID（优先级最高的来源） |
| `msstore_id` | string | 条件 | `channel=msstore` 时必填，形如 `9WZDNCRFJ3PZ`（Store 产品 ID）。**不要填 `XPDDRBQ2D1N7NJ`**：那是 `winget search` 输出的 ID，`winget show --id XPDDRBQ2D1N7NJ` 可解析，属于 Store 应用标识，与「产品 ID」是两个命名空间，入库前必须用 `winget show --id … --exact` 验证 |
| `version` | string | 否 | 该 `url` 对应的版本。为空表示「跟随官方最新」 |
| `arch` | enum | 否 | `x64` / `x86` / `arm64` / `any` |
| `lang` | string | 否 | `zh-CN` / `en-US` / `any` |
| `source_type` | enum | 是 | `official`（厂商官网）/ `vendor`（厂商自有 CDN，如 `dldir1v6.qq.com`）/ `winget`（从 manifest/show 提取）/ `manual`（人工录入），见 §4 |
| `verified_at` | ISO8601 | 是 | 最近一次探活/校验通过的时间（由探活任务写回，不由人填） |
| `health` | enum | 是 | `active` / `stale` / `dead`，见 §6 |
| `contributor` | string | 否 | 提交者标识（账号名或 `system`），不记邮箱等个人信息 |
| `silent_args` | string | 否 | 沿用现有字段，**仅作记录**，本工具不执行安装 |

`entry_id` 不能等于 `display_name` 的理由：① 显示名会变（`QQ` → `QQ NT`、`抖音` → `抖音 8.8.0`）；② 55 条清单里已存在 `比心 版本 8.0.0.0` 这类带版本号的名字；③ 显示名不唯一（同名 x86/x64 两条）；④ 改名会连带打断用户本地已有的收藏与上报记录。

```json
{
  "catalog_version": 2,
  "updated_at": "2026-11-15T22:30:00+08:00",
  "etag": "sha256:9f2c1d7a4b8e0c3f5a6d7e8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d",
  "entries": [
    {
      "entry_id": "cat-cn-weixin-universal",
      "display_name": "微信",
      "match_keys": ["微信", "Weixin", "WeChat", "WeChatSetup", "微信 (Universal)"],
      "publisher": "腾讯科技(深圳)有限公司",
      "install_scope": "any",
      "channel": "winget",
      "winget_id": "Tencent.WeChat.Universal",
      "msstore_id": "",
      "url": "",
      "file_name": "",
      "sha256": "",
      "size": 0,
      "version": "",
      "arch": "x64",
      "lang": "zh-CN",
      "source_type": "winget",
      "verified_at": "2026-11-15T22:20:00+08:00",
      "health": "active",
      "contributor": "system",
      "silent_args": "/S"
    },
    {
      "entry_id": "cat-cn-weixin-direct-fallback",
      "display_name": "微信（直链兜底）",
      "match_keys": ["微信", "Weixin"],
      "publisher": "腾讯科技(深圳)有限公司",
      "install_scope": "any",
      "channel": "direct",
      "url": "https://dldir1v6.qq.com/weixin/Universal/Windows/WeChatWin_4.2.0.exe",
      "file_name": "WeChatWin_4.2.0.exe",
      "sha256": "67a53601ae597f0dff821155706e31dbfef36ee972caadb868097eb4d972c11a",
      "size": 0,
      "version": "4.2.0.52",
      "arch": "x64",
      "lang": "zh-CN",
      "source_type": "vendor",
      "verified_at": "2026-11-15T22:20:00+08:00",
      "health": "active",
      "contributor": "maintainer",
      "silent_args": "/S"
    },
    {
      "entry_id": "cat-microsoft-office-2019-proplus",
      "display_name": "Microsoft Office 专业增强版 2019 - zh-cn",
      "match_keys": ["Microsoft Office 专业增强版 2019 - zh-cn", "Office 2019 Professional Plus", "ProPlus2019Retail"],
      "publisher": "Microsoft Corporation",
      "install_scope": "machine",
      "channel": "direct",
      "url": "https://example.com/placeholder/office2019.img",
      "file_name": "office2019.img",
      "sha256": "",
      "size": 0,
      "version": "16.0.19127.20936",
      "arch": "x86",
      "lang": "zh-CN",
      "source_type": "manual",
      "verified_at": "2026-11-15T22:20:00+08:00",
      "health": "stale",
      "contributor": "maintainer",
      "silent_args": "/configure config.xml"
    }
  ]
}
```

> 示例中的 `example.com/placeholder` 是占位符（沿用现有 `catalog.example.json` 约定），不得入库；微信两条的 URL 与 SHA256 取自 `winget show --id Tencent.WeChat.Universal` 的真实输出。

## 3. 单一事实来源与优先级

一条 `entry_id` 只允许**一个有效 `channel`**，避免「URL 改了 winget_id 没改」的不一致。
| 优先级 | `channel` | 触发条件 | 说明 |
|---|---|---|---|
| P1 | `direct` | 有条目且 `url` 非空、`health != dead` | 最可控：可带 `sha256` 与 `size`，不依赖 winget 源 |
| P2 | `winget` | 条目有 `winget_id`，或**清单记录自带精确 ID**（来自 `winget export`） | **`winget export` 拿到的精确 ID 优先级高于任何名称匹配**，见下 |
| P3 | `msstore` | 条目有 `msstore_id` | 默认不启用（README：`winget download` 拉 msstore 需授权，实测易失败），需要显式开关 |
| P4 | 名称匹配 winget | 以上都没有，且 `--name-match` 开启 | 命中率仅 25%（14/55），只做兜底 |

**硬规则：ID 一旦有精确来源，禁止再用名称搜索覆盖它。** 实测反例：`winget show --name "向日葵远程控制"` 的 BestMatch 是 Store 应用 `XPDDRBQ2D1N7NJ`（`winget search` 的 Source 列为 `msstore`），而导出链路里该软件无精确 ID；若按名字自动绑 Store ID，就会把一个 exe 装机的 ARP 软件错绑到商店应用上。同理 `游戏加加` 的 export ID 是 `GamePP.GamePP`，而名称搜索结果里还混着 `GamePP.exe`、`GamePPLite.exe` 等碎片 token，纯名称匹配必错。

## 4. 条目来源与采集策略

| 来源 | 能覆盖什么 | 实测/可行性 | 可信度 | 更新方式 |
|---|---|---|---|---|
| `winget export --include-versions` | 精确 `PackageIdentifier`：**52 条**；同时报 `not available from any source` **8 条** | **已实测**：`winget export --include-versions -o x.json` 产出 `{"Sources":[{"Packages":[{"PackageIdentifier":…,"Version":…}]}]}`，`Packages` 共 52 条；另 8 条只在 stderr 报错（见下） | 最高（官方映射，零猜测） | 客户端每次 `scan` 现算；服务端只存增量 |
| `winget list` | 已安装全量：**155 行原始输出 / 153 行数据**（表头前有一个空行）；**142 个不同 Id**；按行首前缀分 `MSIX\` **72 行**、`ARP\` **18 行**、裸 `Publisher.Product` **63 行**（63 与「Source 列 = winget 的行数」不是同一口径，不要混用） | **已实测**：五列 `Name/Id/Version/Available/Source`，Source 列为空的行约 90 条，多为 MSIX/Store | 高（同一台机器的事实数据） | 客户端每次 `scan` 现算 |
| `winget show --id <id> --exact` | `Publisher`、`Installer Type`、`Installer Url`、`Installer SHA256`、`Release Date`、`Offline Distribution Supported` | **已实测可行**：`Microsoft.VisualStudioCode` 返回 `Installer SHA256: da5aad5f…`、`Offline Distribution Supported: true`；**但** `Installer:` 块是**变长**的——`Tencent.WeChat.Universal` 一行只有 `Installer Type / Installer Url / Installer SHA256 / Release Date / Offline Distribution Supported`，**没有** `Installer Locale` / `Architecture` / `Scope` 行。解析器只能「按 key 取值」，不能按固定行数 | 高（可直接落成 `url` + `sha256`） | 服务端半自动批量刷新 |
| 人工维护直链 | winget 收录不了或收录名不一致的：Office 2019 批量授权、`.img`/`.iso` 介质、企业内网包 | 本机 55 条中 `Microsoft Office 专业增强版 2019 - zh-cn` 无任何 winget ID | 中（靠人复核 + 探活） | 人工提交 → §8 审核 |
| 官方 API / 版本清单页 | 微信 `dldir1v6.qq.com`、NVIDIA 驱动查询、Office C2R 清单 | 每家格式不同，无统一协议 | 中 | **半自动**：人工确认域名与 URL 模板，脚本只做 `HEAD` + 版本提取 |
| winget-pkgs 源（YAML manifest） | 候选 URL 与 SHA256 的**最大**来源 | notebook 上 **github.com 不可达（000）** | 中 | **不得在线拉 GitHub raw**：改为离线导入（维护者本机下载 manifest 包 → `push` 上传 → 服务端合并），或经 cloud1:8084 自身中转缓存 |

**不能依赖 GitHub raw 的原因（实测）**：notebook `192.168.1.24` 上 `github.com` / `cdn.jsdelivr.net` 均返回 000。因此：
- 目录数据**只从本地文件/本服务读取**，任何「在线 fetch winget-pkgs」都写在客户端一侧（客户端通常能上网）；
- 服务端如需 manifest 数据，走 **离线导入**：`software-reback catalog import --file manifests.zip --push`；
- 不允许在服务端代码里出现 `raw.githubusercontent.com` 常量。

**winget export 的 8 个报错项（实测，stderr 输出 `Installed package is not available from any source: <X>`）**：`Notepad++`、`Weixin`、`ThunderShell`、`QQExtension`、`Codex Primary Runtime`、`PDFToolExtension`、`WorkBuddy`、`Local AI Manager for Microsoft 365`。

**口径必须写清楚（易错点）**：这 8 个是 `winget export` **内部**在解析已安装包时的 map 失败，**不是**「注册表 55 减 8」。
- 同一台机器上 `winget list` 的行名与这 8 个 `X` 同名；
- 但 `Notepad++.Notepad++`、`Tencent.WeChat.Universal`、`Tencent.WorkBuddy.Global` 这三条仍出现在 52 条导出结果里（实测）；
- 因此导出数与报错数**不能相减**，指标口径一律用「注册表条数 55 → 关联到精确 ID 的条数」（实测基线 50/55，见 06 §1）。

## 5. 合并与冲突解决

**合并键**（同一 `entry_id` 的多条记录视为同一软件的不同版本/架构）：

1. `entry_id` 相同 → 合并；
2. `match_keys` 归一化后与已有条目**完全重合** → 视为同一条目（可能是重复提交）；
3. 只部分重合（如 `微信` vs `微信（直链兜底）`）→ **不合并**，作为同一 `match_keys` 的多候选，由 §3 优先级择一。

| 冲突场景 | 谁覆盖谁 | 结果 |
|---|---|---|
| 同一 `entry_id` 出现两个不同 `sha256` | **新条目 reject**，旧条目保留并标记 `stale` | 防投毒；同时报冲突事件 |
| 同一 `entry_id` 的 `url` 与 `sha256` 同时变（正常发版） | 版本号更大者胜；版本相同时 `verified_at` 更新者胜 | 需要人工确认版本号 |
| `direct` 与 `winget` 同时存在 | `direct` 优先（P1），但若 `direct.health=dead` 则回落 P2 | 探活驱动 |
| 多架构（x64/x86/arm64） | **不合并**，各自独立 `entry_id` 后缀（`-x64` / `-x86` / `-arm64`），下载时按快照 `arch` 选 | 否则会下错架构 |
| 多语言（zh-CN/en-US） | 同架构规则，后缀 `-zhcn` / `-enus`；`any` 优先于具体语言 | 语言缺省回落 `any` |
| 多版本（同一软件两个 major） | 保留最新 `version` 为 `active`，旧版置 `stale` 但**不删**（重装可能要装回旧版） | 删除只由维护者显式执行 |
| 同名不同 `publisher` | 不合并，用 `publisher` 消歧；注册表侧无 Publisher 时不选 | 宁漏不误 |

## 6. 健康度与失效检测

**判定**（四种探针，任一命中即调整 `health`）：

| 探针 | 判定 | 频率（预估） | 发起方 |
|---|---|---|---|
| `HEAD`（失败回退 `GET` + `Range: bytes=0-0`） | 404/410 → `dead`；5xx 连续 3 次 → 疑死；2xx 且 `Content-Length` 与 `size` 不符 → `stale` | 每 7 天（新条目入库后 7 天内每日） | **优先 notebook**；国内下载站常从机房被拦，见下 |
| `sha256` 变化 | 同 `entry_id`、同 `version` 但 hash 变了 → `stale` + 安全告警；版本号也变了 → 正常发版 | 每次探活 | 同上 |
| DNS/证书 | 域名解析失败或证书过期 → `dead` | 每 7 天 | 同上 |
| 客户端回流 | 用户机器上真的下载过且 SHA256 通过 → `active`，刷新 `verified_at` | 每次 `download` | **客户端（关键）** |

**「客户端探活回流」设计**（解决 notebook 出网受限）：
- 客户端在**实际下载成功**后，把 `(entry_id, 实际 sha256, http_status, final_url, 耗时)` 作为 probe 事件随 `push` 上报（或走独立的 `probe-report` 子命令）；
- 服务端只做聚合：同一 `entry_id` 在 24h 内被 ≥2 个不同 `device_id` 成功下载且 SHA256 落地一致 → 强制 `active`，刷新 `verified_at`；
- `dead` 的撤销**只能由人工**触发（避免单机网络问题误杀条目）；
- 回流数据**不含**下载目录、IP、机器名（只含 `device_id` 用于去重，符合 `04-isolation.md` 与 `03-api-contract.md` 的隐私边界）；
- 回流同时是**目录命中率**的数据源：客户端上报的 `skipped` 原因码可统计「哪一类软件最缺条目」。

```text
                            客户端下载 + SHA256 校验通过（回流）
                            ┌────────────────────────────────┐
                            │                                ▼
   [ 待审 pending ] ─审核通过─► [ active ] ─探活 4xx/5xx 连续 3 次─► [ dead ]
                                │    ▲                              │
                    同 version  │    │ 维护者确认新版本号并回填       │ 人工复核并修复 url
                    SHA256 变化 │    │ 新 hash（记录 last_change）    │
                                ▼    │                              ▼
                              [ stale ] ◄──补丁版本号更新（维护者确认）── [ stale ]

   dead / stale 都保留条目：下载计划按 §3 回落下一优先级；
   dead 持续 90 天未修复 → 归档（不删除，人工可复活）
```

| 状态 | 下载时行为 | 报告 detail |
|---|---|---|
| `active` | 正常使用 | — |
| `stale` | 仍使用，但报告 `status=ok` 且 `detail` 附「目录条目可能过期」 | `catalog_stale` |
| `dead` | 跳过该 channel，走下一优先级；全部 dead 则 `skipped` | `catalog_dead` |

## 7. SHA256 维护

| 问题 | 结论 |
|---|---|
| 谁来算 | ① `winget show` 回填（安装方发布的 hash）；② 贡献者本机 `Get-FileHash` 后提交；③ 服务端导入时对**已上传小样本**计算——**不对安装包本体计算**（服务端不托管、不下载大文件） |
| 何时算 | 条目首次入库时必算；`url` 变化时必须重算；`health` 从 `dead` 恢复时必须重算 |
| `sha256` 为空允许下载吗 | **允许（沿用现状）**，现有 `downloader.py` 的逻辑是 `if sha256 and actual != sha256` 才判失败，空值等于跳过校验 |
| 空的代价 | ① 无法发现供应链替换（同一 URL 换包）；② 无法做「按 hash 缓存复用」（06 §3.5）；③ 无法做客户端回流探活校验；④ 下载中断后无法判断 `.part` 是否同一份包 |
| 改进（v2 分级） | `strict`（默认）：空 SHA256 → 仍然下载，但报告 `detail=no_sha256` 并计入「无校验条目数」指标；`--require-sha256`：空值直接 `skipped`。**不默认开启 strict-fail**，否则 55 条里大量条目会从「能下」变成「不能下」 |
| 无 hash 时如何降低风险 | 至少校验 `size`（Content-Length 一致性）+ 记录最终 `final_url` 域名是否在条目 `url` 域名白名单内 |

## 8. 贡献与审核流程

```text
1. 用户在客户端看到 skipped / failed 条目
2. software-reback catalog add --entry <file.json>   （本地生成条目草稿，自动填本机 base info）
3. software-reback catalog check --entry <file.json> （离线自检：schema、URL 可达、SHA256 与本地文件一致）
4. software-reback catalog push --entry <file.json>  （上报云端，Bearer token 绑定 account_id+device_id）
5. 服务端自动校验（下表）→ 通过则进入 pending 队列；不通过直接 409 并返回逐项原因
6. 人工审核（维护者）：看域名、看来源类型、比对官方页面；通过 → 入库，degraded 项目记录豁免原因
7. 入库后 7 天内每日探活；两条通过则 health=active
```

| 自动校验项 | 规则 | 失败处理 |
|---|---|---|
| JSON schema | 必填字段齐全、类型正确、`entry_id` 唯一 | 硬拒 |
| URL scheme | 必须 `https://`；禁止 `http://`（除非维护者白名单） | 硬拒 |
| 内网地址 | 拒绝 `10./172.16-31./192.168./127./169.254./::1/link-local`、非标准端口 | 硬拒（防 SSRF） |
| 域名黑名单 | 网盘分享域、破解站、聚合下载器 | 硬拒 |
| 域名白名单 | 官方/Vendor 首选；未知域名 → `degraded` 转人工 | 转人工 |
| URL 可达性 | `HEAD` 200/206；超时 10s | 硬拒 |
| SHA256 与文件一致 | 若同时给了 `url` 与本地文件路径，服务端比对客户端上报的 hash（不下载） | 硬拒 |
| `file_name` 安全性 | 过 `downloader.safe_file_name`：不含 `<>:"/\` 竖线 `?*` 等非法字符，且不是 `CON/PRN/AUX/NUL/COM1-9/LPT1-9` | 硬拒 |
| `size` 一致性 | 非 0 时必须与 `Content-Length` 相等 | `degraded` |
| 重复检测 | `match_keys` 归一化后与现有条目重合 | 返回「可能重复」+ 已有 `entry_id` |
| 频率限制 | 单 `account_id` 每小时 ≤20 条提交 | 429 |

## 9. 目录版本与分发

| 项 | 设计 |
|---|---|
| 版本号 | 单调递增整数 `catalog_version`（当前 2）+ 内容哈希 `etag`（条目规范化 JSON 的 SHA256） |
| 条目级版本 | 每条 `entry_id` 带 `rev` 整数，供增量同步 |
| 拉取 | `GET /catalog?since_rev=123` 返回 `rev>123` 的条目 + 删除墓碑（`tombstone: true`） |
| 变更检测 | 客户端请求带 `If-None-Match: <etag>`；服务端 304 时零传输 |
| 全量兜底 | `GET /catalog?full=1`，客户端本地 ETag 不匹配且增量链断裂时使用；并回写本地 `catalog_cache.json` |
| 离线场景 | 客户端内置一份 `catalog.bundled.json`（打包在 wheel 内，随版本发布），无网时直接用它；本地缓存优先于 bundled，bundled 优先于「没有目录」 |
| 冲突 | 本地用户手改的条目放 `catalog.local.json`（**优先级最高**），不与远端合并、也不上推，除非 `catalog push` |
| 大小预算 | 全量目录控制在 5 MB 内（预估：单条 ~1 KB × 数千条），便于整包缓存 |

## 10. 运营指标

| 指标 | 公式 | 基线 / 目标 |
|---|---|---|
| 目录命中率 | `未进 skipped 的软件数 / 清单总数` | 现状 14/55 = **25.5%**（纯名称匹配）；目标 ≥50/55 = **90.9%**（= 注册表与 `winget list` 精确名关联率） |
| 条目健康率 | `health=active 的条目数 / (active+stale+dead)` | 目标 ≥90%（预估） |
| 失效平均修复时长（MTTR） | `Σ(修复时间 − 首次判 dead 时间) / 已修复条数`，只统计 dead 且已复活条目 | 目标 ≤7 天（预估） |
| 贡献通过率 | `审核通过条目数 / 提交条目数` | 目标 ≥60%（预估）；低于 30% 说明 `catalog check` 规则太松 |
| 无校验率（新增） | `sha256 为空的 active 条目 / active 条目` | 监控项，目标逐版本下降 |
| 单机可复现 | 本机样本上 `scan --enrich` 后 `package_id` 非空的记录数 | **必须 ≥50/55**（回归门槛） |

## 11. 不做什么

- **不托管安装包**：目录与服务端都不存二进制，不做镜像、不做 CDN 回源缓存安装包（只缓存**元数据**）。
- **不自动执行安装**：`silent_args` 只是记录，本工具从不调用安装器（README「未实现的部分」保持不变）。
- **不抓取破解站 / 网盘分享 / 聚合下载器**：`source_type=manual` 也必须指向官方或厂商自有域名。
- **不绕过需要登录的下载站**：需要账号、验证码、企业授权（如 Office 批量授权）的，只记录「需人工获取」。
- **不在服务端在线拉 GitHub raw / jsDelivr**：notebook 实测不可达（000）。
- **不把显示名当主键**，不做「模糊匹配自动入库」（只能人工审核后入库）。
- **不做跨账号共享上报数据**：目录是公共数据，但谁提交、谁审核要留痕（`contributor` 字段）。
