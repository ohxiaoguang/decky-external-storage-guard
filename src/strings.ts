// Keep user-facing strings together for future locale support.
export const zh = {
  name: "External Storage Guard", overview: "设备概览", detail: "设备详情", logs: "日志详情",
  refresh: "刷新", loading: "正在读取设备和内核日志…", refreshed: "最近刷新",
  windows: { boot: "本次启动", day: "最近 24 小时", previous: "上一次启动" },
  levels: { Error: "严重", Warning: "警告", Info: "信息" },
  allLevels: "全部级别", allDevices: "全部设备", unassociated: "未关联事件",
  noDevices: "未检测到可确认的外部存储设备", noEvents: "当前筛选下没有事件",
  clean: "已读取的日志中未发现严重或警告事件", unknown: "日志不可用，无法判断设备是否正常",
  partial: "仅显示有限日志：最多读取 6000 条内核记录，返回最近 500 条匹配事件。计数仅限返回的记录。",
  scope: "仅按需读取。无错误记录不代表设备健康；只读挂载也可能是用户主动设置。",
  history: "历史记录仅在可确认归属时关联设备；无法确认、已拔出或设备名可能复用的记录列入未关联事件。",
  mounted: "已挂载", unmounted: "未挂载", readonly: "只读", writable: "可写",
  back: "返回设备概览", missing: "设备已断开或当前无法扫描，请返回设备概览。",
  raw: "查看原始日志", collapse: "收起原始日志", more: "下一页", prev: "上一页",
  unavailable: "暂无", requestError: "Decky 后端通信失败，请刷新或查看 Decky 日志。",
  partition: "分区与挂载", lastEvent: "最近异常", scan: "设备扫描", journal: "内核日志",
  unknownType: "未知", sd: "SD 卡", filter: "筛选", page: "页",
  kind: "事件类型", refs: "日志引用", timeUnknown: "时间不可用", count: "记录数",
  eventKinds: {
    cache_flush: "缓存刷新失败", io_error: "读写失败", filesystem: "文件系统错误",
    readonly: "异常只读", offline: "设备离线", disconnect: "设备断开", initialization: "初始化失败",
    tuning: "调谐回退", timeout: "响应超时", reset: "重试或重置", crc: "传输校验",
    controller: "控制器异常", mount: "挂载变化", recognized: "设备识别",
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
