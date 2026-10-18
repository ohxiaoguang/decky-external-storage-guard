// Keep user-facing strings together for future locale support.
export const zh = {
  name: "External Storage Guard", overview: "设备概览", detail: "设备详情", logs: "日志详情",
  refresh: "刷新", loading: "正在读取设备和内核日志…", refreshed: "最近刷新",
  windows: { boot: "本次启动", day: "最近 24 小时", week: "最近 7 天", all: "全部可用记录（有界）", previous: "上一次启动" },
  levels: { Error: "严重", Warning: "警告", Info: "信息" },
  allLevels: "全部级别", allDevices: "全部设备", unassociated: "未关联事件",
  noDevices: "未检测到可确认的外部存储设备", noEvents: "当前筛选下没有事件",
  clean: "已读取的日志中未发现严重或警告事件", unknown: "日志不可用，无法判断设备是否正常",
  partial: "日志或事件已触及限制：普通范围最多6000条，长范围12000条，事件返回最近500条。不能据此排除更早异常。",
  sleep: "休眠历史", sleepMissing: "未发现可配对休眠记录，可能未休眠、记录缺失或窗口不完整。",
  sleepUnavailable: "休眠日志不可用，无法判断休眠历史。", causal: "仅表示时间相关，不代表休眠导致存储错误。时间以日志边界估计，可能受挂起时钟、校时和日志延迟影响。",
  afterWake: "唤醒后", estimated: "约", seconds: "秒", afterWindow: "唤醒后观察窗口",
  allSleepEvents: "取消休眠周期筛选", sleepStart: "休眠开始", wakeEnd: "唤醒完成", boot: "启动 ID",
  sleepStates: { paired: "日志已配对（估计）", missing_start: "缺休眠开始", missing_wake: "缺唤醒完成", failed: "失败或中止" } as Record<string, string>,
  wakeUnknown: "无法确定最近一次唤醒", beforeSleep: "休眠前", duringSleep: "休眠/恢复过程中，时间归属不确定",
  clockAdjusted: "时钟可能已调整", beforeNextSleep: "也发生在下一次休眠前",
  sleepLimited: "休眠记录/事件/原文可能不完整，计数仅覆盖返回的事件。", sleepObservations: "识别到的相关线索",
  reports: "诊断报告", copyReport: "复制诊断报告", copySummary: "复制简短摘要", exportTxt: "导出 TXT 文件",
  reportRange: "报告范围", reportBusy: "正在读取并生成报告…", reportPrivacy: "默认脱敏序列号、UUID、用户名路径与常见凭据。保留型号、PCI ID 和本地设备/总线名称供诊断；分享前仍请检查。",
  reportLimit: "报告可能受 journal 保留历史和条数/大小限制；完整原始诊断消息指本次有界读取中的脱敏相关消息。",
  reportCopied: "复制命令已确认执行，请粘贴检查内容。", reportCopyFailed: "复制失败或 Steam 剪贴板不可用，请导出 TXT。",
  reportTooLarge: "完整报告超过64KiB复制上限，请导出 TXT 或复制简短摘要；不会静默截短复制。",
  reportSaved: "已保存 UTF-8 报告", reportTruncated: "报告有截断，详情见报告中的限制章节。",
  reportComplete: "未触及报告大小上限，历史完整性仍受系统保留情况限制。", reportFailure: "报告操作失败，请查看原因。",
  scope: "仅按需读取。无错误记录不代表设备健康；只读挂载也可能是用户主动设置。",
  history: "历史记录仅在可确认归属时关联设备；无法确认、已拔出或设备名可能复用的记录列入未关联事件。",
  mounted: "已挂载", unmounted: "未挂载", readonly: "只读", writable: "可写",
  back: "返回设备概览", missing: "设备已断开或当前无法扫描，请返回设备概览。",
  raw: "查看原始日志", collapse: "收起原始日志", more: "下一页", prev: "上一页",
  unavailable: "暂无", requestError: "Decky 后端通信失败，请刷新或查看 Decky 日志。",
  partition: "分区与挂载", lastEvent: "最近异常", scan: "设备扫描", journal: "内核日志",
  unknownType: "未知", sd: "SD 卡", filter: "筛选", page: "页",
  kind: "事件类型", refs: "日志引用", timeUnknown: "时间不可用", count: "记录数",
  remount: "重新挂载", cancel: "取消", confirmRemount: "确认重新挂载",
  remountWarning: "正在运行的游戏或程序可能受影响，存在存档丢失风险。请先关闭使用此设备的所有程序，确保写入已结束。将安全卸载后重新挂载；卸载失败会立即停止。此操作不修复文件系统，不解除故障只读状态，挂载路径也可能变化。",
  noRepair: "重新挂载不能代替文件系统检查或修复；本插件不会运行 fsck。",
  managing: "正在安全卸载并重新挂载，请勿拔出设备或卸载插件…",
  operation: "设备操作结果", operationSuccess: "成功", operationFailure: "未完成",
  phase: "阶段", phases: { validation: "操作对象校验", unmount: "安全卸载", mount: "重新挂载", verify: "挂载状态确认" } as Record<string, string>,
  manageUnavailable: "该分区仅支持监控，请刷新查看操作资格。",
  communicationUnknown: "设备操作通信中断，结果尚未确认。后端可能仍在执行，请等待后刷新核对真实状态，不要立即重复操作。",
  eventKinds: {
    cache_flush: "缓存刷新失败", io_error: "读写失败", filesystem: "文件系统错误",
    readonly: "异常只读", offline: "设备离线", disconnect: "设备断开", initialization: "初始化失败",
    tuning: "调谐回退", timeout: "响应超时", reset: "重试或重置", crc: "传输校验",
    controller: "控制器异常", mount: "挂载变化", recognized: "设备识别",
    filesystem_check: "文件系统检查要求 / 日志中止",
  } as Record<string, string>,
} as const;

export function time(value: number | null): string {
  return value ? new Date(value).toLocaleString() : zh.timeUnknown;
}
export function size(bytes: number): string {
  if (!bytes) return zh.unavailable;
  return `${(bytes / 1024 ** 3).toFixed(1)} GiB`;
}
export function kind(value: string): string {
  return value === "SD" ? zh.sd : value === "Unknown" ? zh.unknownType : value;
}
