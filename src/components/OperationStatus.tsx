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
        {operation.detail && <p>{operation.detail}</p>}
        {operation.warnings.map(w => <p key={w} style={{ color: "#ffce70" }}>{w}</p>)}
        {operation.finishedAt && <p>{time(operation.finishedAt)}</p>}
      </>}
    </div>
  </PanelSectionRow></PanelSection>;
}
