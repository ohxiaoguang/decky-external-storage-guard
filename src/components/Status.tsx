import { PanelSection, PanelSectionRow } from "@decky/ui";
import { Snapshot } from "../types";
import { zh } from "../strings";

export function Status({ data }: { data: Snapshot }) {
  const readable = data.journalStatus.status === "ok";
  const clean = readable && !data.journalStatus.limited && data.deviceStatus.status === "ok" && !data.events.some(e => e.severity !== "Info");
  return <PanelSection title={zh.journal}>
    <PanelSectionRow><div style={{ fontSize: 13, lineHeight: 1.5 }}>
      {data.deviceStatus.status !== "ok" && <p style={{ color: "#ff9a9a" }}>{zh.scan}：{data.deviceStatus.message}</p>}
      <p style={{ color: readable ? undefined : "#ffce70" }}>{data.journalStatus.message}</p>
      {!readable && <p>{zh.unknown}</p>}
      {clean && <p>{zh.clean}</p>}
      {data.journalStatus.limited && <p style={{ color: "#ffce70" }}>{zh.partial}</p>}
      {data.warnings.map(w => <p key={w}>{w}</p>)}
      <p>{zh.scope}</p>
      {data.window !== "boot" && <p>{zh.history}</p>}
    </div></PanelSectionRow>
  </PanelSection>;
}
