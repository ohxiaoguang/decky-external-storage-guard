# External Storage Guard v0.1.0

SteamOS 游戏模式中的只读外部存储诊断 Decky 插件。适用于 Steam Deck、安装 SteamOS 的 ROG Ally X 等设备；首版界面为中文。

本项目实现了实际系统读取，没有内置演示数据、HTTP 服务或额外监听端口。**构建和自动化测试通过不等于已经通过实机验收**；ROG Ally X / Steam Deck 的 Decky 加载、手柄操作、真实读卡器与 USB 桥接兼容性仍需按下文验证。

## 功能与判断边界

- 自动列出可确认的原生 SD 卡、USB HDD / SSD 及分区，包括未挂载设备；显示容量、文件系统、所有可见挂载点与只读状态。
- 使用 `lsblk --json`、sysfs 拓扑和 `findmnt --json`；不凭 `sda`、`mmcblk0` 名称或单个 removable 标志判断。原生 SD 需要 sysfs `device/type=SD` 和 MMC host 拓扑；eMMC (`MMC`) 排除。USB 通过传输类型或 sysfs USB 拓扑确认。
- 排除内置 NVMe，以及承载 `/`、`/usr`、`/var`、`/home`、`/boot`、`/efi` 的磁盘（包括映射设备的父盘）。无法确认外置属性的磁盘不列出；已确认 USB 但无法判别 HDD / SSD 时显示“未知”。USB 的 HDD / SSD 分类依赖内核 ROTA 提示，不能保证识别硬盘盒内真实介质。
- 读取本次启动、最近 24 小时、上次启动的内核日志。最近 24 小时使用 `journalctl _TRANSPORT=kernel --since=-24h`，这是 `-k` 的内核过滤条件，但不隐含限制为本次启动。
- 分类 MMC 调谐 / CRC / 初始化 / 缓存刷新、I/O、USB 重置 / 断开、SCSI / UAS、ext4 / exFAT / NTFS、实际只读重挂载等事件。按设备和严重程度筛选，时间倒序，点击查看原始日志；时间按设备本地时区显示。
- 严重：读写失败、缓存刷新失败、文件系统错误、内核拒绝离线设备 I/O、因错误切换只读。警告：调谐回退、重试 / 重置、CRC、超时；超时不自动宣称已恢复。信息：识别、正常挂载 / 卸载、USB 断开。
- **一条 `USB disconnect` 不能判断用户是否主动拔出，因此单独按信息展示；伴随的真实 I/O / offline 错误仍按严重展示。** 只读挂载也不自动当作故障。`errors=remount-ro` 是挂载策略；重复 Tuning failed 记录次数但不认定卡损坏；游戏 segfault 排除。

### 设备关联的保守策略

本次启动通过块设备 / 分区名、sysfs MMC 控制器、精确 USB 端口和 SCSI 地址关联。USB hub 下不同端口不混用，候选设备有歧义时不分配归属；不会根据时间相邻把鼠标或手柄的 USB reset 当作磁盘异常。

已拔出的块设备错误、无法确认身份的记录进入“未关联事件”，保留日志引用。历史中明确的 `usb-storage <端口>` / USB 存储驱动证据可以用于识别该端口断开前的存储事件；只有泛化 USB 枚举或断开记录、没有存储证据时不显示。缺少拓扑的历史 UAS 总线事件可能因此漏报，这是为避免无关外设误判而采用的限制。

**上次启动的记录不使用本次启动的设备名对应关系**，最近 24 小时也逐条检查 boot ID；历史存储异常通常列入未关联事件。对本次启动已观察到的重新 attach / disconnect 边界，较早世代的记录也不计入当前设备。这不是跨重启持久设备身份追踪；当前日志尾部缺失身份变更证据时，内核设备名仍存在复用风险。没有可确认外置身份的历史 NVMe 错误被排除。

没有异常记录不等于设备健康。计数仅针对当前时间范围内**返回的最近记录**，不是磁盘寿命计数或完整健康评估。

## 安全、权限与性能

插件仅运行固定参数的 `lsblk`、`findmnt`、`journalctl`，读取 sysfs 和本次 boot ID。没有 shell 命令拼接；不执行 mount / umount、修复、格式化、扫描重置、SMART 或读写压力测试，不修改系统配置，不调用 sudo 或询问密码。

`plugin.json` 声明 Decky 支持的 `root` 标志，让后端在 Decky 已有的权限范围内读取内核日志（官方模板的 `_root` 是未启用的占位形式，核对 Loader 实现后改为实际标志）。若运行环境仍不授权读取，界面明确显示权限不足。插件不会自动改变 journald、用户组或系统权限。

只在界面挂载时和手动刷新时读取；没有后台定时器。前端离开界面后忽略未完成结果，已经发出的后端读取会在超时内结束；卸载插件时取消读取并终止尚存子进程。

每条系统命令最多 8 秒；一次刷新按顺序最多执行三条命令，通常远低于 24 秒。stdout 上限 8 MiB、stderr 上限 64 KiB；每次最多读取最新 6000 条内核日志，每条消息最多 4096 字符，返回最新 500 条匹配事件；前端每页显示 20 条。触及日志条数 / 事件条数限制会提示结果不完整，触及输出上限则明确报错。设备扫描失败、日志为空、权限不足、没有历史、超时、命令缺失、读取失败分别返回状态；读取失败绝不显示为“设备正常”。

## 技术结构

参考官方 [decky-plugin-template](https://github.com/SteamDeckHomebrew/decky-plugin-template/tree/90d0780e882a17f5714fc6de044c645f22608290) 的 Rollup / TS 配置，并核对 Loader 的 API v1 实例化和 ZIP 安装实现。使用 `@decky/api` 的 `definePlugin` / `callable`，不使用旧版 `serverAPI.callPluginMethod`。

```text
main.py                     Decky API v1 与卸载生命周期
storage_guard/commands.py   有界、可取消的只读命令执行
storage_guard/devices.py    设备发现、sysfs、挂载状态与系统盘排除
storage_guard/journal.py    日志读取、时间范围和错误状态
storage_guard/rules.py      独立分类规则（纯函数）
storage_guard/events.py     关联、启动隔离、排序与数量限制（纯函数）
storage_guard/service.py    组合扫描、事件计数与结构化响应
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

固定版本安装地址为 `https://github.com/ohxiaoguang/decky-external-storage-guard/releases/download/v0.1.0/External-Storage-Guard.zip`（替换版本标签可安装其他版本）。直链需要相应 Release 已成功发布并附带安装资产；返回 404 时先检查 Release / Actions 页面。

也可将下载或本地构建的 `External-Storage-Guard.zip` 放入掌机 Downloads，再通过 **Install Plugin from ZIP File / 从 ZIP 文件安装插件** 安装。**不要使用 GitHub 自动生成的 Source code (zip) / Source code (tar.gz)**；源码归档没有编译后的 `dist/index.js`，不能代替插件安装包。

## 自动发布与手动后备方式

`.github/workflows/release.yml` 在推送 `v*` 标签时执行：校验标签版本 → `npm ci --ignore-scripts` → 类型检查和全部单元测试 → Rollup 编译 → 白名单打包和 ZIP / 隔离加载验证 → 生成 SHA-256 → 上传构建 artifact → 发布任务校验下载包的 SHA-256 → 上传固定名资产并公开 GitHub Release。构建 / 测试失败不会进入发布任务，上传失败不会将新建草稿公开。

构建任务只有 `contents: read`，发布任务使用 GitHub 自动提供的 `GITHUB_TOKEN` 和 `contents: write`，无需额外 PAT。正式标签发布为 latest，含连字符的预发布标签发布为 prerelease；标签与 `package.json`、`package-lock.json` 必须完全一致。重跑同一标签的工作流会复用 Release 并重新上传资产，不创建第二个 Release。

首次版本的标签命令示例（发布流程必须已提交到该标签所指提交）：

```bash
python3 scripts/check_release.py v0.1.0
git tag -a v0.1.0 -m "External Storage Guard v0.1.0"
git push origin v0.1.0
```

后续发版先用 `npm version <新版本> --no-git-tag-version` 同步 package 与 lockfile 并提交，再推送对应的 `v<新版本>` 标签；不要移动已有发布标签。版本不匹配时查看 Actions 的 **Check tag and package versions** 步骤。

如果发布失败，查看 [Actions](https://github.com/ohxiaoguang/decky-external-storage-guard/actions) 对应标签的失败任务：

- `Resource not accessible by integration` / HTTP 403：仓库或组织策略限制了 Actions 的 Release 写权限；由仓库管理员检查 Actions 是否启用、工作流权限及允许的 action 策略，之后重跑失败任务。这里的 `GITHUB_TOKEN` 属于 GitHub runner，与本地开发环境的网络或 CLI 权限不同。
- runner 未启动、计费额度或 Actions 被禁用：工作流无法执行；先解决 GitHub 给出的具体原因，或采用以下本地构建和网页上传方式。
- 依赖安装、测试或 ZIP 验证失败：先修复失败项，再创建新版本标签；不要跳过验证发布源码 ZIP。

无法使用 Actions 时，手动发布步骤：

1. 检出计划发布的标签，在该提交运行 `npm ci --ignore-scripts`、`python3 scripts/check_release.py v0.1.0` 和 `npm run package`（其他版本替换标签）。全部成功后得到 `out/External-Storage-Guard.zip`。
2. 在 GitHub 仓库 **Releases → Draft a new release**，选择同一标签，上传上述 ZIP 作为独立 Release 资产，文件名保持 **External-Storage-Guard.zip**。正式版发布并标记为 latest；预发布勾选 prerelease。
3. 检查 Release 页面存在该资产，打开上面的 `latest/download` 直链并下载验证。不要选择页面自动附带的 Source code ZIP。

已在本机授权 GitHub CLI 的维护者也可执行以下命令（不能用它绕过组织策略）：

```bash
gh release create v0.1.0 out/External-Storage-Guard.zip --verify-tag --title "External Storage Guard v0.1.0" --generate-notes --latest
```

若 Release 已存在，使用 `gh release upload v0.1.0 out/External-Storage-Guard.zip --clobber` 补传资产，并在网页确认它不是草稿且是所需的 latest 正式版。

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

## 排错与可选只读诊断

- 不显示设备：确认它是 SD 或 USB 外部设备且仍被内核识别。内置 NVMe、eMMC、仅有 removable 标志而无总线证据的设备不会列出。可在桌面终端用下面只读命令核对，不需要修改或修复磁盘。
- 权限不足：确认运行的 Decky 版本支持 `root` 标志，以及其后端自身拥有读取日志的权限。不要为本插件修改 journald 或用户组、输入 sudo 密码。保留界面错误信息供排查。
- 无日志 / 无历史：内核日志可能未被 journald 收集、当前环境没有 journal 或没有持久化上次启动。插件不会自动开启持久化。日志读取成功但没有匹配异常会显示“已读取的日志中未发现严重或警告事件”，这与日志不可用不同。
- 读取超时 / 超上限：手动重试并缩短时间范围；结果有截断提示时，统计仅覆盖有限记录。
- 加载失败 / 通信失败：核对安装包目录层级、`dist/index.js`、`storage_guard`、`api_version: 1` 和当前 Decky 版本；使用 Decky 的日志页面或下面服务日志定位，不使用独立 HTTP 服务。

```bash
lsblk --json --bytes --tree --output NAME,KNAME,PATH,TYPE,SIZE,MODEL,TRAN,RM,RO,ROTA,FSTYPE,MOUNTPOINTS,MAJ:MIN
findmnt --json --list --output SOURCE,TARGET,FSTYPE,OPTIONS,MAJ:MIN
readlink -f /sys/class/block/mmcblk0
cat /sys/class/block/mmcblk0/device/type
journalctl -k -b 0 --no-pager -n 100
journalctl -u plugin_loader --no-pager -n 100
```

上述命令遇到权限不足时直接报告即可，无需提权。对外分享原始日志前自行检查路径、设备标识等个人信息。

## 验证范围与后续功能

自动化覆盖：用户提供的真实 MMC 日志；USB、SCSI / UAS、文件系统、重复计数；设备类型 / 拓扑与系统盘排除；未挂载、多挂载、只读；启动隔离、名称复用边界与未知关联；权限不足、无历史、无日志、格式错误；缺少命令、超时、输出上限、卸载取消；Decky 后端入口实例化及 JSON 响应。

非 SteamOS 开发环境可以直接运行以上测试和构建，不模拟健康设备展示。真实硬件兼容性、Decky 运行时 UI 和手柄交互需实机验收。版本对应的实际验证结果见交付时的验证报告。

首版没有重新挂载、安全弹出、重新扫描设备、修复、SMART、压力测试、常驻通知或自动恢复按钮；这些属于后续规划。
