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
import { RemountControls } from "./components/RemountControls";
import { Updates } from "./components/Updates";
import { ReportControls } from "./components/ReportControls";

const getSnapshot = callable<[window: Window], Snapshot>("get_snapshot");
const remountPartition = callable<[token: string], RemountResponse>("remount_partition");
const cleanups = new Set<() => void>();
export function disposeViews() { cleanups.forEach(fn => fn()); cleanups.clear(); }

export function App() {
  const [page, setPage] = useState<"home" | "details">("home");
  const [section, setSection] = useState("device");
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
    (deviceFilter === "all" || (deviceFilter === "unassociated" ? !e.deviceId : e.deviceId === deviceFilter)) &&
    (level === "all" || e.severity === level) &&
    (!sleepCycle || (e.wakeContext?.cycleId === sleepCycle && e.wakeContext.phase === "after_wake" &&
      e.wakeContext.delaySeconds !== null && e.wakeContext.delaySeconds <= wakeMinutes * 60))
  ), [data, selected, deviceFilter, level, sleepCycle, wakeMinutes]);
  const device = data?.devices.find(d => d.id === selected);
  const onReportBusy = (value: boolean) => { if (active.current) { loading.current = value; setBusy(value); } };
  const details = (tab = "device") => { setSection(tab); setPage("details"); };
  const home = () => {
    setPage("home"); setSleepCycle(null);
    if (windowRef.current !== "boot") { windowRef.current = "boot"; setWindow("boot"); setData(null); void refresh("boot"); }
  };
  const recent = (data?.events || []).filter(e => e.severity !== "Info").slice(0, 5);
  const cycle = data?.sleepHistory?.cycles[0];
  return <>
    <PanelSection>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => void refresh()}>{busy ? "读取中…" : zh.refresh}</ButtonItem></PanelSectionRow>
      {error && <PanelSectionRow><p role="status" style={{ fontSize: 12, color: "#ffce70" }}>{error}</p></PanelSectionRow>}
    </PanelSection>
    {page === "home" ? <>
      {data && <>
        {data.deviceStatus.status !== "ok" && <PanelSection><PanelSectionRow><p>设备读取失败，请查看详情</p></PanelSectionRow></PanelSection>}
        {data.journalStatus.status !== "ok" && <PanelSection><PanelSectionRow><p style={{ fontSize: 12 }}>日志不可用，无法判断有无异常</p></PanelSectionRow></PanelSection>}
        {data.journalStatus.limited && <PanelSection><PanelSectionRow><p style={{ fontSize: 12 }}>日志不完整，计数仅覆盖已返回记录</p></PanelSectionRow></PanelSection>}
        <DeviceList devices={data.devices} selected={selected} busy={busy} readable={data.journalStatus.status === "ok"}
          onSelect={id => { setSelected(selected === id ? null : id); setDeviceFilter(id); }} />
        {device && <>
          <PanelSection title="设备操作">
            {device.partitions.filter(p => p.path !== device.id).map((p, i, parts) => <RemountControls
              key={p.path} partition={p} busy={busy} compact label={parts.length > 1 ? `重新挂载 · 分区 ${i + 1}` : "重新挂载"} onRemount={token => void remount(token)} />)}
          </PanelSection>
          <ReportControls revision={operation?.finishedAt ?? data?.refreshedAt} compact busy={busy} onBusy={onReportBusy} />
        </>}
        {selected && !device && <PanelSection><PanelSectionRow><p>所选设备已断开或不可用</p></PanelSectionRow></PanelSection>}
      </>}
      <OperationStatus operation={operation} busy={managing} />
      {data && <>
        <PanelSection title="最近存储异常">
          <PanelSectionRow><p style={{ fontSize: 13 }}>{data.journalStatus.status === "ok" ?
            `本次开机记录：错误 ${data.events.filter(e => e.severity === "Error").length} · 警告 ${data.events.filter(e => e.severity === "Warning").length}` : "异常数量未知"}</p></PanelSectionRow>
          {recent.map(event => <PanelSectionRow key={event.id}><ButtonItem layout="below" disabled={busy}
            description={time(event.timestamp)} onClick={() => details("logs")}>{event.summary}</ButtonItem></PanelSectionRow>)}
          {!recent.length && <PanelSectionRow><p style={{ fontSize: 12 }}>{data.journalStatus.status === "ok" ? "已读取日志中暂无异常；不代表设备健康" : "暂无可用记录"}</p></PanelSectionRow>}
        </PanelSection>
        <PanelSection title="最近休眠 / 唤醒"><PanelSectionRow><div style={{ fontSize: 12 }}>
          {cycle ? <>休眠 {time(cycle.start?.timestamp ?? null)}<br />唤醒 {time(cycle.wake?.timestamp ?? null)}（日志估计）</> : "暂无可配对记录"}
        </div></PanelSectionRow></PanelSection>
      </>}
      <PanelSection><PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => details(device ? "device" : "logs")}>查看详情</ButtonItem></PanelSectionRow></PanelSection>
      <Updates busy={busy} />
    </> : <>
      <PanelSection>
        <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={home}>返回主页</ButtonItem></PanelSectionRow>
        <PanelSectionRow><DropdownItem label="诊断详情" selectedOption={section} disabled={busy}
          rgOptions={[{ data: "device", label: "设备信息" }, { data: "logs", label: "内核异常日志" }, { data: "sleep", label: "休眠历史" }, { data: "reports", label: "诊断报告 / TXT" }]}
          onChange={option => setSection(option.data)} /></PanelSectionRow>
      </PanelSection>
      {section === "reports" && <ReportControls revision={operation?.finishedAt ?? data?.refreshedAt} busy={busy} onBusy={onReportBusy} />}
      {section === "device" && <>
        {device ? <DeviceDetail device={device} readable={data?.journalStatus.status === "ok"} busy={busy} onRemount={token => void remount(token)} /> : <PanelSection><PanelSectionRow><p>请在主页选择设备</p></PanelSectionRow></PanelSection>}
        <OperationStatus operation={operation} busy={managing} />
      </>}
      {(section === "logs" || section === "sleep") && <>
        <PanelSection><PanelSectionRow><DropdownItem label={zh.journal} selectedOption={window} disabled={busy}
          rgOptions={Object.entries(zh.windows).map(([data, label]) => ({ data, label }))}
          onChange={option => { const next = option.data as Window; windowRef.current = next; setWindow(next); setData(null); void refresh(next); }} /></PanelSectionRow></PanelSection>
        {data && <>
          <Status data={data} />
          {section === "sleep" && data.sleepHistory && <SleepHistory events={data.events} history={data.sleepHistory} selected={sleepCycle} onSelect={setSleepCycle} minutes={wakeMinutes} onMinutes={setWakeMinutes} />}
          <PanelSection title={zh.filter}>
            <PanelSectionRow><DropdownItem label={zh.overview} selectedOption={deviceFilter}
              rgOptions={[{ data: "all", label: zh.allDevices }, { data: "unassociated", label: zh.unassociated }, ...data.devices.map(d => ({ data: d.id, label: d.model || d.name }))]}
              onChange={option => setDeviceFilter(option.data)} /></PanelSectionRow>
            <PanelSectionRow><DropdownItem label={zh.logs} selectedOption={level}
              rgOptions={[{ data: "all", label: zh.allLevels }, ...Object.entries(zh.levels).map(([data, label]) => ({ data, label }))]}
              onChange={option => setLevel(option.data as Severity | "all")} /></PanelSectionRow>
          </PanelSection>
          <EventList events={filtered} />
        </>}
      </>}
    </>}
  </>;
}
