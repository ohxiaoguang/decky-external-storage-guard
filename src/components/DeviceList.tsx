import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { Device } from "../types";
import { zh, kind, size } from "../strings";

export function accessState(d: Device): string {
  const states = d.partitions.flatMap(p => p.mounts.map(m => p.readOnly || m.readOnly));
  if (!d.mounted) return "—";
  if (d.readOnly || (states.length > 0 && states.every(Boolean))) return zh.readonly;
  return states.some(Boolean) ? "部分只读" : zh.writable;
}

export function DeviceList({ devices, onSelect, readable, selected, busy }: {
  selected?: string | null; busy?: boolean;
  devices: Device[]; onSelect: (id: string) => void; readable: boolean;
}) {
  return <PanelSection title={zh.overview}>
    {!devices.length && <PanelSectionRow><p>{zh.noDevices}</p></PanelSectionRow>}
    {devices.map(d => <PanelSectionRow key={d.id}>
      <ButtonItem layout="below" disabled={busy} onClick={() => onSelect(d.id)} description={
        `${size(d.size)} · ${[...new Set(d.partitions.map(p => p.filesystem).filter(Boolean))].join(" / ") || zh.unknownType} · ${d.mounted ? zh.mounted : zh.unmounted} · ${accessState(d)}`
      }>
        <span style={{ color: !readable ? "#ffce70" : d.counts.Error ? "#ff9a9a" : d.counts.Warning ? "#ffce70" : undefined }}>
          {selected === d.id ? "● " : ""}{d.model || kind(d.kind)}<br />
          {readable ? `本次开机记录：${zh.levels.Error} ${d.counts.Error} · ${zh.levels.Warning} ${d.counts.Warning}` : zh.unknown}
        </span>
      </ButtonItem>
    </PanelSectionRow>)}
  </PanelSection>;
}
