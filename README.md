# External Storage Guard v0.5.0

SteamOS 游戏模式中的单层 Decky 外部存储工具。显示 MicroSD、USB 移动 SSD / HDD，提供独立的安全“卸载”“挂载”，以及一个原始系统日志弹窗。不显示内置系统 SSD。

## 界面与使用

打开插件后自动读取一次设备，可手动“刷新”，没有后台轮询或监控开关。每台设备分别显示名称、容量；每个分区显示名称、容量、当前挂载及读写状态，并拥有自己的“卸载”“挂载”按钮。多个分区不会合并成整盘操作。未挂载且块设备未标记只读时，显示“读写状态待挂载确认”，不猜测挂载后的状态。

已挂载分区可卸载，未挂载分区可挂载；不合格分区的按钮禁用并显示原因。卸载确认前应关闭相关游戏 / 程序、等待写入完成。卸载成功保持未挂载，绝不自动挂载。卸载不代表 USB 已断电，也不是物理安全弹出。

页面底部只有“查看日志”和“复制更新链接”。没有详情页、统计、等级、筛选、休眠关联、操作历史或报告导出。操作结果只留在当前后端会话，显示成功、失败或不确定及原因。操作后原位更新同一设备 / 分区组件；失败、通信或读取异常不销毁整页或丢弃已有设备列表。

## 两种操作与安全验证

API 分别是 `unmount_partition(token)` 和 `mount_partition(token)`。前端只传后端签发的、不含路径的一次性授权，不接受任意 `/dev` 路径。授权绑定动作、分区身份和原始挂载状态，有效期 120 秒；刷新或操作后重新签发，重复或过期请求拒绝。

卸载只执行：

```text
udisksctl unmount -b <后端验证的具体分区> --no-user-interaction
```

返回码必须为 0，并重新扫描，确认同一身份的分区不再有挂载点，才返回成功。设备忙直接提示“设备正在使用”；卸载失败不执行挂载，不使用 force / lazy / 强制中断文件系统，也不关闭设备电源。

挂载只执行：

```text
udisksctl mount -b <后端验证的具体分区> --no-user-interaction [--options <后端白名单选项>]
```

命令前确认未挂载；返回码为 0 后仍须重新扫描、验证同一设备身份、真实挂载点和权限 / 只读选项。确认后才返回成功，并显示实际路径与读写状态。仅启动命令、返回 0、刷新前端或出现某条 EXT4 消息，都不足以判定成功。命令超时、输出过量、返回 0 但没有实际状态变化、验证阶段掉线或身份变化都显示“不确定”。返回非 0 保留真实失败原因。

保留的安全机制包括：

- 通过传输类型、sysfs SD / USB 拓扑确认外置属性；排除 eMMC、内置 NVMe、承载系统目录的设备及映射父盘，不能凭名称或 removable 标志判断。
- 仅操作普通数据分区，不操作整盘、EFI、交换分区、加密 / LVM / holders 或未知类型。支持 ext4、exFAT、NTFS / NTFS3；分区类型须为 Linux filesystem data / Microsoft basic data，或对应 MBR 0x83 / 0x07。FAT 等其他文件系统仅显示，不启用操作。
- 要求 UUID、PARTUUID、diskseq、主次设备号、分区号和完整拓扑。命令前重扫，逐项比对身份 / 挂载，并检查实际块设备文件、sysfs 和交换空间；替换 / 同名复用后停止。
- 已挂载目标需要恰好一个挂载点。整台盘可见挂载须在 `/run/media/`、`/media/`、`/mnt/` 下；系统目录、自定义不受支持的目录和承载 Decky / 插件运行数据的盘拒绝操作。
- 当前块设备只读、挂载只读或实时 `emergency_ro` 受到保护；不请求 `rw`，不绕过文件系统驱动保护。同一会话 / 同一连接内，已验证卸载前的只读和白名单权限会用于之后挂载；exFAT / NTFS 保留已确认 uid / gid / 掩码等。首次挂载未挂载的非 Linux 分区时，必须可靠确认 Decky 桌面用户，使用其数值 uid / gid，不能静默以 root 默认权限挂载。
- 不根据旧 journal aborted 等历史记录永久强制只读，也不据此声称已修复；实际挂载保护由当前设备、UDisks 和文件系统执行。不运行 fsck、e2fsck、格式化、设备重置或系统配置修改。

插件沿用 Decky root 运行标志，但 UDisks / polkit 自行检查授权。`--no-user-interaction` 禁止交互认证；权限不足时失败，不调用 sudo / pkexec，不改组或全局权限策略。挂载路径可能由 UDisks 改变，须核对 Steam 库是否仍可用。

## 原始日志弹窗

“查看日志”使用 Decky 官方 ModalRoot、按钮和可聚焦滚动区，尽量使用屏幕空间。仅有刷新 / 复制 / 关闭、必要的读取 / 截断反馈和可滚动换行原文。B 关闭；滚动区支持方向键 / 手柄方向和键盘翻页。真实手柄焦点及全屏尺寸仍需目标 Steam / Decky 版本验证。

固定读取本次启动 `journalctl --output=json --boot=0`，范围为内核、systemd suspend / hibernate 等服务、systemd-sleep 和 udisks2 / udisksd，不只使用 `journalctl -k`。从内核记录中保留 MMC / SDHCI、USB / UAS / SCSI、I/O、EXT4 / exFAT / NTFS、挂载、设备连接断开及 PM / freezing 等关键词消息；服务范围保留原文。USB 上下文可能包含其他外设，工具不再进行设备归因。

每条显示 journal 实际提供的来源字段、Boot ID、原始 `__REALTIME_TIMESTAMP`（epoch 微秒）、`__MONOTONIC_TIMESTAMP` 及可用源时间戳，再显示未经翻译 / 解释的 MESSAGE。按本次启动 journal 单调时间、再按实时时间升序排列；没有时间戳时不补造。MESSAGE 换行保留，二进制消息保留 journal 数组表示。没有分级、统计、健康结论、休眠周期配对或错误“中文解释”。

查询最多最近 **2000 条范围内记录**，10 秒超时，命令 stdout 上限 **4 MiB**、stderr 64 KiB；显示最多 **48 KiB UTF-8**，保留完整消息，不切断一条消息后假装完整。达到条数 / 文本上限或跳过无法表示的消息时持续标注“日志已截断”。如果命令输出超过上限无法解析完整 JSON，明确提示读取截断，不制造部分日志。范围中的无关内核消息也计入查询尾部上限，不能保证覆盖整次开机。

复制直接复制弹窗当时显示的**全部文本**，复用官方 `@decky/api.executeInTab` 的 Steam CEF 适配，不依赖 `navigator.clipboard`。48 KiB 的显示限制低于 64 KiB 剪贴板限制；复制期间不刷新内容。CEF 返回失败 / 不可用时明确提示，不伪报成功。刷新失败保留原文，截断提示不会被复制成功反馈清除。

**日志是未经脱敏的原始记录，可能包含用户名、设备序列号、挂载路径等私人信息，分享前请检查。** 不再生成脱敏报告或 TXT。udisks2 是否记录主动挂载由系统决定；缺少消息时不会伪造“系统操作日志”，操作成功也不依赖这些消息。

## 会话与中断

不读写 `remount-state.json`、`remount-audit.json`，不永久保存系统日志。仅保留本次会话最近结果和同一连接内已验证的挂载选项；新操作覆盖结果，重启插件即丢失。旧版本文件不会被读取或继续写入，可自行移除。

RPC 使用 `asyncio.shield`：关闭前端或取消等待不主动取消已开始的命令；插件卸载等待事务完成，取消卸载等待也不向事务传播取消。显式取消 / 异常保留“不确定”。单个 UDisks 命令 20 秒，不自动重试；扫描命令各 8 秒。进程被强杀、断电或热拔插仍可能中断操作；新会话无法恢复旧结果或原挂载选项，必须刷新核对真实状态。用户空间校验无法消除所有物理竞态，操作期间不要更新、禁用插件或拔盘。

## 安装、构建与发布

游戏模式 → Decky 设置 → 开发者模式 → **Install Plugin from URL**，使用固定直链：

```text
https://github.com/ohxiaoguang/decky-external-storage-guard/releases/latest/download/External-Storage-Guard.zip
```

[下载安装包](https://github.com/ohxiaoguang/decky-external-storage-guard/releases/latest/download/External-Storage-Guard.zip) · [所有版本](https://github.com/ohxiaoguang/decky-external-storage-guard/releases)

“复制更新链接”使用同一地址，无下载或自动更新逻辑。latest 只随正式 Release 更新；新版本需发布后才能从此处下载。也可用 **Install Plugin from ZIP File**。不要使用 GitHub 自动生成的 Source code ZIP / tar.gz。

开发需要 Node.js 22+、npm、Python 3.10+；后端没有第三方 Python 依赖，使用 Decky Python，前端 React 由 Steam 提供：

```bash
npm ci --ignore-scripts
npm run package
```

执行严格 TypeScript、Python 测试、Rollup、安装 ZIP / 隔离加载 / 前端交互检查，生成 `out/External-Storage-Guard.zip`。包内只有一个 `external-storage-guard/` 顶层，包含 `main.py`、`plugin.json`、`package.json`、`dist/index.js`、安全操作 / 设备 / 原始日志模块、README / LICENSE，没有旧分类 / 休眠分析 / 报告模块、测试、node_modules 或操作历史。

现有 Actions push / PR 检查及 `v*` 标签发布流程保留：依赖安装 → 版本校验 / 测试 / 构建 / ZIP 验证 → SHA-256 → 发布固定名 ZIP 和校验文件。测试失败不会发布。Actions artifact 是外层 ZIP，须先解压取出其中的安装包。经合并并批准发布后：

```bash
python3 scripts/check_release.py v0.5.0
git tag -a v0.5.0 -m "External Storage Guard v0.5.0"
git push origin v0.5.0
```

后续先 `npm version <版本> --no-git-tag-version` 并提交，再推送匹配标签，不移动旧标签。Actions 禁用、额度或 Release 写权限阻挡时查看具体失败步骤；手动后备为本地 `npm ci --ignore-scripts && npm run package`，在对应标签的 GitHub Release 上传固定名安装 ZIP 及 SHA-256，不能以源码归档代替。

## 真实 SteamOS：分别测试卸载与挂载

1. 备份重要数据，优先使用可牺牲的测试 MicroSD / USB 数据盘。安装测试包，用手柄确认只有一层设备列表、刷新和底部两个按钮；内置 SSD 不显示，多分区的名称和按钮各自对应。
2. 只读核对 `lsblk -f` 与 `findmnt -rn -S /dev/<已核实外部分区> -o TARGET,FSTYPE,OPTIONS`。不要照抄未知设备路径；关闭该分区上的游戏 / 程序、等待写入结束。
3. **卸载**：已挂载时“卸载”启用、“挂载”禁用。点击并确认，观察原设备卡片原位变为“未挂载”，“挂载”启用；终端 findmnt 应不再列出该分区。等待一段时间也不得自动重新挂载。无 EXT4 内核消息不应影响基于状态的成功判断，不能把卸载当作设备已经断电。
4. **挂载**：对同一未挂载分区点击“挂载”，确认卡片变为“已挂载”，显示实际路径 / RO 或 RW，“卸载”启用。终端核对 findmnt 及 Steam 库路径。只读测试介质应保持只读，不能出现强制恢复可写。若挂载失败 / 结果不确定，卡片不能整页重置或提示成功，按提示刷新再核对。
5. 在无重要数据的测试介质上保持工作目录或文件占用后尝试卸载，应安全提示设备正在使用，无强制卸载。退出占用再手动刷新重试。验证缺少 UDisks 授权、已断开设备和过期授权的反馈；不要为了测试强拔有写入的盘或制造文件系统损坏。
6. 打开日志弹窗，验证尺寸、手柄 / 键盘滚动、换行、刷新、B / 关闭按钮。将复制结果粘贴到可信文本框，应与窗口显示全文相同，保留 Tuning failed 等原文和原始时间戳。与本次启动 journal 的内核 / systemd / udisks2 原消息对照；系统没有的挂载消息不得出现，达到限制必须提示截断。
7. 操作等待期间关闭菜单后重新打开，应在后台完成后看到实时状态和最近结果；不可牺牲重要存档测试强杀 / 断电。新会话没有历史不能当作上次成功。检查更新链接复制、两种设备 / 多分区、exFAT / NTFS 用户权限和实际只读行为。

当前开发环境是 Linux 容器，不能验证真实 SteamOS 的 UDisks / polkit、物理 SD / USB、手柄焦点、ModalRoot 尺寸、Steam CEF 剪贴板或实际内核 / udisks2 日志行为。自动化桩通过不等于实机通过，也不能据此断言此前“看起来重新进入插件”的现场原因。
