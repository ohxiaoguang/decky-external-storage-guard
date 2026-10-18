# 验证记录

## v0.2.0 安全重新挂载

日期：2026-10-18（Asia/Shanghai）。本节记录 v0.2.0；后文保留 v0.1.0 的历史验证结果。

- `npm run package` 本地通过：**76 项 Python 自动化测试**、严格 TypeScript 类型检查、Rollup 编译、安装 ZIP 结构检查和包内后端 / 前端 ESM 入口隔离加载均通过。
- 打包后的前端使用测试专用 hooks / Decky 组件桩验证：打开确认框不执行操作、取消后也不能通过旧回调执行、确认仅发送一次授权令牌、操作中禁用、成功 / 失败状态、失败后显示后端真实未挂载状态，以及后续使用新授权操作。
- 新增后端安全验证覆盖：SD / USB 数据分区资格，内置 NVMe 拓扑、eMMC、整盘、EFI、swap、映射 / holders、系统挂载目录、非支持挂载点和 Decky 自身运行目录排除；前端任意路径、过期 / 重放授权拒绝；UUID / PARTUUID / 设备号 / diskseq / 挂载点变化；读取故障日志后再次校验；块设备文件类型与 swap 文件使用检查。
- 事务测试覆盖：仅固定参数的非交互 UDisks 命令；busy / 权限不足 / 缺少工具 / 卸载失败立即停止，不调用 mount；卸载后掉线 / 设备复用 / 自动挂载停止；挂载失败和状态验证失败不报告成功；超时结果未知；只读和文件系统故障不尝试可写挂载；exFAT / NTFS 的数值 uid / gid、权限掩码和安全选项保留；并发拒绝及请求取消保护；原子状态记录和中断提示；首次状态写入失败拒绝卸载。
- 现有设备发现和全部监控测试继续通过。生产后端在当前容器实际扫描成功、外部设备 0、journal 状态 `no_logs`；没有显示虚构设备，**没有在开发环境执行真实 unmount / mount**。
- `python3 scripts/check_release.py v0.2.0` 通过，package / lock 版本一致。固定名称仍为 `External-Storage-Guard.zip`，白名单包含新增的 `remount.py` 和 `operation_store.py`；测试桩不进入安装包。
- **待实机验证**：SteamOS UDisks / polkit 实际授权、SD / USB 桥接盒 sysfs 与分区标识兼容性、非 Linux 文件系统实际挂载选项、Steam 游戏库路径、手柄确认 / 取消和焦点、真实 busy 状态、系统强制终止时的操作记录。自动化通过不等于真实重新挂载已验证。
- 使用前备份重要存档并关闭设备上的游戏 / 程序。没有强制卸载、fsck、全局权限修改或设备重置；用户空间检查无法消除物理拔插 / 断电的全部风险。遇到权限信息不足或失败结果会拒绝 / 停止，不降低保护。

## v0.1.0 历史记录

日期：2026-10-18（Asia/Shanghai）。仓库：`ohxiaoguang/decky-external-storage-guard`，交付分支：`feat/external-storage-guard-v0.1.0`。

## 已实际完成

- 检查空仓库并参考官方模板 commit `90d0780e882a17f5714fc6de044c645f22608290`，核对 Loader commit `67196ad` 的 API v1 后端加载、ESM 类型、root 标志与本地 ZIP 安装流程。
- 开发环境：Linux 容器，Python 3.12.14、Node.js 24.19.0、npm 11.9.0。该环境不是 SteamOS，没有 Decky UI、真实 SD / USB 存储或可读取的内核 journal。
- `npm ci --ignore-scripts --offline --cache /workspace/work/npm-cache` 成功，验证锁文件能够复现依赖安装；CI 中采用常规 `npm ci --ignore-scripts`。
- `npm run typecheck` 成功；不使用 `skipLibCheck` 隐藏依赖类型问题。
- `python3 -m unittest discover -s tests -v`：**44 项测试全部通过**。覆盖用户提供的 MMC 案例，USB / UAS / 文件系统，内置盘排除，实际 sysfs 链接读取，未挂载 / 多挂载 / 只读，历史启动和设备名 / 端口复用边界，无法关联，权限 / 无历史 / 空日志 / 错误格式，命令缺失 / 超时 / 输出上限，取消子进程和卸载生命周期。
- `npm run build` 成功，输出官方 Rollup 配置的 ESM `dist/index.js` 与 source map。
- `npm run package` 成功；ZIP 结构检查成功；安装包解压到仓库外后，使用 Loader 等价的 `spec_from_file_location('_', main.py)` 成功加载后端并运行加载 / 卸载生命周期。
- 对安装包中的前端 ESM 入口使用测试专用 Decky / React 桩验证：默认插件定义、名称、内容、图标、`get_snapshot` callable 与卸载入口有效；未渲染真实 Steam UI。
- 当前环境实际调用生产 `Service.snapshot('boot')`：设备扫描成功，外部设备 0；journal 返回 `no_logs`、事件 0，并明确提示无法据此判断设备正常。没有用 mock 填充设备。
- `git diff --cached --check` 无空白错误。安装包白名单不包含 tests、node_modules、mock 数据或 Python cache。

## 已修复的验证问题

- NTFS3 的 `ntfs3: sda: ...` 前缀匹配。
- 官方模板当前依赖缺少 `@types/react-router` 导致的严格类型检查失败。
- `journalctl -k` 隐含本次启动，导致最近 24 小时跨启动日志遗漏；改用 `_TRANSPORT=kernel` 与固定时间参数。
- 权限不足提示与“没有历史”同时出现时，优先显示权限错误。
- 同一启动内重新 attach / USB 端口复用造成的错误归属风险；无法确认世代时保守地放入未关联或排除无存储证据的 USB 日志。
- 日志已截断时不显示“已读取日志中没有异常”的结论。
- Python 3.10 与较新版本的 asyncio 超时异常兼容处理；本机实际测试版本是 3.12，并未在 3.10 单独运行。

## 待实机验证

- SteamOS / Decky Loader 安装、真正的前后端通信和 root 标志在目标版本上的权限表现。
- ROG Ally X 原生 MicroSD 拓扑、约 477 GiB 的 512GB 卡、真实 ext4 状态及历史内核日志。
- Steam Deck、不同 USB HDD / SSD 与硬盘盒的总线 / ROTA 报告差异。
- 游戏模式手柄焦点、长日志滚动、筛选、分页、本地时间显示。
- 真实设备安全断开 / 重连、多设备并用，以及打开 / 关闭菜单时的性能和耗电。
- 初版 GitHub Actions 检查已[成功运行](https://github.com/ohxiaoguang/decky-external-storage-guard/actions/runs/39119336239)；尚未发布到插件商店。

## 已知保守限制

上次启动的设备名不会与本次启动直接关联；无可靠身份的历史异常在“未关联事件”。没有存储驱动 / 拓扑证据的历史 USB 总线日志会被忽略，可能漏掉部分已拔出 UAS 设备事件。日志尾部缺失身份变更证据时仍存在同名设备复用风险；ROTA 只是 USB 介质类型提示。计数仅覆盖当前返回的有限记录。

纯 `USB disconnect` 按信息展示，因为它不能证明意外拔出；真实 I/O、offline、文件系统或异常只读仍按严重展示。插件不主动测试故障或执行任何恢复动作。

具体构建、ZIP 安装与 8 项 ROG Ally X 验收步骤见 README。

## 自动发布流程补充验证

- 本地 `npm run package` 通过：现为 47 项单元测试（新增标签 / package / lock 版本校验），严格类型检查、Rollup 构建、ZIP 检查及包内入口隔离加载均通过。
- `actionlint` v1.7.7 对检查与发布两个工作流验证通过。
- 安装包统一为 `out/External-Storage-Guard.zip`，内部唯一顶层目录仍为 `external-storage-guard/`，包含编译后的 `dist/index.js`、manifest、Python 后端与完整 `storage_guard` 模块，不包含测试或依赖目录。
- 标签工作流在构建验证通过后，以 `contents: write` 的独立任务发布 Release 安装资产与 SHA-256；README 包含 latest 下载直链、URL 安装和手动后备步骤。具体远程执行结果以对应标签的 Actions 记录和 Release 资产为准。
- 已实际推送 `v0.1.0` 标签，[发布工作流](https://github.com/ohxiaoguang/decky-external-storage-guard/actions/runs/39119713695) 的构建与发布任务均成功；对应 main 分支[检查任务](https://github.com/ohxiaoguang/decky-external-storage-guard/actions/runs/39119697719) 也成功。
- 已确认 [v0.1.0 Release](https://github.com/ohxiaoguang/decky-external-storage-guard/releases/tag/v0.1.0) 非草稿、非预发布，并包含 `External-Storage-Guard.zip` 与 `.zip.sha256` 独立资产。
- 从 README 的 `releases/latest/download/External-Storage-Guard.zip` 实际下载，SHA-256 校验、完整插件目录检查、包内后端 / 前端入口隔离加载全部通过。实际 ZIP 大小 468465 字节，SHA-256 为 `dc02e8b98a0469bcfa3261caee20a1138379c538fb1c1415f5f46b3b1d8a3080`。这仍不等同于 SteamOS 实机 UI 验收。
