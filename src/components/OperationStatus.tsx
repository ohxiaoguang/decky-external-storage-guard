import { PanelSection, PanelSectionRow } from "@decky/ui";
import { Operation } from "../types";
import { zh } from "../strings";

const reasons: Record<string, string> = {
  device_busy: "设备正在使用，请先关闭相关程序", permission_denied: "权限不足",
  device_disconnected: "设备已断开", stale_target: "设备状态变化，请刷新后重新确认",
  invalid_target: "授权过期，请刷新后重新确认", timeout: "命令超时，结果不确定，请刷新核对",
  interrupted: "操作中断，结果不确定，请刷新核对", unknown: "结果不确定，请刷新核对",
  busy: "其他操作进行中", missing_command: "系统缺少 udisksctl",
};
export function OperationStatus({ operation, busy }: { operation: Operation | null; busy: boolean }) {
  if (!operation && !busy) return null;
  const success = operation?.status === "success";
  return <PanelSection title="最近操作"><PanelSectionRow>
    <div role="status" style={{ fontSize: 13, color: busy ? undefined : success ? "#9ddeae" : "#ffce70" }}>
      {busy ? "操作中…" : success ? "成功：已验证重新挂载" :
        `失败：${reasons[operation!.status] || `${zh.phases[operation!.phase] || "状态验证"}未完成`}`}
    </div>
  </PanelSectionRow></PanelSection>;
}
