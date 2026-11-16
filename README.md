# software-reback

重装 Windows 前把「装了哪些软件」变成一份可复用的清单，重装后按清单把安装包批量取回。

本项目只做两件事，刻意不碰「安装执行」：

1. **读取软件信息**：扫描注册表卸载项，输出结构化清单 `software.json`
2. **下载软件包**：把清单里的每一条翻译成「从哪下、怎么校验」，批量下载到本地目录，并产出可勾选的报告

安装包本体不托管、不做二次分发，只记录下载来源 —— 这是它能在没有额外存储介质的前提下工作的原因。

## 环境要求

- Windows 10/11（读取注册表依赖 `winreg`）
- Python 3.10+
- winget（Windows 11 自带；`winget --version` 能输出即可）
- 无第三方依赖，`urllib` 走 HTTP，`unittest` 跑测试

如果直链下载报 `CERTIFICATE_VERIFY_FAILED`（常见于 Python 未加载站点所需根证书），用 `--ca-bundle` 指定一个公共 CA 包（例如 curl 的 [cacert.pem](https://curl.se/ca/cacert.pem)），校验依然严格，只是换了信任源：

```powershell
python -m software_reback download -i software.json -d downloads --ca-bundle C:\certs\cacert.pem
```

## 运行

```powershell
# 不安装，直接以源码运行
$env:PYTHONPATH = "src"
python -m software_reback scan -o software.json
python -m software_reback download -i software.json -d downloads

# 或者安装成命令
pip install -e .
software-reback scan -o software.json
```

## 功能 1：读取软件信息

```powershell
python -m software_reback scan -o software.json
```

数据来源是三个注册表位置（与「设置 → 应用 → 已安装的应用」同源）：

| 位置 | 覆盖范围 |
|---|---|
| `HKLM\...\Uninstall` | 64 位机器级安装 |
| `HKLM\WOW6432Node\...\Uninstall` | 32 位机器级安装 |
| `HKCU\...\Uninstall` | 当前用户级安装 |

过滤规则：丢弃无显示名、`SystemComponent=1`（系统组件）、有 `ParentKeyName`（补丁/子项）的条目；同名同版本的多条记录合并成一条，缺失字段互相补齐。

输出格式：

```json
{
  "schema_version": 1,
  "generated_at": "2026-11-15T22:05:00+08:00",
  "software": [
    {
      "name": "Notepad++ (64-bit x64)",
      "version": "8.9.8.1",
      "publisher": "Notepad++ Team",
      "install_location": "C:\\Program Files\\Notepad++\\",
      "source": "registry",
      "package_id": ""
    }
  ]
}
```

`package_id` 为空表示还没绑定 winget 包。加 `--enrich` 会逐个去 winget 搜索补齐（每个软件一次网络查询，55 个软件约 1–2 分钟）。

## 功能 2：按软件信息下载软件包

```powershell
python -m software_reback download -i software.json -d downloads
```

每条记录的来源按以下优先级决策（`resolver.py`）：

1. **软件目录里的直链**：可带 `sha256`，最可控，适合 winget 覆盖不到的软件
2. **记录自带的 winget 包 ID**（`scan --enrich` 产生的）
3. **按名称自动匹配 winget**：默认开启，`--no-name-match` 关闭
4. **无法解析**：写入报告，进人工清单

先看计划再决定是否下载：

```powershell
python -m software_reback download -i software.json -d downloads --dry-run
```

报告 `download-report.csv`（UTF-8 带 BOM，Excel 可直接打开）字段：

| 字段 | 含义 |
|---|---|
| `name` / `version` | 软件名与版本 |
| `method` | `url`（直链）/ `winget` / `unresolved` |
| `status` | `ok` 已下载 / `planned` 仅计划 / `failed` 失败 / `skipped` 无来源 |
| `target` | 实际落盘文件路径（winget 会记录新增的文件）；计划阶段是 URL 或包 ID |
| `detail` | 失败原因或跳过原因 |

`main()` 在有失败项时返回码为 2，便于接到脚本或 CI。

## 名称匹配怎么做的

注册表里的显示名往往带噪声：`Notepad++ (64-bit x64)`、`OBS Studio 32.2.2`、`Python (64-bit)`。直接精确匹配的覆盖率会很低，但放宽过头会装错软件，所以分两轮：

1. **精确轮**：名字完全相同，或 winget 表头被截断（`…`）时按前缀匹配
2. **归一化轮**：剥掉括号说明与尾部版本号后再比较，且**候选包 ID 必须唯一**才采用；有歧义（比如同时命中 `Python 3.12` 和 `Python 3.13`）一律放弃

另外两条硬规则：

- **商店包默认跳过**。`winget download` 拉 msstore 包需要授权，实测容易失败；Store 应用重装后从「我的应用」库还原更可靠。需要时可在代码层传 `allow_store=True`。
- **宁漏不误**。任何一步拿不到唯一解，就落到 `unresolved` 进人工清单，绝不猜。

## 软件目录（补漏入口）

`catalog.example.json` 是结构示例（其中 URL 均为占位地址，需替换成官方真实地址）：

```json
{
  "entries": [
    {
      "display_name": "微信",
      "url": "https://example.com/WeChatSetup.exe",
      "file_name": "WeChatSetup.exe",
      "sha256": "官方安装包的真实 SHA256",
      "silent_args": "/S"
    },
    {
      "display_name": "NVIDIA App",
      "winget_id": "Nvidia.App"
    }
  ]
}
```

索引键是 `display_name`（比较时忽略大小写与多余空格）。`url` 与 `winget_id` 至少给一个；`sha256` 非空时会强校验，不匹配直接判失败且不留下半成品文件。

```powershell
python -m software_reback download -i software.json -d downloads --catalog catalog.json
```

## 实测覆盖率（单机样本，供参考）

在一台装了 55 个软件的 Win11 机器上跑 `scan` + `download --dry-run`：

- 自动匹配成功 **14 个**（Chrome、OneDrive、Steam、FFmpeg、剪映、抖音、豆包、迅雷、百度网盘、网易邮箱大师、游戏加加、Clash Verge、豆包输入法、Python Launcher）
- 其余 **41 个** 进 `skipped`：商店包、VC++ 运行库、NVIDIA 驱动组件、Office、微信/QQ、以及部分工具类软件（名字与 winget 目录不一致或 winget 未收录）

也就是说，**单纯靠 winget 只能解决四分之一左右**。剩下的大头正是 `catalog` 需要补的部分 —— 这也解释了为什么这类工具的核心工作量在目录维护，而不是代码。

## 安全与合规边界

- 只按**已记录**的来源下载：直链来自 `catalog`，包 ID 来自清单；不接受临时输入拼接
- `sha256` 非空即强制校验；下载先写 `.part`，校验通过才原子改名，失败不留残留文件
- 不缓存、不再分发第三方安装包（多数 EULA 禁止再分发）；工具只负责「找到官方地址」与「校验完整性」
- 清单含软件名称，属于个人信息，`software.json` 已在 `.gitignore` 中排除

## 测试

```powershell
python -m unittest discover -s tests -v
```

64 项测试，覆盖：注册表条目归一化与去重、winget 表格解析（含列被挤压成单空格的真实情况）、名称匹配的精确轮/归一化轮/歧义拒绝、商店包策略、目录加载、下载计划的四级优先级、HTTP 真实下载与 SHA256 失败路径、CA 证书包缺失的早期报错、清单与报告的读写、CLI 编排。

## 未实现的部分

- **安装执行**（静默参数下发与状态回传）—— 刻意不做，避免「下载即执行」的安全问题
- 驱动、Windows 设置、PATH、字体、开发环境等迁移
- Store 应用还原（建议交给 Microsoft Store 的「我的应用」）
- 云端托管与账号化（清单目前是本地文件）

## 设计文档（下一步方向：云端 + 多用户隔离）

上面的「云端托管与账号化」已有完整设计方案，在 [`docs/`](docs/README.md)：

| 文档 | 内容 |
|---|---|
| [docs/README.md](docs/README.md) | 索引、四类需求对应关系、待评审定案的 4 处口径冲突 |
| [docs/01-features.md](docs/01-features.md) | 功能清单：M1 读取 / M2 下载 / M3 隔离 / M4 汇总，35 个功能点与验收标准 |
| [docs/02-architecture.md](docs/02-architecture.md) | 架构：notebook 上 `systemd --user` 单进程 + SQLite，含内存预算与 10 条决策记录 |
| [docs/03-api-contract.md](docs/03-api-contract.md) | 接口契约：20 个端点、17 个错误码、清单 schema v2、9 张表 DDL |
| [docs/04-isolation.md](docs/04-isolation.md) | 隔离设计与**可自动复现的 35 条越权用例**（账号 + 机器双维度） |
| [docs/05-catalog.md](docs/05-catalog.md) | 软件汇总（目录）schema v2、来源分级、失效探活、贡献审核 |
| [docs/06-client.md](docs/06-client.md) | 客户端强化：`winget export` + `winget list` 双路融合（覆盖率 25% → 90.9%） |
| [docs/07-roadmap.md](docs/07-roadmap.md) | 路线图：M0–M5 里程碑、依赖顺序、风险与逐步验证命令 |

> 文档阶段**不改动**现有 `src/` 与 `tests/`；64 个测试仍全部通过。
