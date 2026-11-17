# 06 · 客户端强化设计（M1 读取 + M2 下载）

> 前置：`README.md`（现有实现）+ `PLAN-SPLIT.md`（**已归档**，仅引用其实测事实数据）。
> 硬约束：**不重写**，在现有 `cli.py / inventory.py / winget.py / resolver.py / downloader.py / store.py / catalog.py` 上做增量扩展；64 个既有测试必须继续通过。
> 本文所有数字均来自本机实测（winget **v1.29.380**，可执行文件在 `%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe`，**不在 PATH 里，必须用全路径调用**）。

## 1. 现状与差距

| 能力 | 现有实现 | 实测数字 | 差距 | 本设计怎么补 |
|---|---|---|---|---|
| 注册表读取 | `inventory.collect()` 三源（HKLM / WOW6432Node / HKCU），过滤 `SystemComponent` / `ParentKeyName`，同名同版本合并 | 清单 `software.json` **55 条** | 无环境快照，无法区分机器级/用户级 | §2.6 环境快照 + `install_scope` 字段 |
| winget 识别 | `scan --enrich` → `winget.resolve_package_id()`，每个软件一次 `winget search --name`，两轮（精确 + 归一化），候选不唯一就放弃 | 覆盖率 **14/55 ≈ 25%**，41 条进 `skipped` | 纯名称搜索，而答案本来就在机器上 | §2.3 **先用 `winget export` 的精确 ID**，名称搜索降为最后一档 |
| 精确 ID | 未使用 | `winget export --include-versions` → **52 个 PackageIdentifier** | 完全没用上 | 作为主链路 |
| 已安装全量 | 未使用 | `winget list` → 表头 + 分隔行 + **153 行数据**，**142 个不同 Id**；Id 分三类：`MSIX\…`（72 行）、`ARP\…`（18 行）、裸 `Publisher.Product`（63 行），后两类合计 81 与「Source 非空 63 行」不是同一口径（逐个 Id 的前缀计数见 §2.4） | 完全没用上 | 用于补充 Publisher/Scope/Store 识别 |
| 注册表 ↔ winget 关联 | 无（只按名字搜） | 注册表 55 条按「精确名（忽略大小写+多余空白）」与 `winget list` 关联命中 **50 条 = 90.9%** | 缺实现 | §2.3 关联算法，目标 ≥50/55 |
| 下载 | `downloader.download_url()`：流式 + `.part` + SHA256 + 原子改名 | 中断即全量重下；无 Range、无并发、无缓存复用 | 大包体验差、重复下载 | §3 断点续传 / 并发 / 缓存 |

**目标（可复现门槛）**：同一台机器上 `scan --enrich` 后 `package_id` 非空的记录数 **≥50/55**（基线 50/55，即 90.9%），且**不得出现错绑**（宁可 50，不可 51 错）。`download --dry-run` 的可解析率随目录推进，阶段目标 ≥90%。

## 2. 功能 1：读取强化

### 2.1 多源读取

| 源 | 拿到什么 | 局限 | 可靠性 | 新增成本 |
|---|---|---|---|---|
| 注册表三源（现有） | `DisplayName / DisplayVersion / Publisher / InstallLocation` | 无包 ID；有 `Unknown` 版本；`PUBG: BATTLEGROUNDS` 版本为空 | 高 | 0（已实现） |
| `winget export --include-versions` | **52** 个精确 `PackageIdentifier` + `Version` | 8 条报 `not available from any source`；**出口 JSON 不带显示名**，必须靠 `list` 反查 | 最高 | 中 |
| `winget list` | 153 行：Name/Id/Version/Available/Source | 定宽表、CJK 宽度错位、单元格溢出（§2.4） | 高 | 中 |
| Store / MSIX 应用 | 72 行 Id 形如 `MSIX\<PkgFamilyName>_<Ver>_<Arch>__<PublisherHash>`，Source 列为空 | 不能 `winget download`（需授权）；重装应走 Store「我的应用」 | 中 | 低（同一次 `list` 解析） |
| 其他源（可选，P2） | `HKLM\…\App Paths`、`Uninstall` 的 `QuietUninstallString` | 噪声大 | 低 | 后置 |

### 2.2 权限与调用注意事项（实测）

- **PATH 里没有 winget**：`run_winget()` 现在写死 `["winget", *args]`，在 PATH 缺失的环境会直接 `FileNotFoundError`。需改为 `resolve_winget_path()`：先 `shutil.which("winget")`，再回落 `%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe`，最后回落 `%ProgramFiles%\WindowsApps\...`，全失败给出可读错误。
- 所有调用保持 `--accept-source-agreements --disable-interactivity`（现有实现已有），并统一 `encoding="utf-8", errors="replace"`。
- `winget export` 必须带 `-o <file>`：stdout 会与进度条混在一起，直接管道会解析失败。

### 2.3 匹配与融合流程（核心）

**为什么比纯名称搜索强**：名称搜索要「猜」`Notepad++ (64-bit x64)` 对应哪个包，而 `winget export` 是 winget 自己把「本机已安装的包」映射成精确 ID —— 答案零歧义。名称搜索只保留兜底，且仍守「宁漏不误」。

```text
step 0  采集
        R = 注册表 55 条（现有 inventory.collect）
        E = winget export 的 52 条 {PackageIdentifier, Version}
        L = winget list 的 153 行 {name, id, version, available, source}

step 1  ID 直连（最高优先，零歧义）
        E 里的每个 ID，按 id 精确匹配 L 的行 → 得到该 ID 对应的 list 名称与版本
        （实测：id 精确匹配即可，不需要模糊；**52 个 ID 全部能在 L 中找到对应行 = 52/52**）
        注意：这一步之所以「全部命中」，前提是 L 的 Id 列解析正确——
        若按码点直接定宽切片而不做 §2.4 的宽度修正，实测只有 **40/52**
        （豆包/抖音/剪映/微信/百度网盘/邮箱大师/PhysX/InstallationAssistant/WindowsTerminal/WSL 等 12 条会解析错）

step 2  名称锚定到 L
        for r in R:
            key = normalize_name(r.name)            # 压空白 + casefold，现有函数
            cand = [row for row in L if normalize_name(row.name) == key]
            if len(cand) == 1:  anchor[r] = cand[0];  continue
            if len(cand) > 1:   anchor[r] = 按 §2.3.2 消歧(cand, r); continue
            anchor[r] = None                        # 交给 step 4

step 3  由锚点升级为 ID
        row = anchor[r]
        if row.id 属于 step1 的 ID 集合:   r.package_id = row.id; r.source = "winget"
        elif row.id 形如 ARP\… 或 MSIX\…:  只回填 r.install_scope / r.installed_id，
                                          不产生 package_id（不可下载，进目录环节）
        else:                              不进 ID 集合也非 ARP/MSIX → 视为不可靠，丢弃锚点

step 4  唯一兜底：目录匹配（M4）
        entry = catalog.find_by_match_keys(r.name, publisher=r.publisher)
        命中且唯一 → r.package_id = entry.winget_id 或 entry.url

step 5  最后兜底：现有名称搜索
        仅当 --name-match 且 step3/4 都没结果时，才调用 resolve_package_id()

step 6  输出 schema v2（§2.5），未关联的进 skipped 并写原因码
```

#### 2.3.1 关联算法（注册表名 ↔ winget export Id）

`E` 只有 ID，没有显示名，所以「注册表 ↔ export」必须先各自对到 `L` 上，再在 `L` 上做交集。三条键依次使用：

| 轮次 | 键 | 说明 | 采用条件 |
|---|---|---|---|
| K1 | `normalize_name(注册表 name) == normalize_name(list name)` | 忽略大小写与连续空白的精确名 | 候选行数 = 1 |
| K2 | `Publisher` 归一化 + 名称前缀（`search_key` 剥 `(64-bit x64)` 与尾部版本号） | 处理 `Python 3.12.10 (64-bit)` 这类带噪声名 | 候选行数 = 1，且 publisher 归一化后相等 |
| K3 | `entry_id`（目录 match_keys） | 目录里的别名 | 命中条目唯一 |

#### 2.3.2 歧义处理规则（宁漏不误）

1. 同名多行 → 若只有一行的 Id 在 `E` 里，取它；否则**放弃**（`ambiguous_name`）。
2. 归一化后多行且 Id 都不同（如 `Visual Studio Code` 的 ARP 行与 `MSIX\Microsoft.VisualStudioCode_…` 行同时存在）→ 只有当其中恰好一行是 winget 源（裸 ID）时取该行，否则放弃。
3. 版本冲突（注册表 `8.9.8.1` vs list `Available=8.9.9.1`）**不阻断**，`Available` 仅记录，不参与选择。
4. 一条 export ID 不允许被两条注册表记录同时认领（一对多时按名最长匹配，仍不唯一则全部放弃）。
5. 任何一步拿不到唯一解 → 不产出 `package_id`，记原因码，绝不猜。

#### 2.3.3 实测未命中的 5 条（逐条分析）

| 注册表条目 | 为什么没命中 `winget list` | 补全方案 |
|---|---|---|
| `Google Chrome` | `winget list` 里确实有 `Google Chrome`（Source 为空），但**精确名相同却没能对到 export ID**：Chrome 走独立更新器，ARP 行不映射到 `Google.Chrome` 包，导出里也就没有它 | 走目录 `entry_id=cat-google-chrome`，`winget_id=Google.Chrome`（官方源有该包），或直链 `https://dl.google.com/…/ChromeStandaloneSetup64.exe` |
| `Microsoft Office 专业增强版 2019 - zh-cn` | 对应行是 `ARP\Machine\X64\ProPlus2019Retail - zh-cn`，批量授权（C2R Retail）无 winget 包，导出里没有 | 只能人工直链（`.img`）或 `office deployment tool` + `config.xml`；目录标 `source_type=manual` |
| `PUBG: BATTLEGROUNDS` | 行是 `ARP\Machine\X64\Steam App 578080`，版本为 `Unknown`，属于 Steam 子项，无独立 winget 包 | 归「平台托管」：记录 `Steam AppID=578080`，重装路径是装 Steam 后按 AppID 安装；不做直链（DRM） |
| `向日葵远程控制` | 行存在（`ARP\Machine\X86\Oray AweSun RemoteClient`），但无 winget 包 ID；`winget search --name 向日葵` 的 BestMatch 是 Store 应用 `XPDDRBQ2D1N7NJ`（Source=`msstore`，`winget show --id` 能解析但属于 Store），**不是同一个东西** | 不采用该 Store ID；改用官方直链，或标 `unresolved` 并提示用户从官网装 |
| `游戏加加` | 行存在，但 Name 单元格被塞进一整串互斥体/进程 token（`GamePlusPlusInterUninstallMutex GamePP.exe …`），精确名对不上 | 目录 `match_keys` 加 `游戏加加`、`GamePP`；`winget_id=GamePP.GamePP`（导出结果里确有该 ID），`silent_args` 记录即可 |

> 这 5 条体现「宁漏不误」：宁可留在 `skipped` 里等人补目录，也不把 `XPDDRBQ2D1N7NJ` 这种 Store 应用 ID 硬绑到 ARP 软件上。其中 `游戏加加` 有一个现成的精确 ID（来自 export），属于「本可以直接关联、只是 Name 被污染」的特例，因此值得优先修。

### 2.4 `winget list` 解析：定宽切列 + 溢出兜底

实测三种格式坑（根因不同，必须分别处理）：

1. **CJK 宽度错位（最重要）**：winget 按显示宽度排版（CJK=2 列），而 Python 按码点计长度。实测 `NVIDIA HD 音频驱动程序 1.4.6.3` 行的 `ARP\Machine\X64\…` 出现在码点 **129**（表头里 Id 起始于 135），差 6 = 该行 Name 里的 7 个 CJK 码点（各多占 1 列）减去行首的 1 列补齐。
2. **单元格溢出到下一列**：`Microsoft Teams` 行的 `Available` 溢出并带上了 Source，被 `\s{2,}` 切成 `… 1.0.0.1 | 26288.2004.5269.3420 winget`。该行长度 269 = 表头长度，**完全填满的行反而不分列**。
3. **列被挤压成单空格**：现有 `winget._split_row()` 已针对此做过兜底，思路要沿用。

**方案（四级，顺序固定）**：

```text
parse_list_v2(output, known_ids=E):
  lines = 规范化换行后按行切
  hdr   = 表头行（含 Name/Id/Version/Available/Source 五个列名）
  sep   = hdr 下一行，全 '-'；record_width = len(sep)（实测 269）
  cols  = [(idx(hdr, c), idx(hdr, 下一列名)) …]，最后一列右端 = record_width

  for line in 数据行（跳过空行、跳过重复表头）:
    level 1  定宽切片：name/id/version/available/source = line[p0:p1] …
    level 2  溢出行修正：
             若 row 的 id 单元格为空 且 line 有内容 → 视为上一行的续行（丢弃并计入 parse_errors）
             若 len(line) > record_width → 先按 record_width 截断
             （版本溢出已由定宽切片天然解决：available 就是 26288.2004.5269.3420，source 为 winget）
    level 2b 宽度错位修正（关键，不做它 52 个 export ID 只能对上 40 个）：
             n = name 切片里非 ASCII 码点数
             若 id 不以 MSIX\ / ARP\ 开头，且 id 不在已知集合 E 里：
                 id = line[id_start - n : ver_start - n] 再取一次（n>0 才做）
             仍不成立 → 用结构化锚点（level 3）
    level 3  结构化锚点兜底（沿用 _split_row 思路；**只能当兜底，不能当主路径**）：
             把 level 2b 修正后的 id 切片再切一次：
               - 取 id 切片的头部 token，若它含 '.' 或以 'MSIX\' / 'ARP\' 开头 → 用它升级锚点
               - 否则用正则 r'(MSIX|ARP)\\S+' 或「含点、长度≥6、其后紧跟 VERSIONISH 版本」的 token
             实测：纯 token 正则能还原 50/52 个 export ID
             （漏 Notepad++.Notepad++ 与 YY.YY：它们的前一列 Available 为空，token 后紧跟的不是版本号，
              这类只能靠 level 2b 的定宽修正还原）
    仍失败 → 丢弃该行并计入 parse_errors（不猜测）
  return rows, parse_errors
```

> 实测代价对比：同一份 153 行输出，`level 1+2` 直接切出 142 个 Id，但 52 个 export ID 只有 **40 个**能对上；剩下 12 个全是被 CJK 宽度错位截断的（`Nvidia.PhysX`、`ByteDance.Doubao`、`ByteDance.Douyin`、`ByteDance.DoubaoInputMethod`、`ByteDance.JianyingPro`、`Tencent.WeChat.Universal`、`Baidu.BaiduNetdisk`、`NetEase.MailMaster`、`GamePP.GamePP`、`Microsoft.WindowsInstallationAssistant`、`Microsoft.WindowsTerminal`、`Microsoft.WSL`）。加上 `level 2b` 后 **52/52**。

**单测如何覆盖**（离线 fixture，不调 winget）：

| 用例 | fixture 形态 | 断言 |
|---|---|---|
| CJK 宽度错位 | 一行 `NVIDIA HD 音频驱动程序 1.4.6.3 …` + 一行纯 ASCII（同为 `ARP\Machine\X64\…`） | 两行的 `id` 都等于 `ARP\Machine\X64\{B2FE1952-0186-46C3-BAEC-A80AA35AC5B8}_HDAudio.Driver` |
| 版本溢出 | 复制 `Microsoft Teams` 原始行（`1.0.0.1` 后紧跟 `26288.2004.5269.3420 winget`） | `version == "1.0.0.1"`、`available == "26288.2004.5269.3420"`、`source == "winget"` |
| 列压成单空格 | 现有 `_split_row` 的测试样例行 | 回归通过，行为不变 |
| 空 Source | 一行以 `MSIX\Microsoft.AV1VideoExtension_2.0.35.0_x64__8wekyb3d8bbwe` 结尾 | `source == ""` 且 `id` 不被截断 |
| CJK + Source 为空（双重坑） | `豆包`（`ByteDance.Doubao`，Source=`winget`）与 `百度网盘`（`MSIX\…`，Source 空）原行 | 前者 id/channel 正确，后者 id 不被截断 |
| 全量回归 | 保存本机真实输出为 `tests/fixtures/winget-list-1.29.380.txt` | **原始 155 行 / 数据 153 行**、142 个 Id、对 52 个 export ID 命中 **52/52** |

#### 2.4.1 解析失败必须可观测（K1 指标的前提）

**这是本节最重要的约束**：K1「覆盖率 ≥90%」完全建立在 `winget list` 解析正确之上，而 `winget list` 是非结构化、无版本契约的定宽文本。若解析失败静默发生，覆盖率会悄悄掉到 40/52 甚至更低，而报告仍显示「成功」。

因此 `parse_list_v2` **必须返回 `(rows, parse_errors)` 二元组，且 `parse_errors` 必须向上传播到清单与报告**：

| 要求 | 具体做法 | 违反后果 |
|---|---|---|
| 错误计数必须外露 | `parse_list_v2` 返回 `parse_errors`（行号 + 原因码）；写入清单 `source_summary.parse_errors` 与 `stats.parse_errors` | 解析失败被当成「本机没有这个软件」，K1 失真且无人察觉 |
| 失败不得静默降级 | 解析出错的行**丢弃并计数**，绝不猜测填充；`parse_errors > 0` 时 `scan` 输出告警并在报告里单列 | 错误数据进入清单，下游下载到错包 |
| 覆盖率必须带分母 | 报告输出 `identified / total` 与 `parse_errors`，二者同时展示；K1 达标判定需 `parse_errors == 0` | 用「解析失败」冒充「软件未安装」，指标虚高 |
| 解析器版本必须留痕 | 清单 `client.winget_version` + `client.parser_version` 双记录 | winget 升级导致格式漂移时无法定位是哪一版出的问题 |

> 判定口径：**K1 ≥90% 且 `parse_errors == 0` 才算达标**。若 `parse_errors > 0`，即使覆盖率显示 90%，也视为未达标——因为分母本身不可信。这条是对原设计「只统计 `winget_id` 非空条数」的修正：原口径无法区分「真的没装」与「解析失败没认出来」。


### 2.5 输出清单 schema v2

`schema_version: 2`，**v1 字段全部保留**（`name/version/publisher/install_location/source/package_id`），只做加法；`load_inventory` 读 v1 时必须正常（`SoftwareRecord.from_dict` 已按字段白名单过滤）。

```json
{
  "schema_version": 2,
  "generated_at": "2026-11-15T22:35:00+08:00",
  "client": { "tool_version": "0.2.0", "winget_version": "v1.29.380", "parser_version": "list-v2.1" },
  "environment": {
    "os": "Windows 11 Pro 10.0.26100",
    "arch": "x64",
    "process_arch": "x64",
    "is_wow64": false,
    "timezone": "Asia/Shanghai",
    "locale": "zh-CN",
    "elevated": false
  },
  "stats": { "total": 55, "identified": 50, "by_source": { "winget": 50, "registry": 5 }, "parse_errors": 0 },
  "software": [
    {
      "name": "Notepad++ (64-bit x64)",
      "version": "8.9.8.1",
      "publisher": "Notepad++ Team",
      "install_location": "C:\\Program Files\\Notepad++\\",
      "source": "winget",
      "package_id": "Notepad++.Notepad++",
      "install_scope": "machine",
      "installed_id_kind": "arp",
      "arch": "x64",
      "match_rule": "k1_exact_name",
      "entry_id": "cat-notepad-plus-plus",
      "catalog_channel": "winget"
    },
    {
      "name": "PUBG: BATTLEGROUNDS",
      "version": "",
      "publisher": "PUBG Corporation",
      "install_location": "C:\\Program Files (x86)\\Steam\\steamapps\\common\\PUBG",
      "source": "registry",
      "package_id": "",
      "install_scope": "machine",
      "installed_id_kind": "arp",
      "arch": "",
      "match_rule": "none",
      "entry_id": "",
      "catalog_channel": "",
      "skip_reason": "no_package_id_platform_managed"
    }
  ]
}
```

新增字段：`install_scope`（`machine`/`user`/`""`）、`installed_id_kind`（`arp`/`msix`/`winget`/`""`）、`arch`、`match_rule`（`k1_exact_name`/`k2_publisher_prefix`/`k3_catalog`/`name_search`/`none`）、`entry_id`、`catalog_channel`、`skip_reason`。`match_rule` 是为了让「为什么没绑上」可解释，也是回归门槛的度量口径。

### 2.6 环境快照（`environment` 块）

| 字段 | 取值方式 | 用途 |
|---|---|---|
| `os` | `platform.platform()` / `sys.getwindowsversion()` | 判断 Win10/Win11、build |
| `arch` | `platform.machine()` | 选目录条目的 `arch` |
| `process_arch` / `is_wow64` | `platform.architecture()` + `PROCESSOR_ARCHITEW6432` 环境变量 | 32 位 Python 读不到 64 位注册表键，必须标记，否则清单会**静默少条目** |
| `timezone` / `locale` | `datetime.now().astimezone().tzinfo` / `locale.getpreferredencoding()` | 报告时间可比、编码问题定位 |
| `elevated` | `ctypes.windll.shell32.IsUserAnAdmin()` | 非管理员时 HKLM 只读可见性提示 |

**用户级/机器级区分**：注册表源本身已区分（HKLM = machine、HKCU = user），写入 `install_scope`；`winget list` 的 `ARP\Machine\…` / `ARP\User\…` 前缀提供交叉验证。

## 3. 功能 2：下载强化

### 3.1 下载决策优先级（在现有 4 级上扩展）

| 级 | 来源 | 现有 | 说明 |
|---|---|---|---|
| 1 | 目录直链 `direct` | 有（`resolver.plan_for` 第 1 档，`entry.url` 非空） | 可带 `sha256` + `size` |
| 2 | 目录 `winget_id` | 有（第 2 档） | 来自目录，人工/导出确认过 |
| 3 | **清单记录自带的精确 `package_id`** | 有（第 3 档，`record.package_id`） | **v2 起它是 `winget export` 的产物，优先级实质提升**：纯名称搜索结果不再写回记录，只作为第 5 档 |
| 4 | **目录 `msstore_id`（新增）** | 无 | 需显式 `--allow-store`；默认跳过（README 已说明理由） |
| 5 | 名称搜索 winget（兜底） | 有（第 4 档，`matcher`） | `--no-name-match` 可关；覆盖率约 25% |
| 6 | 无法解析 | 有（`unresolved`） | 原因码见 §5 |

每条计划额外输出 `decided_by`（`catalog_direct`/`catalog_winget`/`record_package_id`/`catalog_msstore`/`name_match`/`none`），方便统计各级贡献。

### 3.2 断点续传（HTTP Range + ETag/If-Range）

现有实现：`.part` 每次从 0 开始重写，中断即丢弃全部字节。改造：

```text
download_url_v2(url, dest_dir, file_name, sha256, size, timeout, ca, resume=True):
    target = dest / safe_file_name(file_name)
    part   = dest / (target.name + ".part")
    meta   = dest / (target.name + ".part.json")   # {url, etag, last_modified, total}
    if target.exists() and sha256 and sha256_of_file(target) == sha256:  return target  # 缓存命中
    offset = part.stat().st_size if (resume and part.exists() and meta.url == url) else 0
    headers = {"User-Agent": "software-reback/0.2", "Range": f"bytes={offset}-"} if offset else {}
    if offset and meta.etag: headers["If-Range"] = meta.etag
    resp = urlopen(GET)
    if 206 and Content-Range 起点 == offset:  open(part, "ab")   # 续传
    elif 200:                                 open(part, "wb"); offset = 0   # 服务器不支持 Range，重头下并覆盖
    elif 416:                                 part 截断重下（offset 已越界）
    total = 解析 Content-Range 的 total 或 Content-Length + offset
    下载完成后：written = part.stat().st_size
    if total 已知且 written != total: raise Incomplete  # 不删 .part，可续
    if size 且 written != size:       raise SizeMismatch
    if sha256 且 sha256_of_file(part) != sha256: part.unlink(); raise HashMismatch
    os.replace(part, target); meta.unlink()
```

要点：
- 续传元数据独立成 `.part.json`，避免污染包本体；
- 服务器返回 `200`（不支持 Range）时**必须重头下**，不能追加，否则文件永久损坏；
- 只有**校验通过**才 `os.replace` 原子改名（现有行为保留）；
- `HashMismatch` 时删 `.part` 与 `.part.json`（内容不对的续传没有意义）；`Incomplete` 时**保留**。

### 3.3 并发、限速、重试与退避

| 参数 | 默认 | 范围 | 说明 |
|---|---|---|---|
| `--concurrency` | 2 | 1–4 | 同域名并发上限 1（多数厂商站点对同 IP 并发敏感） |
| `--timeout` | 60 s（连接 15 s / 读取 60 s） | 10–600 | 现有参数是单一 `timeout`，拆成 connect/read |
| `--rate-limit` | 0（不限） | KB/s | 限速仅作用于 `direct` 通道，`winget` 通道交给 winget 自己 |
| `--retries` | 3 | 0–5 | 仅对可重试错误 |
| 退避 | 指数 + 抖动 | — | `sleep = min(30, 2**attempt) * (0.5 + random())`，即 ~1/2/4 s 带上浮 |
| 可重试 | 超时、连接重置、5xx、429（尊重 `Retry-After`） | — | — |
| 不重试 | 404/410、`HashMismatch`、`SizeMismatch`、证书错误 | — | 直接进失败分类 |

失败隔离：单个软件失败不中断整批（现有 `cli.run_download` 已如此），并发下按 `outcomes` 收集，报告保持清单顺序输出以保证可复现。

### 3.4 校验

| 校验项 | 现有 | v2 | 失败 |
|---|---|---|---|
| SHA256 | 非空即强校验 | 保留；新增 `--require-sha256` 让空值变 `skipped` | `HashMismatch` |
| 大小 | 无 | `size` 非空时与落盘字节数严格相等 | `SizeMismatch` |
| Content-Length 一致性 | 只用于进度条 | 与实际接收字节比对，不一致 → `Incomplete`（可续传重试） | `Incomplete` |
| 域名 | 无 | 落盘前比对 `final_url` 域名是否在条目允许域名内，越界记 `detail=domain_drift`（不失败，但上报） | 告警 |
| winget 通道 | 只信 exit code | 保持；额外记录 `Available` 与落盘文件（无法逐个校验 hash，明示 `verified=false`） | — |

### 3.5 缓存复用（按 SHA256 命名）

设计：`downloads/.cache/<sha256 前 2 位>/<sha256><ext>`，命中后 `os.link`/`shutil.copy2` 到目标名。

**为什么按 hash 而不是按文件名**：
1. 同一安装包在不同软件名下重复出现（如 VC++ 运行库被多个程序捆绑）时，按名字会重复下载，按 hash 天然去重；
2. **同时解决隔离防串包**：文件名是不可信输入（URL 最后一段、目录 `file_name`），`A/Setup.exe` 与 `B/Setup.exe` 可能内容不同。按 hash 落缓存 + 校验后落目标名，等于「先证明内容，再决定名字」，不会出现「上一批的 Setup.exe 被当成这一批的」；
3. 续传判定、回流探活、`verified_at` 都直接引用同一个 hash，口径统一。

约束：缓存目录与 `downloads/` 同级但仍由 `--dest` 决定；`--no-cache` 关闭；缓存项不被 `--clean` 之外的逻辑删除。

### 3.6 报告格式扩展（CSV，UTF-8 BOM）

现有字段 `name/version/method/status/target/detail` **保持原顺序不变**（老脚本按列号读不会坏），新字段追加在后：

| 新增字段 | 说明 |
|---|---|
| `entry_id` | 目录条目主键（无则空） |
| `decided_by` | §3.1 的决策级 |
| `package_id` | 实际使用的包 ID |
| `url_final` | 重定向后的真实 URL |
| `http_status` | 最后一次响应码 |
| `bytes` | 落盘字节数 |
| `sha256_expected` / `sha256_actual` | 便于事后比对 |
| `verified` | `true` 仅当 SHA256 校验通过 |
| `attempts` | 重试次数 |
| `error_code` | §5 的分类码 |
| `elapsed_ms` | 耗时 |

## 4. CLI 命令设计

**兼容性铁律**：现有 `scan`（`-o/--output`、`--enrich`）与 `download`（`-i/-d/--catalog/--no-name-match/--dry-run/--report/--ca-bundle`）**参数名与默认值一律不变**；新增能力要么是新开关（默认关闭的旧行为），要么是新子命令。

### 4.1 `scan`

| 参数 | 默认 | 说明 |
|---|---|---|
| `-o/--output` | `software.json` | 不变 |
| `--enrich` | off | 不变，但内部改为「export 优先」流水线（§2.3） |
| `--no-export`（新） | false | 跳过 `winget export`，退回旧行为（用于 winget 不可用的机器） |
| `--include-store`（新） | false | 把 MSIX/Store 应用写进清单（`source=store`，`package_id` 留空） |
| `--timeout-ms`（新） | 30000 | 单次 winget 调用超时 |

```powershell
# 全路径调用，PATH 里没有 winget 也照样能用
$env:PYTHONPATH = "src"
python -m software_reback scan -o software.json --enrich
# 期望：已读取 55 个软件；identified 50（≥50 为回归门槛）
```

### 4.2 `download`

| 参数 | 默认 | 说明 |
|---|---|---|
| `-i/-d/--catalog/--no-name-match/--dry-run/--report/--ca-bundle` | 不变 | 保持 |
| `--resume/--no-resume`（新） | 开 | 断点续传 |
| `--concurrency`（新） | 2 | 并发 |
| `--retries`（新） | 3 | 重试次数 |
| `--timeout`（新） | 60 | 读取超时（现有内部参数外露） |
| `--allow-store`（新） | 关 | 允许 msstore 通道 |
| `--require-sha256`（新） | 关 | 无 hash 即跳过 |
| `--no-cache`（新） | 关 | 关闭按 hash 缓存复用 |

```powershell
python -m software_reback download -i software.json -d downloads --catalog catalog.json `
  --dry-run --concurrency 2 --resume
# 期望：报告里 method 分布 url/winget/unresolved 三列可见，退出码 0
```

### 4.3 新增子命令

| 子命令 | 参数 | 示例 | 说明 |
|---|---|---|---|
| `push` | `--file`(默认 software.json) `--server` `--token-env`(默认 `SR_TOKEN`) `--device-id` | `python -m software_reback push --server https://127.0.0.1:8084/api --token-env SR_TOKEN` | 上报清单（M3 隔离：`(account_id, device_id)`）。**token 只从环境变量读，不提供 `--token` 明文参数**，避免进命令行历史与日志 |
| `pull` | `--server` `--token-env` `--output` `--since-rev` | `python -m software_reback pull --output software.json` | 拉取云端清单 / 目录增量（05 §9） |
| `catalog` | `catalog add/check/push/import` | `python -m software_reback catalog check --entry entry.json` | 目录贡献（05 §8） |
| `serve` | **不做** | — | 云端是 systemd --user 单进程服务，本仓库只提供客户端；本地无 Web 服务需求 |

`push/pull` 的鉴权：`Authorization: Bearer <token>`，token 通过 `--token-env SR_TOKEN` 或环境变量读取；**任何日志都不得回显 token**（与 `PLAN-SPLIT.md` 的禁止项一致）。

## 5. 失败分类与用户可执行动作

| `error_code` | 失败类型 | 表现 | 用户该怎么办 |
|---|---|---|---|
| `winget_not_found` | winget 缺失 | `FileNotFoundError` / 版本过低 | 装 App Installer；或全路径调用；或 `--no-export` 退回仅注册表模式 |
| `winget_export_partial` | 导出阶段部分失败 | stderr 出现 `not available from any source` | 正常现象（本机 8 条）；这些条目走目录补齐，不需要处理 |
| `winget_parse_failed` | 表格解析失败 | 报告 `method` 有值但 `package_id` 空、`detail=parse` | 把 winget 输出整段保存后反馈（解析器会随版本号更新） |
| `winget_source_unavailable` | winget 源不可用 | 超时 / 429 / 源协议失败 | 换网络重试，或临时 `--no-export` |
| `ambiguous_name` | 名称有歧义 | 多条候选 | 用目录给 `match_keys` 明确别名，不自动猜 |
| `sha256_mismatch` | SHA256 不匹配 | 已下完但校验失败，`.part` 已删 | **不要安装**；把实际 hash 报给目录贡献流程（`catalog check`） |
| `size_mismatch` | 大小不符 | 落盘字节数 ≠ `size` | 同上；或换网络重试（部分 CDN 会返回截断包） |
| `http_404` / `http_410` | 链接失效 | `Not Found` | 在云端目录把该条目标 `dead`，提一个修复 URL |
| `http_403` / `login_required` | 需要登录/授权 | 302 到登录页或 403 | **不做绕过**：手动从官网下载，或走 winget/Store 通道 |
| `cert_verify_failed` | 证书校验失败 | `CERTIFICATE_VERIFY_FAILED` | 沿用现有 `--ca-bundle`（README 已说明），**不允许 `--insecure` 降级** |
| `incomplete` | 传输中断 | 字节数 < Content-Length | 直接重跑，`--resume` 会自动续传 |
| `unresolved` | 无来源 | `skipped` | 提交目录条目（05 §8）或手动安装 |
| `store_requires_auth` | Store 包无授权 | `winget download` 失败 | 用 Microsoft Store「我的应用」还原 |

## 6. 可测试性（沿用「函数参数注入依赖」）

现有风格：`cli.run_scan(collect_fn=…)`、`cli.run_download(matcher=…, url_downloader=…, winget_downloader=…)`、`winget.resolve_package_id(runner=…)`、`inventory.read_registry_entries(entry_reader=…)`。新增点如下，**全部默认指向真实实现**，测试传假实现即可全离线：

| 注入点 | 落点模块 | 签名 | 用于测什么 |
|---|---|---|---|
| `resolve_winget_path(path_getter=…)` | `winget.py`（改） | `→ str` | PATH 缺失时回落到 `%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe` |
| `run_export(runner=…)` | `winget.py`（改） | `(args)→(stdout, rc)` | 解析 export JSON、8 条 stderr 报错 |
| `parse_list_v2(output, known_ids=None)` | `winget.py`（改） | `→ (rows, errors)` | 定宽切列、CJK 错位、版本溢出（§2.4 用例表） |
| `link_records(records, export_ids, list_rows, rules=…)` | `match.py`（新） | `→ dict` | K1/K2/K3 关联与歧义拒绝；断言「未命中的就是那 5 条」 |
| `download_url(..., opener=…)` | `downloader.py`（改） | `opener(Request)→Response 假对象` | 206 续传、200 不支持 Range、416、Content-Length 不符 |
| `http_head(url, opener=…)` | `downloader.py`（新） | `→ (status, headers)` | 目录探活（05 §6） |
| `lookup(sha256, cache_dir=…)` | `cache.py`（新） | `→ path` 或 `None` | 按 hash 命中/未命中 |
| `snapshot(getenv=…, platform_info=…)` | `env.py`（新） | `→ dict` | 环境快照字段（§2.6） |
| `write_report(outcomes, path, fields=…)` | `store.py`（改） | — | 新字段追加且旧列序不变 |

新增离线 fixture：`tests/fixtures/winget-list-1.29.380.txt`（真实输出，表头前有一个空行，共 155 行）、`winget-export-1.29.380.json`（52 条）、`software-55.json`（本机清单）。回归门槛两条用例：

1. `parse_list_v2(fixture)` → 153 行数据、142 个不同 Id；
2. `link_records(...)` → `identified == 50`，未命中集合恰为 `{Google Chrome, Microsoft Office 专业增强版 2019 - zh-cn, PUBG: BATTLEGROUNDS, 向日葵远程控制, 游戏加加}`。

## 7. 不做什么

- **不自动执行安装**：不调 `msiexec`、不跑 `setup.exe`、不传 `silent_args` 给任何进程（`silent_args` 仅落库）。
- **不绕过需要登录的下载站**：不做 cookie 注入、不模拟登录、不处理验证码。
- **不下载破解版 / 绿色版 / 网盘分享链接**：目录与清单都只接受官方或厂商自有域名。
- **不降级 TLS**：不提供 `--insecure`，只提供 `--ca-bundle`。
- **不修改系统状态**：不改 PATH、不装驱动、不动 Windows 设置。
- **不在 PATH 缺失时静默跳过 winget**：必须显式报 `winget_not_found`，避免「看起来跑通了但一个都没识别」。
- **不猜测绑定**：任何歧义一律留空并记 `match_rule=none`。
