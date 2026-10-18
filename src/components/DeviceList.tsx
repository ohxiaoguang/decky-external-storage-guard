import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { Device } from "../types";
import { zh, kind, size } from "../strings";

export function DeviceList({ devices, onSelect, readable }: {
  devices: Device[]; onSelect: (id: string) => void; readable: boolean;
}) {
  return <PanelSection title={zh.overview}>
    {!devices.length && <PanelSectionRow><p>{zh.noDevices}</p></PanelSectionRow>}
    {devices.map(d => <PanelSectionRow key={d.id}>
      <ButtonItem layout="below" onClick={() => onSelect(d.id)} description={
        `${kind(d.kind)} · ${size(d.size)} · ${d.mounted ? zh.mounted : zh.unmounted}${d.readOnly ? ` · ${zh.readonly}` : ""}`
      }>
        <span style={{ color: !readable ? "#ffce70" : d.counts.Error ? "#ff9a9a" : d.counts.Warning ? "#ffce70" : undefined }}>
          {d.model || d.name} ({d.name})<br />
          {readable ? `${zh.levels.Error} ${d.counts.Error} · ${zh.levels.Warning} ${d.counts.Warning}` : zh.unknown}
        </span>
      </ButtonItem>
    </PanelSectionRow>)}
  </PanelSection>;
}
