import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { callable } from "@decky/api";
import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { Snapshot, Window, Severity } from "./types";
import { zh, time } from "./strings";
import { Status } from "./components/Status";
import { DeviceList } from "./components/DeviceList";
import { DeviceDetail } from "./components/DeviceDetail";
import { EventList } from "./components/EventList";

const getSnapshot = callable<[window: Window], Snapshot>("get_snapshot");
const cleanups = new Set<() => void>();
export function disposeViews() { cleanups.forEach(fn => fn()); cleanups.clear(); }

export function App() {
  const [window, setWindow] = useState<Window>("boot");
  const [data, setData] = useState<Snapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [deviceFilter, setDeviceFilter] = useState("all");
  const [level, setLevel] = useState<Severity | "all">("all");
  const generation = useRef(0);
  const active = useRef(false);
  const loading = useRef(false);
  const refresh = useCallback(async () => {
    if (loading.current || !active.current) return;
    loading.current = true;
    const request = ++generation.current;
    setBusy(true); setError("");
    try {
      const result = await getSnapshot(window);
      if (active.current && generation.current === request) setData(result);
    } catch {
      if (active.current && generation.current === request) { setError(zh.requestError); setData(null); }
    } finally {
      if (active.current && generation.current === request) { setBusy(false); loading.current = false; }
    }
  }, [window]);
  useEffect(() => {
    active.current = true; loading.current = false;
    const cancel = () => { active.current = false; generation.current++; };
    cleanups.add(cancel);
    setData(null);
    void refresh();
    return () => { cancel(); cleanups.delete(cancel); };
  }, [refresh]);
  const filtered = useMemo(() => (data?.events || []).filter(e =>
    (selected ? e.deviceId === selected : deviceFilter === "all" ||
      (deviceFilter === "unassociated" ? !e.deviceId : e.deviceId === deviceFilter)) &&
    (level === "all" || e.severity === level)
  ), [data, selected, deviceFilter, level]);
  const device = data?.devices.find(d => d.id === selected);
  return <>
    <PanelSection>
      <PanelSectionRow><DropdownItem label={zh.journal} selectedOption={window} disabled={busy}
        rgOptions={Object.entries(zh.windows).map(([data, label]) => ({ data, label }))}
        onChange={option => setWindow(option.data as Window)} /></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => void refresh()}>
        {busy ? zh.loading : zh.refresh}
      </ButtonItem></PanelSectionRow>
      {data && <PanelSectionRow><p style={{ fontSize: 12 }}>{zh.refreshed}：{time(data.refreshedAt)}</p></PanelSectionRow>}
      {error && <PanelSectionRow><p style={{ color: "#ff9a9a" }}>{error}</p></PanelSectionRow>}
    </PanelSection>
    {data && <>
      <Status data={data} />
      {selected ? <>
        <PanelSection><PanelSectionRow><ButtonItem layout="below" onClick={() => setSelected(null)}>{zh.back}</ButtonItem></PanelSectionRow></PanelSection>
        {device ? <DeviceDetail device={device} readable={data.journalStatus.status === "ok"} /> :
          <PanelSection><PanelSectionRow><p>{zh.missing}</p></PanelSectionRow></PanelSection>}
      </> : <DeviceList devices={data.devices} onSelect={setSelected} readable={data.journalStatus.status === "ok"} />}
      <PanelSection title={zh.filter}>
        {!selected && <PanelSectionRow><DropdownItem label={zh.overview} selectedOption={deviceFilter}
          rgOptions={[{ data: "all", label: zh.allDevices }, { data: "unassociated", label: zh.unassociated },
            ...data.devices.map(d => ({ data: d.id, label: d.model ? `${d.name} · ${d.model}` : d.name }))]}
          onChange={option => setDeviceFilter(option.data)} /></PanelSectionRow>}
        <PanelSectionRow><DropdownItem label={zh.logs} selectedOption={level}
          rgOptions={[{ data: "all", label: zh.allLevels }, ...Object.entries(zh.levels).map(([data, label]) => ({ data, label }))]}
          onChange={option => setLevel(option.data as Severity | "all")} /></PanelSectionRow>
      </PanelSection>
      <EventList events={filtered} />
    </>}
  </>;
}
