# 验证记录

## v0.5.2 无弹窗交互修复

日期：2026-10-19（Asia/Shanghai）。以下自动化结果来自 Linux 容器，尚未进行真实 SteamOS 验收。

- 参考 [Decky Clash 固定提交的页面入口](https://github.com/chenx-dust/DeckyClash/blob/a9a78b6afb2f536d9a305c3b8000cf521a404d3c/src/index.tsx#L677)：实际注册 `/decky-clash` 路由，通过 `Router.CloseSideMenus()` / `Router.Navigate()` 进入 `SidebarNavigation`，管理内容使用 `DialogBody`、`Focusable` 和原生按钮。其源码没有为管理页单独实现原始日志滚动。本项目采用用户允许的 App 内条件渲染，保留主页设备数据，使用原生 Focusable / DialogButton 和独立滚动区，不引入其多页侧栏架构。
- 排查：原按钮没有主动调用插件重载；`onDismount` 仅注册插件卸载清理。原卸载 RPC 位于 ConfirmModal 的 onOK，若未完成确认就不会发出；两个入口均同步调用 showModal，并访问返回句柄及 ClosedPromise，异常会离开按钮回调。没有真实掌机前端异常堆栈，无法证明是哪一处 Steam / Decky 兼容异常触发了现场现象。此次彻底删除这两个弹窗入口与关闭回调，没有吞掉异常后假装成功。
- App 始终持有设备、操作结果和请求锁；切换日志页不调用 disposeViews、不重新执行初始 get_snapshot。日志页只读 get_logs；返回不重置设备数据。包内 ESM 使用的四个 RPC 名称与包内 main.py 相符，均随同一版本打包；无法远程确认掌机当前安装的前后端是否混用旧文件。
- 卸载首次点击不发送 RPC；第二次确认后发送一次 unmount_partition。取消、15 秒到期（包括计时器延迟时的截止时间校验）、移动到其他分区、刷新设备、离开主页和实际插件卸载均撤销确认。重复或过时的回调不能执行旧操作。操作中按分区显示“卸载中…” / “挂载中…”，禁用重复请求。
- 成功需要后端 verified 和返回快照中的实际挂载状态一致；缺少快照、状态矛盾、未验证成功或通信异常均明确不确定。失败保留设备卡片并显示原始原因。未修改 UDisks、sysfs / 系统盘 / 分区身份保护、只读保护、返回码和真实状态复核流程；未恢复自动重挂载、持久化或后台轮询。
- `npm run package`：严格 TypeScript、57 项 Python 测试、Rollup、ZIP 结构、隔离后端生命周期 / 前端 ESM 与交互测试通过。交互测试包括两阶段卸载、取消 / 到期 / 换设备 / 状态变化、busy / 失败 / 不确定、真实卸载与挂载后按钮状态、日志页刷新 / 返回保留设备与反馈、不重发初始化读取、原文逐字复制与失败、截断提示、手柄 / 键盘滚动、更新链接与实际卸载清理。日志读取与复制上限保持原样。

### SteamOS 实机验证步骤

1. 安装本版 Release 的 External-Storage-Guard.zip，确认 Decky 显示版本为 0.5.2。若之前发生热更新混用或前端异常，先重启 Decky / 游戏模式，再开始测试。
2. 插入已备份数据的 MicroSD 或 USB 盘，点击刷新，核对具体分区。内置 SSD 不应出现；多分区应分别展示。
3. 关闭使用目标分区的游戏和程序，点击“卸载”：只应变成“确认卸载”并出现取消，设备仍挂载。验证取消、等待 15 秒、换分区焦点、进入日志页后返回，都不会执行卸载。
4. 再次点击“卸载”与“确认卸载”：应显示“卸载中…”，完成后同一主页显示“卸载成功”和“未挂载”，挂载按钮可用。用桌面模式磁盘工具或 findmnt 独立核对实际状态，不要求内核必须输出 EXT4 卸载消息。卸载不等于 USB 已断电。
5. 点击“挂载”：应显示“挂载中…”，完成后显示已挂载、实际路径及读写状态，挂载按钮禁用。用系统磁盘工具 / findmnt 再核对；只读分区不得被强行转成可写。
6. 使用一个非关键分区并让普通程序占用它，再尝试卸载：如果系统拒绝，应显示真实 busy 原因并保持已挂载，不强制卸载。不要用重要游戏存档做占用试验。
7. 点击“查看日志”：必须进入日志页，顶部只有返回、刷新、复制。检查方向键 / 手柄上下和激活翻页、键盘 PageUp / PageDown、触屏及鼠标滚动；原文换行、截断提示和刷新失败应正常显示。复制后粘贴核对原文；按返回或手柄 B 应回主页，设备状态和操作反馈仍在。
8. 操作期间不要拔盘或终止进程。通信中断等无法确认时必须显示不确定，等待后手动刷新；不通过制造真实写入中断来测试断连。断连和替换场景由自动化桩覆盖。

实机尚待确认：当前 Steam / Decky 版本的焦点行为和日志页高度、Steam CEF 剪贴板、设备兼容性、UDisks 权限 / 占用失败表现，以及原问题是否仍能复现。容器中没有执行真实分区挂载、卸载或任何修复。

## v0.5.0 单层分区操作与原始日志

日期：2026-10-19（Asia/Shanghai）。历史章节描述旧版行为，不再是当前功能说明。

- 删除详情 / 报告 / 过滤 / 统计 / 休眠关联组件及 events / rules / suspend / report / export / hardware 后端模块。保留设备发现、系统盘排除、UDisks 安全策略、有界 subprocess、原始 journal；测试随已删除功能移除和替换，不能用旧版测试数量表示当前覆盖。
- `npm run package`：**57 项 Python 测试**、严格 TypeScript、Rollup、安装 ZIP / 包内后端生命周期与前端 ESM / 交互桩检查通过。`check_release.py v0.5.0` 校验 package / lock 版本；固定安装资产名称与更新直链不变。
- 分区操作测试：unmount 仅一条命令且验证无挂载、不调用 mount / power-off；mount 仅未挂载分区、返回码及实际路径 / 权限 / RO 验证；返回0无状态变化为不确定；busy、授权失败、超时、断开、命令两路输出、身份更换与错误分区、过期 / 动作错误 / 重放 token；原系统盘 / eMMC / EFI / swap / 映射 / Decky自身 / sysfs / 块设备文件保护继续通过。
- 非 Linux 文件系统测试：已验证卸载前的数值 uid / gid / 掩码、安全及 RO 选项在同一连接保留；新连接不能套用旧参数；首次挂载可靠确认桌面用户，否则拒绝默认 root 权限。实际文件系统和 UDisks 支持仍待实机。
- 生命周期测试：并发拒绝、RPC 与卸载等待取消不取消操作；强制取消明确不确定；读取取消与插件卸载；会话仅保留最近结果，不生成持久化文件。
- journal 测试：当前 boot 固定查询同时含 kernel / systemd / udisks2，原始消息 / 来源 / 微秒时间戳、顺序、无中文解释、不改写内容、二进制数组、输出 / 条数 / 文本截断、权限 / 空日志 / 坏 JSON / 输出超限。设备刷新不依赖 journal。原文不再脱敏，README 提示分享前检查。
- 前端交互桩：单层结构和每分区按钮；确认 / 取消 / 重复点击；卸载后未挂载及 mount 启用；挂载后实际只读 / 路径；0返回但未验证不显示成功；失败 / 刷新异常保留卡片；稳定设备 key、操作后不重新初始化页面 / 重发初始读取；多分区目标。日志 ModalRoot 三个按钮、刷新 / 失败保留、全文逐字复制、截断反馈保留、脚本安全编码、焦点恢复、手柄方向 / 键盘翻页回调及更新链接复制均通过。
- 生产代码在容器实际只读扫描 / 原始日志接口的情况见本轮交付；未执行实际设备挂载、卸载、断电或修复。README 提供“先卸载→保持未挂载→独立挂载”的真实 SteamOS 核对步骤。
- 当前环境无法验证实际 SteamOS UDisks / polkit、物理设备、游戏占用、真实内核 / udisks2 日志、ModalRoot 最大尺寸与手柄焦点、Steam CEF 剪贴板。测试桩通过不代表实机验收；不把此前界面看起来重进一次的现象断言为已定位现场原因。
- 未合并或创建 v0.5.0 标签 / Release；现有标签触发发布流程保持并继续进行安装包验证。


## v0.4.0 精简主页与会话操作结果

日期：2026-10-18（Asia/Shanghai）。以下结果来自 Linux 容器；历史版本记录仅供追溯，v0.4.0 已取消历史章节中的持久化机制。

- `npm run package`：**125 项 Python 测试**、严格 TypeScript、Rollup、安装 ZIP 结构、包内后端生命周期和前端交互桩检查通过。操作历史持久化测试随代码移除，替换为内存会话、无文件写入、生命周期和历史只读误判回归测试。
- UI 检查：主页无筛选器、休眠历史和长状态面板；选中设备后的简洁操作 / 报告入口；设备文件系统与挂载 / 读写状态；详情导航保留原始日志、睡眠筛选与分页、报告 / TXT；返回主页恢复本次开机；更新区域位于主页底部，版本来自 package 元数据，固定 ZIP 链接复制成功 / 失败及重复点击处理。
- 重新挂载检查：Plugin RPC 调用、返回码 / 两路输出、身份 / 资格 / mounted→unmounted→mounted 复核、busy / 超时 / 挂载失败不能误报成功、当前 RO / emergency_ro 不解除；历史 aborted 即使缺少后续 mount 消息也不再直接强制 ro，后续挂载只标为历史而不宣称修复。
- 生命周期检查：前端 RPC 取消后继续事务；成功卸载进入 mount 后同时取消 RPC 和插件卸载等待仍完成挂载；显式强制取消事务保留不确定结果；刷新异常不丢失已完成结果。只保留最近一次会话结果，新 Service 无历史；无运行目录也不再依赖写入审计才能操作；不生成两个旧 JSON 文件。
- 报告保留原始内核 / 休眠信息与独立章节的会话最近操作结果，并默认脱敏；新操作或快照变更会失效前端报告缓存，避免刚操作后复制旧结果。
- 读取 / 设备识别 / 休眠电源错误分类 / 导出 / 脱敏及原有系统盘防护测试保留。ZIP 验证额外确认没有 operation_store.py、remount-state.json 或 remount-audit.json。既有 release.yml 固定安装资产名与更新链接一致，无 Source code ZIP 替代。
- `check_release.py v0.4.0` 校验 package / lock 版本。未创建 v0.4.0 正式标签或 Release。
- 真实 SteamOS 验证步骤见 README 最后一节：手柄导航、设备对照、空闲安全重挂载、busy、历史维修后的正常 RW、当前 RO、关闭菜单 / 卸载等待、剪贴板与 TXT、真实 suspend 日志。未在容器执行真实磁盘卸载 / 挂载、修复或休眠，不能确认该掌机现场为何没有 EXT4 消息。
- 不持久化意味着进程强制终止 / 断电后无法恢复旧操作结果；无历史不能证明上次成功。运行中的取消屏蔽不能对抗整个进程被杀，README 明确说明并要求核对实时状态。


## v0.3.0 增补：重新挂载审计与 MMC 电源时间线

- 先定位调用链：确认按钮调用 `remount_partition`，后端顺序执行 UDisks unmount / mount，既有代码已检查返回码及状态；没有用刷新代替挂载。发现并修正中间状态过早记录“已卸载”的问题，成功标志延后至全部验证通过。
- `npm run package`：**125 项 Python 测试**，严格 TypeScript、Rollup、ZIP 结构 / 隔离加载与既有前端检查通过。新增交互检查覆盖休眠时间线三个阶段、原始事件和分页；不等同于真实 Steam UI。
- 独立审计测试：实际 Service 事务与 Plugin RPC 转发；无 EXT4 日志但真实三阶段验证通过可成功；命令返回 0 而未卸载或未重新挂载不能成功；busy / 超时立即停止；命令两路输出、返回码 / 时间 / 挂载证据 / 失败原因持久化；同一操作 ID 更新而不重复；无运行目录 / 无法写入 / 损坏 / 符号链接拒绝；50 次及大小上限、脱敏 / 权限、按 Boot 与历史范围导入报告。
- 用户提供的电源日志测试：s2idle 开始后的 Cache Flush -84、退出后一秒的 Cache Enable -84、runtime suspend / resume -84、连续 Tuning failed；独立分类先于 CRC，覆盖周期内外、跨 Boot、日志缓冲源时钟、诊断报告时间线及原始 JSONL。
- 没有在开发容器执行真实卸载、挂载、休眠或设备重置。尚缺该掌机的实际操作审计，因此不能将“无 EXT4 日志”的现场原因断言为某一种权限 / 忙 / 命令失败。既有监控采集与设备安全策略保持；新时间线只读，不自动重新挂载。

## v0.3.0 休眠诊断与脱敏报告

日期：2026-10-18（UTC）。开发环境为 Linux 容器，不是 SteamOS；以下自动化结果不代表掌机实机验收。

- `npm run package`：**110 项 Python 自动化测试**、严格 TypeScript、Rollup 编译、ZIP 结构、包内后端生命周期和前端 ESM 入口检查通过。
- 周期与时钟测试覆盖：内核 / systemd 多条依据合并、结构化消息 ID（本地化文本）、重复完成、多周期、缺少边界、失败 / 取消、跨 Boot 隔离、单调时钟排除挂起时长、源时钟与接收延迟、实时时钟回退、缺少字段的估计 / 未知、前后相邻周期以及 1 / 5 / 10 分钟边界。
- 报告测试覆盖：摘要与未命中分类规则的原始上下文、Boot ID / 微秒时间戳、可靠 PCI 型号核对、未关联和无关内置盘 / 鼠标 / 游戏日志排除、凭据 / 序列号 / 路径脱敏、每份报告独立代号、2 MiB 上限、截断、权限 / 无日志 / 历史保留不确定提示。
- 导出测试覆盖：UTF-8、桌面用户所有权 / 权限、固定目录、无任意路径 / 内容参数、缓存编号 / 过期 / 无效请求、符号链接 / 目录冲突 / root 身份拒绝、文件写入失败清理。文件名冲突不能覆盖或删除已有报告。
- 前端交互检查使用测试专用 hooks / Decky 组件与 CEF 桩：范围切换、并发重复点击抑制、复制与缓存导出、实际路径显示、复制失败 / 超大拒绝 / 简短摘要、日志内容安全编码、焦点恢复、休眠周期筛选及“唤醒后约38秒”。既有监控和重新挂载交互检查继续通过。
- 当前容器实际调用生产 `Service.snapshot('boot')` 与 `generate_report('boot')`：外部设备 0、journal / 休眠状态 `no_logs`，返回包含限制的有效报告（原始日志 0）；桌面用户导出预检返回 `export_unavailable`，未写 root 或其他用户目录，未执行任何真实设备管理命令。
- `python3 scripts/check_release.py v0.3.0` 校验 package / lockfile 版本。安装包固定名称 `External-Storage-Guard.zip`，新增 Python 模块随白名单模块目录打包，测试桩不进入安装包。既有 v* Actions 发布流程不变，本功能提交自身不会创建正式版本标签。
- **待实机验证**：Steam Deck / Ally X 的真实 suspend / resume journal 字段、转发延迟和 RTC 校时；手柄与页面焦点；不同 Decky / Steam CEF 版本的实际剪贴板结果；`DECKY_USER` 与桌面 Downloads 导出权限、真实磁盘空间不足。CEF 复制使用官方 `executeInTab` 的适配，不是一个独立的 Decky 文本剪贴板 API；失败时提示 TXT，不宣称成功。
- 新诊断始终只读，不自动休眠、唤醒、卸载、重新挂载、重置或修复；时间相邻不能证明因果。既有手动重新挂载仍须确认，安全检查未放宽。

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
