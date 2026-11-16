# 并行拆分与统一基线（主控维护）

## 已确认的前提（来自用户 + 实测，所有子任务必须遵守）

| 项 | 结论 | 证据 |
|---|---|---|
| 代码基线 | `G:\git\software-reback` 已有可运行 CLI（scan/download），64 测试全绿，**必须复用，不重写** | `python -m unittest discover -s tests` = 64 OK |
| 云端主机 | notebook `192.168.1.24`，Ubuntu 24.04，Python 3.12.3，4 核 / 11G 内存（已用 5G） | ssh 实测 |
| 云端依赖 | pypi 可装（venv + pip 正常），npm 镜像可用；**github.com / cdn.jsdelivr.net 从 notebook 不可达(000)** → 不能依赖 GitHub raw / CDN 资源 | curl 实测 |
| 云端落地形态 | **systemd --user 单进程轻量 HTTP 服务**，不碰 Docker、不动现有 16 个容器 | 用户选定 |
| 端口 | 已占用：22/80/443/3080/5003/8080/8083/8090/9443。**预留 8081-8089**（frp 已映射 cloud1:20081-20089），本方案取 **8084** | ss -ltnp |
| 隔离强度 | **账号级 + 机器级（device_id）** 双维度；配套**可自动证明的越权测试**（伪造他用户 token、篡改 ID、跨用户读写必须全部拒绝） | 用户选定 |
| 本轮范围 | **只写文档，不部署、不改服务器、不改现有代码** | 用户选定 |
| 本机 winget | 版本 v1.29.380，在 `%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe`（**PATH 里没有，必须用全路径**）；`winget export` 产出 **52 条**可用包 ID，但 8 个软件无法从任何源解析 | 实测 |
| 注册表清单 | `software.json` 共 **55** 条 | 实测 |
| 关键基线差距 | 现有 `winget.py` 名称匹配覆盖率约 25%（14/55）；`winget export` 能给出 **52** 条精确 ID。**结论：清单上报必须走 winget export ID 优先，名称匹配只做兜底** | README 覆盖率 + 实测 |
| **新增实测（主控验证，2026-11-15）** | **`winget list` 155 行 = 72 条 MSIX 应用 + 63 条 winget 源应用；export 的 52 个 ID 在 list 中 100% 可命中(52/52)。注册表 55 条按精确名与 list 关联命中 50 条(90.9%)，仅 5 条未命中**（Google Chrome / Office 2019 / PUBG / 向日葵远程控制 / 游戏加加）。**这就是目标指标：识别覆盖率 25% → ≥90%** | 实测 |
| winget 输出格式坑（实测） | `winget list` 是**定宽空格表**，有单元格溢出行（版本号溢出到下一列，如 `26288.2004.5269.3420 winget`）；行分隔不能只靠 `\s{2,}`，需按表头列位置切片 + 溢出兜底 | 实测 |

## 文档产物（都写到 `G:\git\software-reback\docs\`）

| 文件 | 负责 | 内容 |
|---|---|---|
| `01-features.md` | A | 功能清单（总纲：模块编号、功能点、优先级 P0/P1/P2、验收标准） |
| `02-architecture.md` | B | 架构说明：分层、组件、部署拓扑、技术选型、与现有代码的复用边界 |
| `03-api-contract.md` | B | 云端 HTTP 接口契约 + 数据模型 + JSON 示例 + 错误码 |
| `04-isolation.md` | C | 隔离设计 + **可执行越权验证用例**（负面测试矩阵） |
| `05-catalog.md` | D | 软件汇总（目录维护）：schema、来源、合并规则、健康度度量、数据源采集策略 |
| `06-client.md` | D | 客户端：读取/匹配/下载强化设计，含 export+dump 双路识别与匹配优先级 |
| `07-roadmap.md` | A | 实施路线图：里程碑、任务分解、依赖顺序、风险 |
| `README.md`(更新) | 主控 | 文档索引 + 现状说明 |

## 统一术语与编号（所有文档必须一致）

- **模块编号**：M1 读取、M2 下载、M3 隔离、M4 汇总（软件目录）
- **隔离双维度**：`account_id`（账号）+ `device_id`（机器指纹），资源键一律 `(account_id, device_id, ...)`
- **服务名**：`software-reback-cloud`，监听 `0.0.0.0:8084`
- **客户端**：现有 `software-reback` CLI 扩展 `cloud` 子命令
- **清单 schema**：`schema_version: 2`（v1 → v2 需向后兼容读取 v1）
- **认证**：Bearer token（`Authorization: Bearer <token>`），token 绑定 `(account_id, device_id)`
- **禁止**：任何文档不得把真实密码/token/私钥写进仓库；示例一律用占位符

## 硬性约束（每个子任务都必须遵守）

1. **不要修改 `G:\git\software-reback\src` 与 `tests` 下的现有文件**。只写你负责的 `docs/*.md`。
2. 只写自己的文件，**不要动别人的文档**，避免互相覆盖。
3. 结论必须可验证：给出命令、期望输出、或数据表，不要写「大概」「应该能」。
4. 中文文档，术语保留英文原词（如 winget、SHA256）。
5. 明确写出**不做什么**（范围外），避免范围蔓延。
6. 涉及云端的地方，必须符合「systemd --user 单进程、不碰 Docker、notebook 出网受限(pypi 可用/github 不可达)」这三条实测约束。
7. 篇幅控制在 150–350 行，宁可表格化、清单化，不要长篇散文。
