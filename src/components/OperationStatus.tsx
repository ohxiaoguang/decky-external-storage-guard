import { PanelSection, PanelSectionRow } from "@decky/ui";
import { Operation } from "../types";
import { time, zh } from "../strings";

export function OperationStatus({ operation, busy }: { operation: Operation | null; busy: boolean }) {
  if (!operation && !busy) return null;
  return <PanelSection title={zh.operation}><PanelSectionRow>
    <div role="status" style={{ fontSize: 13, lineHeight: 1.6, overflowWrap: "anywhere" }}>
      {busy ? <p>{zh.managing}</p> : operation && <>
        <strong style={{ color: operation.status === "success" ? "#9ddeae" : "#ffce70" }}>
          {operation.status === "success" ? zh.operationSuccess : zh.operationFailure} · {operation.partition}
        </strong>
        <p>{operation.message}</p>
        <p>{zh.phase}：{zh.phases[operation.phase] || operation.phase} ({operation.status})</p>
        {operation.method && <p>{operation.method}</p>}
        {operation.startedAt && <p>开始：{time(operation.startedAt)} · {operation.operationId}</p>}
        {operation.commands?.map((command, i) => <p key={i}>
          {zh.phases[command.phase] || command.phase}：返回码 {command.returncode ?? "未取得"} · {command.status}
        </p>)}
        {operation.method && <p>已验证：原挂载 {operation.beforeUnmount ? "是" : "未确认"} → 无挂载 {operation.afterUnmount ? "是" : "未确认"} → 新挂载 {operation.afterMount ? "已观察（仍以最终结果为准）" : "未确认"}；完整审计见诊断报告。</p>}
        {operation.detail && <p>{operation.detail}</p>}
        {operation.warnings.map(w => <p key={w} style={{ color: "#ffce70" }}>{w}</p>)}
        {operation.finishedAt && <p>{time(operation.finishedAt)}</p>}
      </>}
    </div>
  </PanelSectionRow></PanelSection>;
}
