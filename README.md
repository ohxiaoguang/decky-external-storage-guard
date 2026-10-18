# External Storage Guard v0.4.0

SteamOS 游戏模式的 MicroSD / USB 存储诊断 Decky 插件，中文界面。支持原始日志诊断、休眠唤醒关联、脱敏报告与用户确认后的安全重新挂载。构建通过不代表已完成 Steam Deck / Ally X 实机验收。

## 界面

主页只显示设备名称、容量、文件系统、当前挂载及读写状态、本次开机的错误 / 警告记录数、最近 5 条存储异常和最近一次休眠 / 唤醒时间。选中设备后出现“重新挂载”“复制诊断报告”；“查看详情”进入设备信息、内核异常日志、休眠历史或报告 / TXT 页面。Boot ID、路径、原始消息和筛选器保留在详情中。

“最近操作”只显示当前会话的操作中、成功、失败及简短原因。错误计数是**历史日志记录数**，不等同于当前文件系统状态，也不是健康评估。没有日志、没有异常或日志截断均不能证明设备正常。

主页最底部“插件更新”只显示从 `package.json` 构建元数据读取的当前版本，以及“复制更新链接”按钮。复用现有 Decky 剪贴板适配，复制成功 / 失败均有简短提示；不下载、不自动更新。固定链接无需随版本更换。

全部交互使用官方 `@decky/ui` 的按钮、下拉框和确认弹窗，未引入独立 UI 框架。手柄焦点和实际 Steam CEF 复制能力仍需实机验证。

## 监控与设备关联

- 用固定参数的 `lsblk --json`、`findmnt --json`、sysfs 拓扑和 boot ID 识别可确认的原生 SD、USB HDD / SSD 与分区。不凭设备名或单个 removable 标志判断外置属性；USB 介质类型提示可能不准确。
- 排除内置 NVMe、eMMC，以及承载系统目录的磁盘和映射父盘。无法确认身份或存在关联歧义的事件保持“未关联”，不会根据时间相邻强行分配。
- 分类 MMC 调谐 / CRC / Cache Flush / Cache Enable、runtime suspend / resume、I/O、USB 断连 / 重置 / 超时、SCSI / UAS、ext4 / exFAT / NTFS 与只读故障。单独 USB disconnect 不能证明意外拔出；`errors=remount-ro` 仅是策略，不能当作已发生只读重挂载。
- 每个启动周期独立关联，历史启动不套用当前设备名映射；在可观察到的 attach / disconnect 边界处避免同名设备复用。历史保留不足时仍不能完全排除复用风险。
- 只在打开、刷新、生成报告和明确设备操作后读取，没有后台轮询、HTTP 服务或额外监听端口。

## 重新挂载：依据真实状态，不依赖 EXT4 日志

在主页选中设备，点击分区的“重新挂载”。弹窗提示先关闭使用设备的游戏 / 程序并等待写入结束；确认才调用 Python 后端。操作期间禁止重复请求。

调用链为 `RemountControls` → `App.remount` → Decky `remount_partition(token)` → `Service.remount` → `Remounter.execute`。执行两条独立的非交互 UDisks 命令：

```text
udisksctl unmount -b <后端核验的分区> --no-user-interaction
udisksctl mount -b <同一分区> --no-user-interaction [--options <白名单选项>]
```

不是 `mount -o remount` 或单纯刷新。只有两条命令均返回 0，且同一分区的状态实际经历 **原挂载 → 无挂载 → 新挂载**、身份和最终选项核验通过，才返回成功。stdout / stderr 与返回码留在当前会话的最近结果中，完整诊断报告可供技术人员核对；不要求内核生成 EXT4 挂载消息。卸载不生效、设备忙、权限不足、掉线、超时、重新挂载后不可见或选项不符都不能提示成功。

安全约束保持：

- 仅允许 sysfs 确认的 SD / USB 普通数据分区，文件系统限 ext4 / exFAT / NTFS / NTFS3，分区类型须为 Linux filesystem data 或 Microsoft basic data（含 MBR 0x83 / 0x07）。整盘、EFI、swap、未知类型和 FAT 仅监控。
- 必须有 UUID、PARTUUID、父盘 diskseq、匹配的主次设备号、分区号和完整拓扑；系统盘、映射 / holders、交换空间、Decky 自身及运行目录所在盘均拒绝操作。
- 分区须恰好一个挂载点，整台外部盘可见挂载须处于 `/run/media/`、`/media/` 或 `/mnt/`。非 Linux 文件系统须可确认数值 uid / gid；只保留白名单权限与安全标志，不能确认时拒绝。
- 前端只提交后端签发的 120 秒一次性授权，不能传任意路径或参数。执行时多次重扫、比对身份 / 挂载 / diskseq，命令前再次检查实际块设备与 sysfs。
- 卸载失败立即停止，不执行 mount；卸载后身份变化、重新自动挂载或设备断开也停止。无强制卸载、懒卸载、认证绕过、全局 polkit / 用户组更改、设备重置或内核参数修改。UDisks / polkit 按现有权限授权，插件不调用 sudo / pkexec。

### 历史文件系统错误与当前只读状态

曾经出现的 `journal aborted`、`filesystem check required`、`emergency_ro` 日志只保留为故障证据，**不再直接决定之后每次挂载必须只读**。若之后观察到正常挂载，会标注历史记录；没有后续依据时明确“当前是否仍异常无法仅凭历史日志确认”。后续挂载也不能证明 e2fsck 已修复，插件不会伪造“已修复”结论。

当前块设备只读、实际挂载只读或实时挂载选项 `emergency_ro` 会保留 `ro` 并验证结果。不请求 `rw`，不尝试解除任何只读 / 文件系统保护。普通挂载仍由 UDisks 和文件系统驱动决定是否允许，挂载后若变为只读会警告。重新挂载不是修复，不自动执行 fsck / e2fsck、格式化或其他修复。

### 会话结果与中断

v0.4.0 删除 `operation_store.py`，不再生成、读取或更新 `remount-state.json` / `remount-audit.json`，也没有持久化操作历史页面。只在内存保留最近一次结果，下次操作覆盖，重启插件即丢失；旧版本已有文件不会被读取，可自行删除。系统挂载和错误事件继续从 journal 读取，不重复保存。

RPC 等待使用 `asyncio.shield`，关闭前端或取消请求不会取消正在进行的事务；插件卸载会等待事务，卸载等待请求自身被取消也不会向事务传播取消。发生不可恢复的取消 / 异常时，本次会话明确保留“结果不确定”，绝不自动重试。

**进程被 Decky 强制终止、关机、断电或实际拔盘仍无法保证事务完成。** 移除持久化后无法在重启时恢复上次操作记录；必须刷新真实挂载状态核对。操作期间不要拔盘、更新、禁用或卸载插件。用户空间核验不能消除物理拔插的全部竞态，使用前备份重要存档。

## 休眠与唤醒诊断

详情中的“休眠历史”结合 `PM: suspend entry`、`Freezing user space processes`、`PM: suspend exit`、systemd 休眠服务及结构化消息 ID，按 Boot ID 配对。支持唤醒后 1 / 5 / 10 分钟异常筛选；周期时间线展示休眠前 5 分钟、进入 / 恢复期间与唤醒后 10 分钟的已返回事件，每页 20 条，最多最近 100 个周期。

优先内核源单调时间，其次 journal 单调时间，缺失才使用实时时钟并标为估计。CLOCK_MONOTONIC 通常不包含挂起时长，不能把它的差值当实际休眠时长；日志缓冲、转发延迟、校时和缺失边界均可能造成歧义。只有内核退出不能证明用户空间恢复已完成。未知时间不补造，跨启动不计算时间差。

MMC Cache Flush / Cache Enable / runtime suspend / resume 失败分别分类，重复 Tuning failed 逐条保留；运行时电源事件不是一次新的系统休眠。时间相邻不等于因果，不自动唤醒、重挂载、重置读卡器或修复。

## 诊断报告与 TXT

主页复制默认本次开机完整报告；详情支持本次开机、24 小时、7 天、全部可用记录，以及复制简短摘要 / 导出 TXT。报告分开列出内核诊断日志和当前会话最近一次主动操作结果，不生成操作历史文件。操作完成或刷新后不会复用旧的前端报告缓存。

包含系统内核 / 可可靠识别的设备型号、当前盘 / 分区 / 挂载、原生 SD 控制器 PCI ID / 驱动、可验证型号、休眠时间线、原始 Boot ID / 微秒时间戳、异常关联和诊断限制。原生读卡器信息来自 sysfs；可选 `lspci` 只在地址与 PCI ID 一致时补充名称，未知不猜测。报告原始 JSONL 保留相关且未命中分类规则的存储上下文，不只导出摘要；不采集整个系统 journal、无关游戏崩溃或普通鼠标日志。

默认脱敏序列号 / CID / WWN、UUID、用户名、挂载路径、网络地址、URL 和常见凭据；保留诊断所需的设备路径、PCI ID、本地总线端口及 Boot ID。没有无脱敏模式；消息可能被保守遮盖，也无法保证识别一切私人信息，分享前仍需检查。脱敏原始消息不是逐字节 journal 备份。

复制通过官方 `@decky/api.executeInTab` 在 Loader 支持的 Steam CEF 页面执行受控复制并检查返回值，不依赖 `navigator.clipboard`。CEF / Decky 版本可能影响成功率，失败会明确提示。完整报告超过 64 KiB UTF-8 则拒绝复制并建议详情导出 TXT，不静默截断；更新链接复用同一适配。

TXT 保存到已确认的 Decky 桌面用户：

```text
<桌面用户主目录>/Downloads/External-Storage-Guard/External-Storage-Guard-<UTC时间>-<随机值>.txt
```

显示实际路径，文件 UTF-8 / 0600、属于桌面用户；拒绝目录符号链接、覆盖、身份不符、root 回退和任意前端路径。仅用户明确选择导出才写 TXT。后端缓存最多 2 份脱敏报告、有效 10 分钟；前端相同快照 / 范围最多复用 1 分钟。

## 读取限制与权限

`plugin.json` 沿用 Decky 的 root 标志，授权仍由系统检查；不能保证每个 SteamOS 配置都允许 UDisks 操作。后端无第三方 Python 依赖，使用 Decky Python 3.10+；前端 React 由 Steam / Decky 提供。

设备查询各 8 秒、journal 12 秒，可选 `lspci` 每个控制器 2 秒、最多 8 个；UDisks 每步 20 秒，不重试。多次验证可能使操作较久，前端异步等待。超时不证明系统服务未完成，应核对真实状态。

journal stdout 上限 8 MiB、stderr 64 KiB，普通范围最多 6000 条、7 天 / 全部最多 12000 条限定记录，每条消息最多 4096 字符。返回最多 500 条分类事件；报告最多 2 MiB、摘要部分最多 256 KiB，超限保留最近原始消息并明确标记截断。非持久 journal / 轮转可能使历史缺失，“全部可用记录”仍不是无限历史；RTC 回退时跨启动顺序不保证精确。

## 安装、更新与发布

游戏模式快捷菜单 → Decky 设置 → 开发者模式 → **Install Plugin from URL**，粘贴固定直链：

```text
https://github.com/ohxiaoguang/decky-external-storage-guard/releases/latest/download/External-Storage-Guard.zip
```

[下载最新安装包](https://github.com/ohxiaoguang/decky-external-storage-guard/releases/latest/download/External-Storage-Guard.zip) · [所有 Release](https://github.com/ohxiaoguang/decky-external-storage-guard/releases)

最新直链只随正式 Release 更新，预发布不会替换 latest。需要相应 Release 发布成功后才能下载新版本。也可使用 Decky **Install Plugin from ZIP File**。不要安装 GitHub 自动生成的 Source code ZIP / tar.gz，它没有编译的插件入口。

开发需要 Node.js 22+、npm 和 Python 3.10+：

```bash
npm ci --ignore-scripts
npm run package
```

该命令运行严格 TypeScript、Python 测试、Rollup 和包内隔离 / 交互检查，输出 `out/External-Storage-Guard.zip`。ZIP 顶层是单个 `external-storage-guard/`，包含 `dist/index.js`、`plugin.json`、`package.json`、`main.py`、Python 模块、README / LICENSE，不包含测试、node_modules 或操作历史。

普通 push / PR 自动检查并上传 artifact，Actions artifact 是外层 ZIP，须解压取出其中固定文件名的安装 ZIP。`.github/workflows/release.yml` 的 `v*` 标签流程核对 package / lock 版本、安装依赖、完整测试 / 编译 / 打包、生成 SHA-256，然后用 GitHub Actions 的 `GITHUB_TOKEN` 发布固定名 ZIP 与校验文件，测试失败不会发布。

合并并确认发布时使用：

```bash
python3 scripts/check_release.py v0.4.0
git tag -a v0.4.0 -m "External Storage Guard v0.4.0"
git push origin v0.4.0
```

后续用 `npm version <版本> --no-git-tag-version` 同步 package / lock 并提交后再标记，不移动已发布标签。若 Actions 未运行、额度不足或权限策略导致发布 403，先查看具体失败步骤；可手动执行 `npm ci --ignore-scripts && npm run package`，在仓库 Releases 创建匹配标签版本，上传 `out/External-Storage-Guard.zip` 及 SHA-256，勿上传源码 ZIP 代替。

## SteamOS 实机验收

1. 备份存档，安装测试 ZIP。用手柄确认主页无复杂筛选、Boot ID 或拓扑；设备名称 / 容量 / 文件系统 / 挂载 / 读写状态正确，选中设备才出现操作按钮；“查看详情”可进入全部诊断，返回主页恢复本次开机范围。
2. 在终端只读核对 `lsblk -f` 与 `findmnt -rn -S /dev/<实际外部分区> -o TARGET,FSTYPE,OPTIONS`。不要复制示例路径盲目操作；先确认并关闭该设备上的全部游戏 / 程序。
3. 确认重新挂载，核对 UI 结果和终端的最终路径 / 读写状态，复制报告检查命令返回码及三阶段证据。即使 `journalctl -k` 没有 EXT4 挂载消息，实际验证通过也应成功；结果可能是 UDisks 选择的新路径，须检查 Steam 库可用性。
4. 用无重要数据的测试介质验证 busy 安全失败，例如终端切换工作目录到该挂载目录并保持占用后发起操作；应停止且不强制卸载。退出占用再刷新、重新确认。内置 SSD、系统目录、过期授权或身份变更仍须拒绝。
5. 使用已有“曾报错、后经人工维修且当前正常挂载”的测试介质核对：旧日志仍可查看，但不会仅因旧 journal aborted 强制 ro；实际只读设备仍须保持 ro。不要为了测试制造损坏，也不要在挂载中的文件系统上运行 e2fsck。
6. 操作期间关闭 Decky 菜单后重新打开，等待后台完成，核对最近结果。只在可牺牲测试介质上验证插件卸载等待；不要在重要介质上测试断电 / 强杀。新会话不恢复旧结果，应以实时状态为准；不能把“无会话记录”视为上次成功。
7. 用手柄验证更新链接复制，切到可信文本输入框粘贴核对固定 ZIP 地址及版本号；模拟不可用 CEF 时应有失败提示，无自动下载。详情测试简短摘要、完整报告超限与 TXT 实际目录权限、隐私脱敏。
8. 在空闲设备上正常休眠 / 唤醒，核对真实 PM / systemd 日志、时间线及 MMC 错误分类。不能把时间相关认定为因果。记录掌机型号、SteamOS / Decky 版本、手柄焦点、CEF 复制及权限差异；当前容器未验证这些实机行为。
