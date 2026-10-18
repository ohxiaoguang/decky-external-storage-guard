import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { callable } from "@decky/api";
import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { Snapshot, Window, Severity, RemountResponse, Operation } from "./types";
import { zh, time } from "./strings";
import { Status } from "./components/Status";
import { DeviceList } from "./components/DeviceList";
import { DeviceDetail } from "./components/DeviceDetail";
import { EventList } from "./components/EventList";
import { OperationStatus } from "./components/OperationStatus";
import { SleepHistory } from "./components/SleepHistory";
import { ReportControls } from "./components/ReportControls";

const getSnapshot = callable<[window: Window], Snapshot>("get_snapshot");
const remountPartition = callable<[token: string], RemountResponse>("remount_partition");
const cleanups = new Set<() => void>();
export function disposeViews() { cleanups.forEach(fn => fn()); cleanups.clear(); }

export function App() {
  const [window, setWindow] = useState<Window>("boot");
  const [data, setData] = useState<Snapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [managing, setManaging] = useState(false);
  const [operation, setOperation] = useState<Operation | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [deviceFilter, setDeviceFilter] = useState("all");
  const [level, setLevel] = useState<Severity | "all">("all");
  const [sleepCycle, setSleepCycle] = useState<string | null>(null);
  const [wakeMinutes, setWakeMinutes] = useState(5);
  const generation = useRef(0);
  const active = useRef(false);
  const loading = useRef(false);
  const windowRef = useRef<Window>("boot");
  const refresh = useCallback(async (requestedWindow = windowRef.current) => {
    if (loading.current || !active.current) return;
    loading.current = true;
    const request = ++generation.current;
    setBusy(true); setError("");
    try {
      const result = await getSnapshot(requestedWindow);
      if (active.current && generation.current === request) { setData(result); setOperation(result.lastOperation); setSleepCycle(null); }
    } catch {
      if (active.current && generation.current === request) { setError(zh.requestError); setData(null); }
    } finally {
      if (active.current && generation.current === request) { setBusy(false); loading.current = false; }
    }
  }, []);
  const remount = async (token: string) => {
    if (loading.current || !active.current) return;
    loading.current = true;
    const request = ++generation.current;
    setBusy(true); setManaging(true); setError("");
    try {
      const result = await remountPartition(token);
      if (active.current && generation.current === request) {
        setOperation(result.operation);
        if (result.snapshot) {
          windowRef.current = "boot"; setWindow("boot"); setData(result.snapshot);
          setSleepCycle(null);
        }
      }
    } catch {
      if (active.current && generation.current === request) {
        setOperation(null); setData(null); setError(zh.communicationUnknown);
      }
    } finally {
      if (active.current && generation.current === request) { setBusy(false); setManaging(false); loading.current = false; }
    }
  };
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
    (level === "all" || e.severity === level) &&
    (!sleepCycle || (e.wakeContext?.cycleId === sleepCycle && e.wakeContext.phase === "after_wake" &&
      e.wakeContext.delaySeconds !== null && e.wakeContext.delaySeconds <= wakeMinutes * 60))
  ), [data, selected, deviceFilter, level, sleepCycle, wakeMinutes]);
  const device = data?.devices.find(d => d.id === selected);
  return <>
    <PanelSection>
      <PanelSectionRow><DropdownItem label={zh.journal} selectedOption={window} disabled={busy}
        rgOptions={Object.entries(zh.windows).map(([data, label]) => ({ data, label }))}
        onChange={option => {
          const next = option.data as Window;
          windowRef.current = next; setWindow(next); setData(null); void refresh(next);
        }} /></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => void refresh()}>
        {busy ? zh.loading : zh.refresh}
      </ButtonItem></PanelSectionRow>
      {data && <PanelSectionRow><p style={{ fontSize: 12 }}>{zh.refreshed}：{time(data.refreshedAt)}</p></PanelSectionRow>}
      {error && <PanelSectionRow><p style={{ color: "#ff9a9a" }}>{error}</p></PanelSectionRow>}
    </PanelSection>
    <ReportControls busy={busy} onBusy={value => { if (active.current) { loading.current = value; setBusy(value); } }} />
    <OperationStatus operation={operation} busy={managing} />
    {data && <>
      <Status data={data} />
      {data.sleepHistory && <SleepHistory history={data.sleepHistory} selected={sleepCycle} onSelect={setSleepCycle} minutes={wakeMinutes} onMinutes={setWakeMinutes} />}
      {selected ? <>
        <PanelSection><PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => setSelected(null)}>{zh.back}</ButtonItem></PanelSectionRow></PanelSection>
        {device ? <DeviceDetail device={device} readable={data.journalStatus.status === "ok"} busy={busy} onRemount={token => void remount(token)} /> :
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
