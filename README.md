# External Storage Guard v0.3.0

SteamOS 游戏模式中的外部存储诊断 Decky 插件。适用于 Steam Deck、安装 SteamOS 的 ROG Ally X 等设备；界面为中文。v0.3.0 新增休眠与唤醒诊断、诊断报告复制和 TXT 导出，保留监控及需用户确认的安全重新挂载。

本项目实现了实际系统读取，没有内置演示数据、HTTP 服务或额外监听端口。**构建和自动化测试通过不等于已经通过实机验收**；ROG Ally X / Steam Deck 的 Decky 加载、手柄操作、真实读卡器与 USB 桥接兼容性仍需按下文验证。

## 功能与判断边界

- 自动列出可确认的原生 SD 卡、USB HDD / SSD 及分区，包括未挂载设备；显示容量、文件系统、所有可见挂载点与只读状态。
- 使用 `lsblk --json`、sysfs 拓扑和 `findmnt --json`；不凭 `sda`、`mmcblk0` 名称或单个 removable 标志判断。原生 SD 需要 sysfs `device/type=SD` 和 MMC host 拓扑；eMMC (`MMC`) 排除。USB 通过传输类型或 sysfs USB 拓扑确认。
- 排除内置 NVMe，以及承载 `/`、`/usr`、`/var`、`/home`、`/boot`、`/efi` 的磁盘（包括映射设备的父盘）。无法确认外置属性的磁盘不列出；已确认 USB 但无法判别 HDD / SSD 时显示“未知”。USB 的 HDD / SSD 分类依赖内核 ROTA 提示，不能保证识别硬盘盒内真实介质。
- 读取本次启动、最近 24 小时、最近 7 天、全部可用记录或上次启动的内核日志与限定的 systemd 休眠服务日志。使用 journalctl JSON 和结构化时间戳；历史范围不使用会隐含限制本次启动的 `-k`。诊断报告提供本次启动 / 24 小时 / 7 天 / 全部四种范围。
- 分类 MMC 调谐 / CRC / 初始化 / 缓存刷新、I/O、USB 重置 / 断开、SCSI / UAS、ext4 / exFAT / NTFS、实际只读重挂载等事件。按设备和严重程度筛选，时间倒序，点击查看原始日志；时间按设备本地时区显示。
- 严重：读写失败、缓存刷新失败、文件系统错误、内核拒绝离线设备 I/O、因错误切换只读。警告：调谐回退、重试 / 重置、CRC、超时；超时不自动宣称已恢复。信息：识别、正常挂载 / 卸载、USB 断开。
- **一条 `USB disconnect` 不能判断用户是否主动拔出，因此单独按信息展示；伴随的真实 I/O / offline 错误仍按严重展示。** 只读挂载也不自动当作故障。`errors=remount-ro` 是挂载策略；重复 Tuning failed 记录次数但不认定卡损坏；游戏 segfault 排除。

### 设备关联的保守策略

本次启动通过块设备 / 分区名、sysfs MMC 控制器、精确 USB 端口和 SCSI 地址关联。USB hub 下不同端口不混用，候选设备有歧义时不分配归属；不会根据时间相邻把鼠标或手柄的 USB reset 当作磁盘异常。

已拔出的块设备错误、无法确认身份的记录进入“未关联事件”，保留日志引用。历史中明确的 `usb-storage <端口>` / USB 存储驱动证据可以用于识别该端口断开前的存储事件；只有泛化 USB 枚举或断开记录、没有存储证据时不显示。缺少拓扑的历史 UAS 总线事件可能因此漏报，这是为避免无关外设误判而采用的限制。

**上次启动的记录不使用本次启动的设备名对应关系**，最近 24 小时也逐条检查 boot ID；历史存储异常通常列入未关联事件。对本次启动已观察到的重新 attach / disconnect 边界，较早世代的记录也不计入当前设备。这不是跨重启持久设备身份追踪；当前日志尾部缺失身份变更证据时，内核设备名仍存在复用风险。没有可确认外置身份的历史 NVMe 错误被排除。

没有异常记录不等于设备健康。计数仅针对当前时间范围内**返回的最近记录**，不是磁盘寿命计数或完整健康评估。

## 休眠与唤醒诊断（v0.3.0）

“休眠历史”按最近周期优先显示。识别内核 `PM: suspend entry`、`Freezing user space processes`、`PM: suspend exit`，并结合 systemd-suspend 等服务的结构化消息 ID 和日志进行配对。每次周期保留 Boot ID、开始 / 唤醒时间及原始依据。最多展示最近 100 个周期，每页 10 个；展开按时间顺序展示该周期的全部已返回依据和存储事件：休眠前 5 分钟、进入 / 恢复期间及唤醒后 10 分钟，每页 20 条。时间线引用当前最多 500 条分类事件，缺失 / 截断明确提示；完整的有界原始诊断消息可通过报告查看。

选择某次唤醒与 **1 / 5 / 10 分钟**，筛选该周期唤醒后的存储事件；错误 / 警告计数基于当前返回的最多 500 条分类事件。识别、读卡器初始化、USB 断连 / 重置及正常挂载信号另行计数。日志详情显示“唤醒后约 38 秒”等信息，区分休眠前、休眠期间无法确定、唤醒后及未知事件；同一事件可以既在上次唤醒后，又在下一次休眠前。MMC Cache Flush 失败、Cache Enable 失败、runtime suspend / resume 失败分别分类，优先于通用 CRC 类；重复 `Tuning failed` 保留每次记录。运行时电源管理失败不是一次新的系统休眠周期。仅在日志提供证据时显示设备重新识别、断开、重置或重新挂载，未出现不代表未发生。

每个 Boot ID 独立配对，绝不跨启动计算时间差。优先使用内核源单调时间戳，否则使用 journal 单调时间戳；缺失时才退回实时时钟并标为估计。**单调时钟通常不包含挂起时长，不能用其差值宣称实际休眠了多久。** 日历时间只代表日志时间；内核缓冲、日志接收延迟、校时和完成记录缺失均可能影响边界。内核退出不等同于用户空间完全恢复，只有内核退出记录时明确标记；无法配对或确定时间时保留缺失 / 未知状态，不补造记录。未捕获开始的唤醒仍会显示为不完整周期。

**时间相关不等于因果关系。** 唤醒后出现 SD / USB 错误不证明休眠导致故障。旧日志不足、无权限、没有休眠记录、读取截断均有独立提示；无异常不能作为健康证明。此区域只读，不会自动休眠、唤醒、重新挂载或重置设备。

## 复制诊断报告与导出 TXT（v0.3.0）

主界面“诊断报告”选择时间范围（默认本次启动），再点击 **复制诊断报告**、**复制简短摘要** 或 **导出 TXT 文件**。报告包含简短摘要、生成时间（UTC）、内核与可可靠识别的设备型号、当前外置盘和分区 / 挂载信息、原生 SD 读卡器 PCI ID / 驱动、可验证的读卡器名称、休眠周期、异常及相对唤醒时间、诊断限制，以及 **带 Boot ID 和原始微秒时间戳的脱敏原始 JSONL 消息**。不会只导出分类摘要；尚未命中分类规则的相关存储消息也保留，便于复核解析规则。

当前设备快照不代表历史设备身份。跨启动的异常、归属不确定的控制器 / USB / 分区事件保持“未关联”。原生 MMC 读卡器从 sysfs 确认 PCI 功能和驱动；可选 `lspci` 仅在地址与 PCI ID 都一致时补充型号名称，缺少工具、USB 读卡器或无法可靠识别时显示未知，不猜测芯片。

报告只选取外部存储相关内核消息和休眠依据，不收集整个系统 journal、游戏崩溃、无关 USB 外设或内置 SSD 日志。原始消息保留诊断内容与结构化时钟，但经过脱敏，**不是逐字节原始 journal 备份**。默认隐藏序列号、CID / WWN、UUID / PARTUUID、用户名、挂载路径、网络地址、URL 及常见密码 / 令牌字段；每份报告使用独立匿名代号。保留诊断所需的 `/dev/...`、本地 USB 端口、PCI 标识、设备型号和 Boot ID。隐藏项可能连同相邻文字一起被保守遮盖；规则不能保证识别所有私人信息，分享前仍应检查 TXT。没有关闭脱敏的选项，也不附带进程命令行、主机名或无关 journal 元数据。

复制通过官方 `@decky/api.executeInTab` 在 Loader 支持的 Steam CEF 页面执行受控的复制适配，并检查 CEF `execCommand('copy')` 返回值；日志内容以 JSON 数据编码，不能作为脚本执行。没有假定游戏模式支持 `navigator.clipboard`，也没有调用未经验证的 Steam 私有文本接口。Decky 当前公开 API 没有独立文本剪贴板方法，此适配依赖实际 CEF / Decky 版本：失败会明确提示改用 TXT；自动化检查不代替掌机验证。完整报告超过 **64 KiB（UTF-8）** 会拒绝复制并建议导出，绝不静默只复制一部分。简短摘要可单独复制。

TXT 保存到 Decky 确认的桌面用户目录：

```text
<桌面用户主目录>/Downloads/External-Storage-Guard/External-Storage-Guard-<UTC时间>-<随机值>.txt
```

界面显示实际保存路径。目录缺失时创建私有目录，文件 UTF-8、权限 `0600`，属于桌面用户；拒绝目录符号链接、覆盖已有文件、身份 / 目录所有者不符。不能确认 `DECKY_USER` 或桌面用户目录时明确失败，不回退 root 目录或外部盘。后端只接受已生成的脱敏报告编号，不接受前端任意路径或文本；最多缓存 2 份、有效 10 分钟，前端同范围最多复用 1 分钟。导出是用户明确请求的文件写入，不进行设备状态操作。

“全部可用记录”仍受读取和报告限制：普通范围最多最近 **6000** 条、7 天 / 全部最多 **12000** 条限定 journal 记录，stdout 上限 **8 MiB**、每条消息最多 **4096** 字符；报告上限 **2 MiB**（摘要部分最多 256 KiB），达到上限保留最近原始消息并明确报告截断和保留数量。跨启动顺序尽可能按实时时钟排列，同启动内优先单调时钟；系统时钟跳变时，跨启动先后不能保证精确。非持久 journal 可能只有当前启动；报告会提示历史可能缺失，不声称已覆盖整个选择时段。查询失败 / 权限不足时仍可给出已有设备快照和限制，不能把缺少日志解释为没有错误。

## 安全重新挂载（v0.2.0）

进入设备详情，在相应分区点击 **重新挂载**。弹窗会提示：正在运行的游戏可能受影响，必须先关闭使用设备的程序并等待写入完成；确认后才开始操作。操作期间按钮、刷新及时间范围切换禁用，避免重复点击。

允许操作的范围刻意保守：

- sysfs 确认 SD / USB 外部设备上的普通数据分区，不能是整盘；文件系统限 ext4、exFAT、NTFS / NTFS3。分区类型须为 Linux filesystem data / Microsoft basic data（含相应 MBR 0x83 / 0x07）。EFI、系统专用、交换、未知分区类型以及 FAT 分区只保留监控。
- 必须有文件系统 UUID、分区 PARTUUID、父盘 `diskseq`、分区号、匹配的主次设备号与完整 sysfs 拓扑。缺少这些信息、存在加密 / LVM / 映射或 holders 关系时拒绝操作。
- 目标分区须恰好有一个挂载点，且整台外部盘的可见挂载都在 `/run/media/`、`/media/` 或 `/mnt/` 下。其他路径、系统挂载、未挂载、多重挂载及使用中的交换空间均不允许。某些自定义挂载或桥接盒因此可能只能监控，界面显示具体原因。
- 承载 Decky 插件本体、homebrew 目录或插件运行数据的设备不允许重新挂载，避免操作期间卸载自身代码或记录目录。
- exFAT / NTFS 还须能从当前真实挂载选项明确取得数值 uid / gid；无法确认时（例如部分 FUSE 挂载）只支持监控，避免以 root 默认权限重挂后 Steam 无法访问存档。仅白名单保留数值 uid / gid / 权限掩码及 nosuid / nodev / noexec 标志，不接受前端提交的选项；挂载后验证这些要求。

后端从已扫描的合格分区签发有效期 120 秒的一次性授权。前端只提交授权令牌，不能直接指定磁盘路径、挂载参数或执行命令。执行时重新扫描，再比对连接序号、分区身份、容量、设备号、拓扑和原挂载信息；读取故障日志后再次检查；每个命令前还核对实际块设备文件和 sysfs，降低拔插、同名设备复用和过期页面造成的误操作风险。

执行顺序固定为 `udisksctl unmount -b <后端验证的分区> --no-user-interaction`，只有成功返回才继续验证卸载状态和身份，再执行 `udisksctl mount -b <同一分区> --no-user-interaction`。设备忙、权限不足或其他卸载失败立即停止，不调用 mount，不使用强制或懒卸载。卸载后若设备断开、身份变化或被其他程序重新挂载，也立即停止；不会操作新到达的同名设备。

**重新挂载不是文件系统修复。** 当前启动日志中针对该分区的 `emergency_ro`、journal aborted、filesystem check required / fsck 提示会在详情和确认框显示警告。原先只读或发现上述证据时，挂载命令只增加 `--options ro`，并验证结果；不尝试强制恢复可写。历史证据和有限日志均不能证明当前健康，`errors=remount-ro` 参数本身不作为错误证据。插件不调用 fsck、e2fsck、任何格式化 / 修复工具，也不重置 USB / PCIe 或修改内核参数。

结束后（成功、失败、超时等）重新扫描设备、挂载信息和本次启动的最新有限内核日志，页面切回本次启动，明确显示成功或失败、阶段与原始失败原因。若卸载成功后挂载失败，会保留失败状态并提示分区可能未挂载；不能据此继续运行原游戏。不会自动重试，也不提供对未挂载分区的单独“挂载”功能。UDisks 可能选择不同的挂载路径或默认挂载选项，操作后务必核对实际路径、只读状态与 Steam 库可用性。

操作记录仅写入 Decky 为此插件提供的运行目录 `$DECKY_PLUGIN_RUNTIME_DIR/remount-state.json`，不写入外部盘或全局系统配置。首次卸载前无法记录状态会拒绝执行；之后的记录写入失败会显示警告。关闭菜单或 RPC 取消不会故意中断进行中的卸载 / 挂载流程。Decky 强制终止、断电或实际拔盘仍可能中断操作：下次启动读取未完成记录，提示结果未确认并刷新真实状态，不自动补挂载。**操作期间不要拔盘、禁用、更新或卸载插件。** 用户空间逐步检查不能消除热拔插在命令交接间隙的所有竞态，也不能替代关闭游戏和重要存档备份。

### 重新挂载排查与独立操作审计

调用链为确认按钮 → `App.remount` → Decky `remount_partition(token)` → Python `Service.remount` → `Remounter.execute`；确认前不会调用设备操作，操作后的刷新用于获取真实状态。执行的是两条独立的非交互 UDisks 命令，不是 `mount -o remount` 或直接 `umount/mount`，也不会以单纯刷新代替设备操作。

成功要求两条命令都返回 0，且同一已核验分区的状态实际经历 **原挂载 → 无挂载 → 新挂载**，最后还要核验身份、只读状态及权限 / 安全选项。命令未执行、返回非 0、设备忙、挂载点没有消失、重新挂载后不可见或选项不符均不会提示成功。返回 0 之后但状态验证完成之前，只能视为命令完成，不能写成“已卸载”。**不以 EXT4 是否输出卸载 / 挂载消息判断成功**；日志读取仅用于故障警告及事后查看。

独立审计保存在 `$DECKY_PLUGIN_RUNTIME_DIR/remount-audit.json`，与只保存最后状态的 `remount-state.json` 分开。记录操作 ID、Boot ID、开始 / 结束时间、后端核验的目标、操作方式、各命令参数 / 返回码 / stdout / stderr、三阶段挂载证据和失败原因；每条输出最多 4096 字符并标识截断。超时等未取得返回码 / 输出时明确标记不可用，不伪造输出；`pending` 不证明命令已执行，`returned_zero` 也不代表整个操作成功。`running` 表示中断或未确认，不能认定成功。

审计使用私有 `0600` 文件、原子替换，保留最近 50 次操作且总计最多 512 KiB，超限淘汰最早记录并标识历史不完整。首个卸载命令前无法持久写入审计则拒绝操作；已卸载后审计写入失败会显示警告，仍尝试完成安全挂载及验证。旧版本没有记录的操作不能追溯。运行目录缺失、记录损坏或权限不足均明确报告，不悄悄覆盖损坏审计或改写全局权限。

“复制诊断报告”与 TXT 包含按所选 Boot / 时间范围筛选的脱敏审计，保留命令输出和状态证据。遇到“没有 EXT4 日志”时，先核对报告中的操作 ID、命令是否实际执行、返回码与三阶段状态，再判断是确认未送达、前置校验拒绝、设备忙、权限不足、卸载未生效、重新挂载失败还是缺少日志。仅凭当前现象无法确定设备上的具体失败环节。

## 安全、权限与性能

监控与报告只调用固定参数的 `lsblk`、`findmnt`、`journalctl`，报告可选查询 `lspci`，并读取 sysfs / boot ID / 有限系统型号信息；只有用户在确认弹窗确认后，设备管理 API 才会调用上述两种 `udisksctl` 操作。没有 shell 拼接、全局权限策略变更、`umount -l/-f` 或额外 HTTP 服务。

`plugin.json` 沿用 Decky 支持的 `root` 标志，使用 Decky 已有进程身份，让 UDisks / polkit 自行执行授权检查。`--no-user-interaction` 禁止弹出认证提示；授权不足、缺少 UDisks / `udisksctl` 或系统总线不可用时报告原因，不调用 sudo / pkexec、不改变用户组或 polkit 规则、不绕过认证。root 标志不保证所有 SteamOS / UDisks 配置都授权成功。

只在打开界面、手动刷新和确认操作后读取；没有后台轮询。普通读取在卸载时取消，正在执行的已确认事务尝试完成后退出，但 Decky 仍可能在其终止期限到达后强制停止，以上操作记录用于下次识别中断。

设备读取命令各有 8 秒超时，journal 查询为 12 秒，可选读卡器名称查询每个 2 秒、最多 8 个控制器；本次启动刷新最多三条核心命令；历史范围会额外读取本次启动日志以展示当前故障警告。UDisks 每步最多等待 20 秒且不重试，多次安全复核和最终刷新使单次操作最坏可能超过两分钟，通常快得多；前端异步等待，不阻塞游戏 UI。命令超时也不证明 UDisks 系统服务绝对没有完成操作，因此按结果未确认提示，以真实刷新状态为准。

监控 stdout 上限 8 MiB、stderr 上限 64 KiB；UDisks 输出上限 64 KiB；普通范围最多读取最新 6000 条、7 天 / 全部最多 12000 条限定 journal 记录，每条消息最多 4096 字符，返回最新 500 条匹配事件，前端每页 20 条。触及限制会提示不完整或报错。读取失败绝不显示为“设备正常”。

## 技术结构

参考官方 [decky-plugin-template](https://github.com/SteamDeckHomebrew/decky-plugin-template/tree/90d0780e882a17f5714fc6de044c645f22608290) 的 Rollup / TS 配置，并核对 Loader 的 API v1 实例化和 ZIP 安装实现。使用 `@decky/api` 的 `definePlugin` / `callable`，不使用旧版 `serverAPI.callPluginMethod`。

```text
main.py                     Decky API v1 与卸载生命周期
storage_guard/commands.py   有界、可取消的命令执行
storage_guard/devices.py    设备发现、sysfs、挂载状态与系统盘排除
storage_guard/journal.py    日志读取、时间范围和错误状态
storage_guard/rules.py      独立分类规则（纯函数）
storage_guard/events.py     关联、启动隔离、排序与数量限制（纯函数）
storage_guard/service.py    组合扫描、事件计数、报告缓存与结构化响应
storage_guard/suspend.py    Boot 隔离的周期配对、时钟语义及唤醒关联
storage_guard/report.py     摘要、脱敏、有界原始 JSONL 报告
storage_guard/hardware.py   只读系统型号与读卡器信息
storage_guard/export.py     桌面用户 Downloads 的安全 TXT 导出
src/clipboard.ts            Decky / Steam CEF 复制适配与大小限制
storage_guard/remount.py    一次性授权、分区资格、实时身份检查、UDisks 事务
storage_guard/operation_store.py Decky 插件运行目录中的原子操作记录
src/App.tsx                 按需请求、页面状态、筛选
src/components/             设备列表、设备详情、日志列表、读取状态
src/types.ts                设备、事件、响应结构
src/strings.ts              中文 UI 字符串、时间 / 容量格式
tests/                      独立测试数据和自动化测试；不会进入安装包
scripts/package.py          白名单式 Decky ZIP 打包
scripts/check_release.py    版本标签与 package / lock 版本一致性校验
.github/workflows/check.yml 类型检查、测试、构建与 ZIP artifact
.github/workflows/release.yml v* 标签自动构建、验证并发布 Release
```

后端无第三方 Python 依赖，需要 Python 3.10+（使用 Decky 的 Python 运行时）；前端 React 由 Steam / Decky 提供，不另行打包 React。开发依赖以 `package-lock.json` 固定，补充 `@types/react-router` 以满足当前 `@decky/api` 的类型引用。

## 开发与构建

需要 Node.js 22+、npm、Python 3.10+。

```bash
npm ci --ignore-scripts
npm run typecheck
npm test
npm run build
npm run package
```

`npm run package` 会先完整运行类型检查、测试和构建，再验证 ZIP 结构、在仓库外加载包内后端，以及用测试桩加载前端 ESM 入口（不等同于真实 Decky UI 测试）。生成固定名称的 `out/External-Storage-Guard.zip`。

普通分支 push / PR 运行检查工作流；推送 `v*` 标签运行独立的发布工作流。Actions 页面下载的 artifact 是 GitHub 外层容器 ZIP，需要先解压，取出其中的 `External-Storage-Guard.zip` 再安装。Release 资产中的同名 ZIP 可直接供 Decky 安装。

ZIP 中只有一个顶层目录：

```text
external-storage-guard/
  plugin.json
  package.json
  main.py
  storage_guard/*.py
  dist/index.js
  dist/index.js.map
  README.md
  LICENSE
```

不需要在掌机上执行 npm / pip 安装。`storage_guard` 随 ZIP 打包，后端显式加入插件目录到模块搜索路径；目录名与显示名称不同是正常情况。

## ROG Ally X + SteamOS 安装

1. 确保掌机运行 SteamOS 游戏模式并已安装可正常使用的当前 Decky Loader。本项目通过 GitHub Releases 分发，并非插件商店已收录插件。
2. 打开游戏模式快捷菜单 → Decky → 设置，启用开发者模式，进入开发者页面，选择 **Install Plugin from URL / 从 URL 安装插件**。
3. 粘贴以下安装直链，确认 Decky 安装提示。该地址指向最新正式 Release 的固定名称安装资产；预发布版本不替换 latest。

   ```text
   https://github.com/ohxiaoguang/decky-external-storage-guard/releases/latest/download/External-Storage-Guard.zip
   ```

4. 在 Decky 插件列表打开 **External Storage Guard**。第一次打开会显示加载状态，然后显示真实设备和内核日志状态。默认是本次启动。
5. 检查设备与日志后，用插件内的刷新按钮重新读取；关闭插件菜单不会产生持续轮询。卸载通过 Decky 的插件管理完成。

[下载最新安装包](https://github.com/ohxiaoguang/decky-external-storage-guard/releases/latest/download/External-Storage-Guard.zip) · [查看所有 Release](https://github.com/ohxiaoguang/decky-external-storage-guard/releases)

固定版本安装地址为 `https://github.com/ohxiaoguang/decky-external-storage-guard/releases/download/v0.3.0/External-Storage-Guard.zip`（替换版本标签可安装其他版本）。直链需要相应 Release 已成功发布并附带安装资产；返回 404 时先检查 Release / Actions 页面。

也可将下载或本地构建的 `External-Storage-Guard.zip` 放入掌机 Downloads，再通过 **Install Plugin from ZIP File / 从 ZIP 文件安装插件** 安装。**不要使用 GitHub 自动生成的 Source code (zip) / Source code (tar.gz)**；源码归档没有编译后的 `dist/index.js`，不能代替插件安装包。

## 自动发布与手动后备方式

`.github/workflows/release.yml` 在推送 `v*` 标签时执行：校验标签版本 → `npm ci --ignore-scripts` → 类型检查和全部单元测试 → Rollup 编译 → 白名单打包和 ZIP / 隔离加载验证 → 生成 SHA-256 → 上传构建 artifact → 发布任务校验下载包的 SHA-256 → 上传固定名资产并公开 GitHub Release。构建 / 测试失败不会进入发布任务，上传失败不会将新建草稿公开。

构建任务只有 `contents: read`，发布任务使用 GitHub 自动提供的 `GITHUB_TOKEN` 和 `contents: write`，无需额外 PAT。正式标签发布为 latest，含连字符的预发布标签发布为 prerelease；标签与 `package.json`、`package-lock.json` 必须完全一致。重跑同一标签的工作流会复用 Release 并重新上传资产，不创建第二个 Release。

当前版本的标签命令示例（发布流程必须已提交到该标签所指提交）：

```bash
python3 scripts/check_release.py v0.3.0
git tag -a v0.3.0 -m "External Storage Guard v0.3.0"
git push origin v0.3.0
```

后续发版先用 `npm version <新版本> --no-git-tag-version` 同步 package 与 lockfile 并提交，再推送对应的 `v<新版本>` 标签；不要移动已有发布标签。版本不匹配时查看 Actions 的 **Check tag and package versions** 步骤。

如果发布失败，查看 [Actions](https://github.com/ohxiaoguang/decky-external-storage-guard/actions) 对应标签的失败任务：

- `Resource not accessible by integration` / HTTP 403：仓库或组织策略限制了 Actions 的 Release 写权限；由仓库管理员检查 Actions 是否启用、工作流权限及允许的 action 策略，之后重跑失败任务。这里的 `GITHUB_TOKEN` 属于 GitHub runner，与本地开发环境的网络或 CLI 权限不同。
- runner 未启动、计费额度或 Actions 被禁用：工作流无法执行；先解决 GitHub 给出的具体原因，或采用以下本地构建和网页上传方式。
- 依赖安装、测试或 ZIP 验证失败：先修复失败项，再创建新版本标签；不要跳过验证发布源码 ZIP。

无法使用 Actions 时，手动发布步骤：

1. 检出计划发布的标签，在该提交运行 `npm ci --ignore-scripts`、`python3 scripts/check_release.py v0.3.0` 和 `npm run package`（其他版本替换标签）。全部成功后得到 `out/External-Storage-Guard.zip`。
2. 在 GitHub 仓库 **Releases → Draft a new release**，选择同一标签，上传上述 ZIP 作为独立 Release 资产，文件名保持 **External-Storage-Guard.zip**。正式版发布并标记为 latest；预发布勾选 prerelease。
3. 检查 Release 页面存在该资产，打开上面的 `latest/download` 直链并下载验证。不要选择页面自动附带的 Source code ZIP。

已在本机授权 GitHub CLI 的维护者也可执行以下命令（不能用它绕过组织策略）：

```bash
gh release create v0.2.0 out/External-Storage-Guard.zip --verify-tag --title "External Storage Guard v0.2.0" --generate-notes --latest
```

若 Release 已存在，使用 `gh release upload v0.2.0 out/External-Storage-Guard.zip --clobber` 补传资产，并在网页确认它不是草稿且是所需的 latest 正式版。

## 实机验收清单

以下行为需要在真实掌机上验证；自动化测试使用的 fixture 不会出现在生产代码或安装包里。

1. **只有内置 SSD**：打开插件，确认 NVMe 不显示为外部设备。设备列表为空和日志读取失败是独立的状态。
2. **ROG Ally X 的 MicroSD**：插入现有 SD 卡，打开插件或刷新；确认 `/dev/mmcblk0`（设备名以实机为准）、SD 类型、约 477 GiB（512GB 标称卡）、ext4、真实挂载路径和只读状态。确认未挂载卡也列出。
3. **原始问题记录**：在记录仍被系统保留的时间范围，查看 `mmc0` 错误；Tuning failed 为警告，Cache Flush bit 失败与 I/O error 为严重，正常识别 / 挂载为信息。缺少 attach / 拓扑证据的早期初始化错误允许列为未关联事件，不强行认定属于当前卡。
4. **多个 USB 存储**：同时连接现有 USB HDD / SSD，确认分别列出，挂载路径与分区不混淆；接入鼠标 / 手柄，确认其 reset 不增加硬盘异常。部分桥接盒报告的 ROTA 不可靠，应记录实际型号用于后续兼容性调整。
5. **设备变化**：先用 SteamOS 自带的安全移除功能停止设备使用，再断开并刷新，确认插件不崩溃、不保留假在线设备。不要为了测试故障在写入中拔盘；I/O 故障通过本项目 fixture 验证即可。
6. **筛选和手柄**：用方向键 / A / B 操作设备按钮、返回、时间 / 严重级别下拉、原始日志展开及多页日志，确认焦点与滚动可用；检查显示时间与 SteamOS 本地时间一致。
7. **历史和不可用状态**：选择最近 24 小时与上次启动；没有持久日志应明确提示没有历史；权限不足应明确提示而非显示正常。不需要为验收去改系统权限；权限失败已有单元测试。
8. **生命周期**：刷新后关闭菜单再重开，应重新读取；卸载后没有插件轮询、定时任务或尚存命令进程。

v0.2.0 设备管理还需在备份好数据、关闭游戏的条件下验证：

1. 在正常 SD / USB 数据分区的详情页确认按钮资格；对内置盘、整盘、EFI、交换、未挂载或身份不足分区确认无可用操作按钮。
2. 打开确认框后先取消，确认挂载状态不变；再在关闭所有使用设备的程序后确认，核对操作中禁用、成功提示、新挂载路径与日志刷新；连续点击不应发出第二次操作。
3. 仅在可丢弃的测试介质上，用终端工作目录或打开文件保持普通 busy 状态，确认安全卸载失败后立即停止且没有强制卸载；退出该程序后再试。不要在写入存档时试验。
4. 权限不足、挂载失败、移除 / 换盘、紧急只读、journal aborted、检查需求和强制终止场景已由模拟测试覆盖。不要为了实机验收故意损坏文件系统或在操作中拔盘；遇到真实故障时确认警告、只读策略、失败状态和原始原因，后续检查交由系统工具处理。
5. 使用手柄核对确认 / 取消、灰色按钮及原因、操作结果和长日志滚动。关闭菜单后重开应读回最后操作记录；中断记录只提示核对状态，不自动再执行。

## 排错与可选只读诊断

- 不显示设备：确认它是 SD 或 USB 外部设备且仍被内核识别。内置 NVMe、eMMC、仅有 removable 标志而无总线证据的设备不会列出。可在桌面终端用下面只读命令核对，不需要修改或修复磁盘。
- 权限不足：确认运行的 Decky 版本支持 `root` 标志，以及其后端自身拥有读取日志的权限。不要为本插件修改 journald 或用户组、输入 sudo 密码。保留界面错误信息供排查。
- 无日志 / 无历史：内核日志可能未被 journald 收集、当前环境没有 journal 或没有持久化上次启动。插件不会自动开启持久化。日志读取成功但没有匹配异常会显示“已读取的日志中未发现严重或警告事件”，这与日志不可用不同。
- 读取超时 / 超上限：手动重试并缩短时间范围；结果有截断提示时，统计仅覆盖有限记录。
- 重新挂载按钮灰色：查看分区下方原因。缺少 UUID / PARTUUID / diskseq、未知分区类型、多挂载、非支持挂载目录、映射 / swap 均只支持监控，不应通过修改策略强行启用。
- 操作显示设备忙：关闭使用设备的游戏、终端和文件管理器，确认写入结束后刷新并重新确认；插件不会强制卸载。
- 卸载后挂载失败 / 中断 / 结果未确认：先刷新核对是否仍挂载和只读；停止依赖该设备的程序，保留错误原因。可由 SteamOS 自带存储管理处理，插件不自动重试或修复，也不会自动执行 fsck。
- 加载失败 / 通信失败：核对安装包目录层级、`dist/index.js`、`storage_guard`、`api_version: 1` 和当前 Decky 版本；使用 Decky 的日志页面或下面服务日志定位，不使用独立 HTTP 服务。

```bash
lsblk --json --bytes --tree --output NAME,KNAME,PATH,TYPE,SIZE,MODEL,TRAN,RM,RO,ROTA,FSTYPE,MOUNTPOINTS,MAJ:MIN,UUID,PARTUUID,PARTTYPE
findmnt --json --list --output SOURCE,TARGET,FSTYPE,OPTIONS,MAJ:MIN
readlink -f /sys/class/block/mmcblk0
cat /sys/class/block/mmcblk0/device/type
journalctl -k -b 0 --no-pager -n 100
journalctl -u plugin_loader --no-pager -n 100
```

上述命令遇到权限不足时直接报告即可，无需提权。对外分享原始日志前自行检查路径、设备标识等个人信息。

## 验证范围与后续功能

自动化覆盖：用户提供的真实 MMC 日志；USB、SCSI / UAS、文件系统、重复计数；设备类型 / 拓扑与系统盘排除；未挂载、多挂载、只读；启动隔离、名称复用边界与未知关联；权限不足、无历史、无日志、格式错误；缺少命令、超时、输出上限、卸载取消；Decky 后端入口实例化及 JSON 响应。

设备管理测试补充：合格 SD / USB 分区，整盘 / 系统拓扑 / EFI / swap / 映射阻止，任意前端路径拒绝，过期 / 已用授权、重复请求，UUID / 设备号 / diskseq / 挂载点变化，真实块文件类型检查、swap 文件占用，卸载失败不继续，卸载后掉线 / 换盘 / 自动挂载，挂载失败及验证失败，故障证据与保留只读，操作记录及中断恢复。前端打包测试使用测试专用 hooks / Decky 桩验证确认、取消、重复点击、操作中禁用和刷新后的失败状态，不等同于 SteamOS 手柄测试。

非 SteamOS 开发环境可以直接运行以上测试和构建，不模拟健康设备展示。真实硬件兼容性、Decky 运行时 UI 和手柄交互需实机验收。版本对应的实际验证结果见交付时的验证报告。

v0.2.0 仅新增安全重新挂载；安全弹出、设备重置 / 重新扫描、修复、SMART、压力测试、常驻通知和自动恢复不在本次范围。
