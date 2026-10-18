import { useEffect, useRef } from "react";
import { ButtonItem, ConfirmModal, PanelSectionRow, showModal, ShowModalResult } from "@decky/ui";
import { Partition } from "../types";
import { zh } from "../strings";

export function RemountControls({ partition, busy, onRemount }: {
  partition: Partition; busy: boolean; onRemount: (token: string) => void;
}) {
  const modal = useRef<ShowModalResult | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; modal.current?.Close(); modal.current = null; };
  }, []);
  const management = partition.management;
  const confirm = () => {
    if (busy || modal.current || !management?.eligible || !management.token) return;
    let settled = false;
    const close = () => { modal.current?.Close(); modal.current = null; };
    const dismiss = () => { settled = true; close(); };
    modal.current = showModal(<ConfirmModal
      strTitle={`${zh.confirmRemount} · ${partition.path}`}
      strDescription={<div><p>{zh.remountWarning}</p>
        {management.warnings.map(w => <p key={w} style={{ color: "#ffce70" }}>{w}</p>)}
        <p>{zh.noRepair}</p></div>}
      strOKButtonText={zh.confirmRemount} strCancelButtonText={zh.cancel}
      bDestructiveWarning={true}
      onOK={() => {
        if (settled || !alive.current) return;
        settled = true; close(); onRemount(management.token!);
      }}
      onCancel={dismiss} closeModal={dismiss}
    />);
    const opened = modal.current;
    void opened.ClosedPromise.then(() => { settled = true; if (modal.current === opened) modal.current = null; });
  };
  return <PanelSectionRow>
    <ButtonItem layout="below" disabled={busy || !management?.eligible}
      description={management?.eligible ? zh.noRepair : management?.reason || zh.manageUnavailable}
      onClick={confirm}>{zh.remount} · {partition.name}</ButtonItem>
    {management?.warnings.map(w => <p key={w} style={{ color: "#ffce70", fontSize: 13 }}>{w}。{zh.noRepair}</p>)}
  </PanelSectionRow>;
}
