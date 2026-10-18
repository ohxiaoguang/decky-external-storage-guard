# v0.1.0 验证记录

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
- GitHub Actions 工作流已编写，本次未在 GitHub 执行；尚未发布到插件商店。

## 已知保守限制

上次启动的设备名不会与本次启动直接关联；无可靠身份的历史异常在“未关联事件”。没有存储驱动 / 拓扑证据的历史 USB 总线日志会被忽略，可能漏掉部分已拔出 UAS 设备事件。日志尾部缺失身份变更证据时仍存在同名设备复用风险；ROTA 只是 USB 介质类型提示。计数仅覆盖当前返回的有限记录。

纯 `USB disconnect` 按信息展示，因为它不能证明意外拔出；真实 I/O、offline、文件系统或异常只读仍按严重展示。插件不主动测试故障或执行任何恢复动作。

具体构建、ZIP 安装与 8 项 ROG Ally X 验收步骤见 README。
