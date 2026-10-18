import { useEffect, useRef, useState } from "react";
import { callable, useQuickAccessVisible } from "@decky/api";
import { ButtonItem, PanelSection, PanelSectionRow, Router } from "@decky/ui";
import { Action, Device, Operation, OperationResponse, Partition, Snapshot } from "./types";
import { size } from "./strings";
import { Updates } from "./components/Updates";
import { LOG_ROUTE } from "./components/LogPage";

const getSnapshot = callable<[], Snapshot>("get_snapshot");
const mountPartition = callable<[token: string], OperationResponse>("mount_partition");
const unmountPartition = callable<[token: string], OperationResponse>("unmount_partition");
const cleanups = new Set<() => void>();
export function disposeViews() { cleanups.forEach(fn => fn()); cleanups.clear(); }
type Confirmation = { path: string; token: string; expires: number };
type Working = { action: Action; path: string } | null;

function DeviceCard({ device, busy, working, armed, operate, unmount, cancel, focus }: {
  device: Device; busy: boolean; working: Working; armed: string | undefined;
  operate: (action: Action, part: Partition) => void; unmount: (part: Partition, confirmed: boolean) => void;
  cancel: () => void; focus: (path: string) => void;
}) {
  const parts = device.partitions.filter(part => part.path !== device.id);
  return <PanelSection title={`${device.model || (device.kind === "SD" ? "MicroSD" : device.kind)} · ${size(device.size)}`}>
    {!parts.length && <PanelSectionRow><p>{device.mounted ? "已挂载" : "未挂载"} · {device.readOnly ? "只读" : "—"} · 无可操作分区</p></PanelSectionRow>}
    {parts.map(part => <PanelSectionRow key={part.path}><div onFocusCapture={() => focus(part.path)} style={{ fontSize: 13, lineHeight: 1.6 }}>
      <div>{part.name} · {part.filesystem || "未知文件系统"} · {size(part.size)}</div>
      <div>{part.mounts.length ? "已挂载" : "未挂载"} · {part.readOnly || part.mounts.some(m => m.readOnly) ? "只读" : part.mounts.length ? "可读写" : "读写状态待挂载确认"}</div>
      <ButtonItem layout="below" disabled={busy || part.mounts.length !== 1 || !part.actions?.unmount?.token}
        onClick={() => unmount(part, armed === part.path)}>
        {working?.path === part.path && working.action === "unmount" ? "卸载中…" : armed === part.path ? "确认卸载" : "卸载"}
      </ButtonItem>
      {armed === part.path && <>
        <div style={{ color: "#e9b85c", fontSize: 12 }}>请先关闭使用该分区的游戏和程序</div>
        <ButtonItem layout="below" onClick={cancel}>取消</ButtonItem>
      </>}
      <ButtonItem layout="below" disabled={busy || part.mounts.length > 0 || !part.actions?.mount?.token}
        onClick={() => operate("mount", part)}>{working?.path === part.path && working.action === "mount" ? "挂载中…" : "挂载"}</ButtonItem>
      {!part.actions?.mount?.token && !part.actions?.unmount?.token && <div style={{ fontSize: 12 }}>{(part.mounts.length ? part.actions?.unmount?.reason : part.actions?.mount?.reason) || "该分区不可操作"}</div>}
    </div></PanelSectionRow>)}
  </PanelSection>;
}

export function App() {
  // alwaysRender keeps this home mounted when the full-screen route closes QAM.
  const [devices, setDevices] = useState<Device[]>([]);
  const [busy, setBusy] = useState(false);
  const [working, setWorking] = useState<Working>(null);
  const [message, setMessage] = useState("");
  const visible = useQuickAccessVisible();
  const homeVisible = useRef(visible);
  const [armed, setArmed] = useState<Confirmation | null>(null);
  const running = useRef(false);
  const alive = useRef(true);
  const currentDevices = useRef<Device[]>([]);
  const confirmation = useRef<Confirmation | null>(null);
  const expiry = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearConfirmation = () => {
    confirmation.current = null;
    if (expiry.current !== null) clearTimeout(expiry.current);
    expiry.current = null;
  };
  const cancel = () => { clearConfirmation(); if (alive.current) setArmed(null); };
  const apply = (snapshot: Snapshot | null) => {
    if (!snapshot || snapshot.deviceStatus.status !== "ok") return false;
    cancel(); // A fresh scan replaces action tokens and invalidates any old confirmation.
    currentDevices.current = snapshot.devices;
    setDevices(snapshot.devices);
    return true;
  };
  const describe = (operation: Operation, snapshot: Snapshot | null) => {
    const name = operation.action === "unmount" ? "卸载" : "挂载";
    const target = operation.target?.split("/").pop() || "";
    if (operation.status === "success" && operation.verified) {
      const actual = snapshot?.deviceStatus.status === "ok" && snapshot.devices.flatMap(d => d.partitions).find(p => p.path === operation.target);
      if (!actual || (operation.action === "unmount" ? actual.mounts.length !== 0 : actual.mounts.length !== 1))
        return "操作结果不确定，请刷新确认：设备列表未能确认操作后的状态";
      return `${name}成功 ${target}${operation.action === "mount" ? ` · ${actual.mounts.map(m => m.target).join(", ")} · ${actual.readOnly || actual.mounts.some(m => m.readOnly) ? "只读" : "可读写"}` : ""}`;
    }
    return operation.status === "uncertain" || operation.status === "success"
      ? `操作结果不确定，请刷新确认：${operation.message}` : `失败：${operation.message}`;
  };
  const refresh = async () => {
    if (running.current || !alive.current) return;
    cancel(); running.current = true; setBusy(true);
    try {
      const snapshot = await getSnapshot();
      if (!alive.current) return;
      if (!apply(snapshot)) setMessage(snapshot.deviceStatus.message);
      else if (snapshot.lastOperation) setMessage(describe(snapshot.lastOperation, snapshot));
      else setMessage("");
    } catch { if (alive.current) setMessage("设备读取失败；保留当前页面"); }
    finally { running.current = false; if (alive.current) setBusy(false); }
  };
  const currentPart = (action: Action, part: Partition) => {
    const actual = currentDevices.current.flatMap(d => d.partitions).find(p => p.path === part.path);
    const token = part.actions?.[action]?.token;
    return token && actual?.actions?.[action]?.token === token && (action === "unmount" ? actual.mounts.length === 1 : actual.mounts.length === 0) ? token : null;
  };
  const operate = async (action: Action, part: Partition) => {
    if (running.current || !alive.current || !homeVisible.current) return;
    const token = currentPart(action, part);
    cancel();
    if (!token) { setMessage("设备状态已变化，请刷新后重试"); return; }
    running.current = true; setBusy(true); setWorking({ action, path: part.path });
    setMessage(action === "unmount" ? "卸载中…" : "挂载中…");
    try {
      const result = await (action === "mount" ? mountPartition(token) : unmountPartition(token));
      if (!alive.current) return;
      if (!result?.operation || result.operation.action !== action) {
        setMessage("操作结果不确定，请刷新确认：接口返回不兼容，请检查插件版本");
        return;
      }
      apply(result.snapshot);
      setMessage(describe(result.operation, result.snapshot));
    } catch (error) {
      if (alive.current) setMessage(`操作结果不确定，请刷新确认：${error instanceof Error ? error.message.slice(0, 300) : "通信中断或接口异常"}；当前页面已保留`);
    }
    finally { running.current = false; if (alive.current) { setBusy(false); setWorking(null); } }
  };
  const unmount = (part: Partition, confirmed: boolean) => {
    if (running.current || !alive.current || !homeVisible.current) return;
    const token = currentPart("unmount", part);
    const pending = confirmation.current;
    if (confirmed) {
      cancel();
      if (token && pending?.path === part.path && pending.token === token && pending.expires > Date.now()) void operate("unmount", part);
      return;
    }
    cancel();
    if (!token) return;
    const next = { path: part.path, token, expires: Date.now() + 15000 };
    confirmation.current = next; setArmed(next);
    expiry.current = setTimeout(cancel, 15000);
  };
  const openLogs = () => {
    if (running.current || !alive.current) return;
    cancel();
    homeVisible.current = false; // Block queued home callbacks before QAM visibility updates.
    try { Router.CloseSideMenus(); Router.Navigate(LOG_ROUTE); }
    catch (error) { homeVisible.current = visible; setMessage(`日志页面打开失败：${error instanceof Error ? error.message : "导航不可用"}`); }
  };
  useEffect(() => { homeVisible.current = visible; if (!visible) cancel(); }, [visible]);
  useEffect(() => {
    alive.current = true;
    const stop = () => { alive.current = false; clearConfirmation(); };
    cleanups.add(stop); void refresh();
    return () => { stop(); cleanups.delete(stop); };
  }, []);
  return <>
    <PanelSection><PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => void refresh()}>{busy ? "处理中…" : "刷新"}</ButtonItem></PanelSectionRow>
      {message && <PanelSectionRow><p role="status" style={{ fontSize: 13, overflowWrap: "anywhere" }}>{message}</p></PanelSectionRow>}
    </PanelSection>
    {devices.map(device => <DeviceCard key={device.id} device={device} busy={busy} working={working} armed={armed?.path}
      operate={(action, part) => void operate(action, part)} unmount={unmount} cancel={cancel}
      focus={path => { if (confirmation.current && confirmation.current.path !== path) cancel(); }} />)}
    {!devices.length && !busy && <PanelSection><PanelSectionRow><p>暂无可确认的外部存储</p></PanelSectionRow></PanelSection>}
    <PanelSection>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={openLogs}>查看日志</ButtonItem></PanelSectionRow>
      <Updates busy={busy} />
    </PanelSection>
  </>;
}
