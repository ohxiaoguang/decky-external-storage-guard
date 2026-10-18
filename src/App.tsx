import { useEffect, useRef, useState } from "react";
import { callable } from "@decky/api";
import { ButtonItem, ConfirmModal, PanelSection, PanelSectionRow, showModal, ShowModalResult } from "@decky/ui";
import { Action, Device, Operation, OperationResponse, Partition, Snapshot } from "./types";
import { size } from "./strings";
import { Updates } from "./components/Updates";
import { LogModal } from "./components/LogModal";

const getSnapshot = callable<[], Snapshot>("get_snapshot");
const mountPartition = callable<[token: string], OperationResponse>("mount_partition");
const unmountPartition = callable<[token: string], OperationResponse>("unmount_partition");
const cleanups = new Set<() => void>();
export function disposeViews() { cleanups.forEach(fn => fn()); cleanups.clear(); }

function DeviceCard({ device, busy, operate, confirm }: {
  device: Device; busy: boolean; operate: (action: Action, token: string) => void; confirm: (part: Partition) => void;
}) {
  const parts = device.partitions.filter(part => part.path !== device.id);
  return <PanelSection title={`${device.model || (device.kind === "SD" ? "MicroSD" : device.kind)} · ${size(device.size)}`}>
    {!parts.length && <PanelSectionRow><p>{device.mounted ? "已挂载" : "未挂载"} · {device.readOnly ? "只读" : "—"} · 无可操作分区</p></PanelSectionRow>}
    {parts.map(part => <PanelSectionRow key={part.path}><div style={{ fontSize: 13, lineHeight: 1.6 }}>
      <div>{part.name} · {part.filesystem || "未知文件系统"} · {size(part.size)}</div>
      <div>{part.mounts.length ? "已挂载" : "未挂载"} · {part.readOnly || part.mounts.some(m => m.readOnly) ? "只读" : part.mounts.length ? "可读写" : "读写状态待挂载确认"}</div>
      <ButtonItem layout="below" disabled={busy || part.mounts.length !== 1 || !part.actions?.unmount?.token} onClick={() => confirm(part)}>卸载</ButtonItem>
      <ButtonItem layout="below" disabled={busy || part.mounts.length > 0 || !part.actions?.mount?.token}
        onClick={() => { const token = part.actions?.mount?.token; if (token && part.mounts.length === 0) operate("mount", token); }}>挂载</ButtonItem>
      {!part.actions?.mount?.token && !part.actions?.unmount?.token && <div style={{ fontSize: 12 }}>{(part.mounts.length ? part.actions?.unmount?.reason : part.actions?.mount?.reason) || "该分区不可操作"}</div>}
    </div></PanelSectionRow>)}
  </PanelSection>;
}

export function App() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const running = useRef(false);
  const alive = useRef(true);
  const confirmation = useRef<ShowModalResult | null>(null);
  const logs = useRef<ShowModalResult | null>(null);
  const apply = (snapshot: Snapshot | null) => {
    if (!snapshot || snapshot.deviceStatus.status !== "ok") return false;
    setDevices(snapshot.devices); // Stable device/partition keys preserve the page.
    return true;
  };
  const describe = (operation: Operation) => {
    const name = operation.action === "unmount" ? "卸载" : "挂载";
    const target = operation.target?.split("/").pop() || "";
    if (operation.status === "success" && operation.verified) {
      const mounts = operation.mounts?.map(m => m.target).join(", ");
      return `${name}成功 ${target}${operation.action === "mount" ? ` · ${mounts || ""} · ${operation.readOnly ? "只读" : "可读写"}` : ""}`;
    }
    return `${operation.status === "uncertain" || operation.status === "success" ? "不确定" : "失败"}：${operation.message}`;
  };
  const refresh = async () => {
    if (running.current || !alive.current) return;
    running.current = true; setBusy(true);
    try {
      const snapshot = await getSnapshot();
      if (!alive.current) return;
      if (!apply(snapshot)) setMessage(snapshot.deviceStatus.message);
      else if (snapshot.lastOperation) setMessage(describe(snapshot.lastOperation));
      else setMessage("");
    } catch { if (alive.current) setMessage("设备读取失败；保留当前页面"); }
    finally { running.current = false; if (alive.current) setBusy(false); }
  };
  const operate = async (action: Action, token: string) => {
    if (running.current || !alive.current) return;
    running.current = true; setBusy(true); setMessage("操作中…");
    try {
      const result = await (action === "mount" ? mountPartition(token) : unmountPartition(token));
      if (!alive.current) return;
      apply(result.snapshot);
      setMessage(describe(result.operation));
    } catch { if (alive.current) setMessage("不确定：通信中断，请等待后刷新核对；当前页面已保留"); }
    finally { running.current = false; if (alive.current) setBusy(false); }
  };
  const confirm = (part: Partition) => {
    if (running.current || confirmation.current || part.mounts.length !== 1 || !part.actions?.unmount?.token) return;
    let settled = false;
    const finish = () => { confirmation.current?.Close(); confirmation.current = null; };
    const dismiss = () => { settled = true; finish(); };
    confirmation.current = showModal(<ConfirmModal strTitle={`卸载 ${part.name}`} bDestructiveWarning
      strDescription="请先关闭使用该分区的游戏和程序。卸载后不会自动挂载，也不代表 USB 设备已经断电。"
      strOKButtonText="卸载" strCancelButtonText="取消" onCancel={dismiss} closeModal={dismiss}
      onOK={() => { if (settled || !alive.current) return; settled = true; finish(); void operate("unmount", part.actions.unmount.token!); }} />);
    const opened = confirmation.current;
    void opened.ClosedPromise.then(() => { settled = true; if (confirmation.current === opened) confirmation.current = null; });
  };
  const openLogs = () => {
    if (logs.current) return;
    const closeModal = () => { logs.current?.Close(); logs.current = null; };
    logs.current = showModal(<LogModal closeModal={closeModal} />, undefined, { bNeverPopOut: true });
    const opened = logs.current;
    void opened.ClosedPromise.then(() => { if (logs.current === opened) logs.current = null; });
  };
  useEffect(() => {
    alive.current = true;
    const stop = () => { alive.current = false; confirmation.current?.Close(); logs.current?.Close(); };
    cleanups.add(stop); void refresh();
    return () => { stop(); cleanups.delete(stop); };
  }, []);
  return <>
    <PanelSection><PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => void refresh()}>{busy ? "处理中…" : "刷新"}</ButtonItem></PanelSectionRow>
      {message && <PanelSectionRow><p role="status" style={{ fontSize: 13, overflowWrap: "anywhere" }}>{message}</p></PanelSectionRow>}
    </PanelSection>
    {devices.map(device => <DeviceCard key={device.id} device={device} busy={busy} operate={(action, token) => void operate(action, token)} confirm={confirm} />)}
    {!devices.length && !busy && <PanelSection><PanelSectionRow><p>暂无可确认的外部存储</p></PanelSectionRow></PanelSection>}
    <PanelSection>
      <PanelSectionRow><ButtonItem layout="below" onClick={openLogs}>查看日志</ButtonItem></PanelSectionRow>
      <Updates busy={busy} />
    </PanelSection>
  </>;
}
