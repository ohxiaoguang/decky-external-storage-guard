# External Storage Guard

面向 SteamOS 掌机的 Decky Loader 外部存储管理与诊断插件，适用于安装了 Decky Loader 的 Steam Deck、ROG Ally X 等设备。

在游戏模式中查看 MicroSD 和 USB 外接硬盘的状态，按分区手动挂载、卸载，并通过原始系统日志协助排查存储问题。

## 主要特性

- 识别 MicroSD、USB 移动 SSD 和移动硬盘，不显示机身内置系统盘。
- 查看设备容量、分区、挂载状态，以及当前可读写或只读状态。
- 每个符合操作条件的分区都有独立的 **卸载** 和 **挂载** 按钮，操作后核对实际状态。
- 在 Steam 全屏日志页查看存储、挂载、卸载及休眠唤醒消息，显示本地日期时间，支持刷新和全文复制。
- 简洁中文主页，支持手动刷新和复制固定更新链接。

## 安装方法

需要先安装并正常运行 Decky Loader。

1. 打开游戏模式快捷菜单中的 **Decky**，进入设置并启用开发者模式。
2. 在开发者页面选择 **Install Plugin from URL / 从 URL 安装插件**。
3. 粘贴以下地址，按提示完成安装：

   ```text
   https://github.com/ohxiaoguang/decky-external-storage-guard/releases/latest/download/External-Storage-Guard.zip
   ```

也可以从 [GitHub Releases](https://github.com/ohxiaoguang/decky-external-storage-guard/releases) 下载 **External-Storage-Guard.zip**，通过 **Install Plugin from ZIP File** 安装。请勿使用页面自动生成的 **Source code** 压缩包。

[下载最新安装包](https://github.com/ohxiaoguang/decky-external-storage-guard/releases/latest/download/External-Storage-Guard.zip)

## 使用说明

1. 在 Decky 插件列表中打开 **External Storage Guard**，查看外部存储设备及各分区状态。需要时点击 **刷新**。
2. 先关闭使用该分区的游戏和程序，点击 **卸载**，再原地点击 **确认卸载**；也可点击 **取消**，确认会在 15 秒后失效。成功后会显示“未挂载”，不会自动重新挂载。
3. 未挂载分区可以点击 **挂载**；插件通过系统服务为 Decky 的普通用户挂载，完成后查看实际路径和读写状态。无法操作时会说明原因，不会改用 root 用户目录。
4. 点击底部 **查看日志**，侧边栏关闭后进入全屏日志页，可使用 **刷新**、**复制** 或 **返回**。返回后可重新打开 Decky 查看设备状态。日志过多时会显示“日志已截断”。
5. 更新时点击 **复制更新链接**，再到 Decky 的 **Install Plugin from URL** 安装。链接无需随版本更换。

操作失败会显示原因；出现“不确定”时，请等待后刷新核对，不要把它当作成功。

## 注意事项

- 正在运行的游戏或程序可能占用存储设备。卸载前请关闭相关程序，等待写入完成，并备份重要数据。
- 本版明确申请 Decky 的 **root 后端权限**，用于后台存储操作和系统日志读取；这意味着插件后端拥有较高系统权限，请只安装可信来源的安装包。不修改系统授权规则，也不保存管理员密码。
- 分区操作要求系统 UDisks 2.10.0 或更新版本。无法确认支持为普通用户挂载时会在卸载前停止，不会尝试挂载到 root 目录。
- 卸载不等于 USB 设备已经断电。挂载成功只表示文件系统已挂载，请另行确认 Steam 游戏库可用。日志权限不足、查询异常和没有匹配记录会分别提示。
- 插件不能修复损坏的内存卡、读卡器或文件系统，也不会自动修复、格式化或强制卸载。
- 系统没有异常记录，不代表硬件一定健康。原始日志可能包含用户名、路径或设备标识，分享前请检查。
- 操作期间不要拔盘、关闭设备或更新插件。插件不保存操作历史，重启后请以当前实际状态为准。
- 更新后若提示用户身份异常，请重新加载插件或重启 Decky。不同 SteamOS、Decky 和设备环境可能存在差异，实际兼容性及游戏模式剪贴板仍需在设备上确认。

## 开源协议

本项目采用 [BSD 3-Clause License](LICENSE)。
