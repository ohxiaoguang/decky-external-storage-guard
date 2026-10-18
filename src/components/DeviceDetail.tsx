import { PanelSection, PanelSectionRow } from "@decky/ui";
import { Device } from "../types";
import { zh, kind, size, time } from "../strings";
import { RemountControls } from "./RemountControls";

export function DeviceDetail({ device: d, readable, busy, onRemount }: {
  device: Device; readable: boolean; busy: boolean; onRemount: (token: string) => void;
}) {
  return <PanelSection title={zh.detail}>
    <PanelSectionRow><div style={{ fontSize: 13, overflowWrap: "anywhere", lineHeight: 1.6 }}>
      <strong>{d.model || d.name}</strong>
      <p>{d.id} · {kind(d.kind)} · {size(d.size)}</p>
      <p>{d.mounted ? zh.mounted : zh.unmounted} · {d.readOnly ? zh.readonly : zh.writable}</p>
      <p>{readable ? `${zh.levels.Error} ${d.counts.Error} · ${zh.levels.Warning} ${d.counts.Warning} · ${zh.levels.Info} ${d.counts.Info}` : zh.unknown}</p>
      <p>{zh.lastEvent}：{d.lastEvent ? time(d.lastEvent) : zh.unavailable}</p>
      <strong>{zh.partition}</strong>
      {d.partitions.map(p => <div key={p.path} style={{ marginTop: 10 }}>
        {p.path} · {size(p.size)} · {p.filesystem || zh.unknownType}
        {p.readOnly && ` · ${zh.readonly}`}
        {p.mounts.length ? p.mounts.map(m => <div key={m.target}>
          {m.target} · {m.filesystem || p.filesystem || zh.unknownType} · {m.readOnly ? zh.readonly : zh.writable}
        </div>) : <div>{zh.unmounted}</div>}
      </div>)}
    </div></PanelSectionRow>
    {d.partitions.filter(p => p.path !== d.id).map(p =>
      <RemountControls key={p.path} partition={p} busy={busy} onRemount={onRemount} />)}
  </PanelSection>;
}
