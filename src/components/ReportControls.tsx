import { useEffect, useRef, useState } from "react";
import { callable } from "@decky/api";
import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { DiagnosticReport, Window } from "../types";
import { copyDiagnostic } from "../clipboard";
import { zh, time } from "../strings";

const getReport = callable<[window: Window], DiagnosticReport>("get_report");
const exportReport = callable<[reportId: string], { status: string; message?: string; path?: string }>("export_report");

export function ReportControls({ busy, onBusy, compact = false, revision }: { busy: boolean; onBusy: (value: boolean) => void; compact?: boolean; revision?: number }) {
  const [range, setRange] = useState<Window>("boot");
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  const [report, setReport] = useState<DiagnosticReport | null>(null);
  const cache = useRef<{ window: Window; report: DiagnosticReport; created: number; revision?: number } | null>(null);
  const running = useRef(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const act = async (action: "copy" | "summary" | "export") => {
    if (busy || running.current || !alive.current) return;
    running.current = true; setWorking(true); setMessage(""); onBusy(true);
    try {
      let next = cache.current?.window === range && cache.current.revision === revision && Date.now() >= cache.current.created && Date.now() - cache.current.created < 60000 ? cache.current.report : null;
      if (!next) next = await getReport(range);
      if (!alive.current) return;
      if (next.status !== "ok" || !next.reportId || !next.text || !next.summary) throw new Error(next.message || zh.reportFailure);
      cache.current = { window: range, report: next, created: Date.now(), revision };
      setReport(next);
      if (action === "export") {
        const output = await exportReport(next.reportId);
        if (output.status === "report_expired") cache.current = null;
        if (output.status !== "ok" || !output.path) throw new Error(output.message || zh.reportFailure);
        if (alive.current) setMessage(`${zh.reportSaved}：${output.path}`);
      } else {
        await copyDiagnostic(action === "summary" ? next.summary : next.text);
        if (alive.current) setMessage(zh.reportCopied);
      }
    } catch (error) {
      if (alive.current) setMessage(error instanceof Error ? error.message : zh.reportFailure);
    } finally {
      running.current = false;
      if (alive.current) { setWorking(false); onBusy(false); }
    }
  };
  if (compact) return <PanelSection>
    <PanelSectionRow><ButtonItem layout="below" disabled={busy || working} onClick={() => void act("copy")}>{working ? zh.reportBusy : zh.copyReport}</ButtonItem></PanelSectionRow>
    {message && <PanelSectionRow><p role="status" style={{ fontSize: 12 }}>{message}</p></PanelSectionRow>}
  </PanelSection>;
  return <PanelSection title={zh.reports}>
    <PanelSectionRow><DropdownItem label={zh.reportRange} selectedOption={range} disabled={busy || working}
      rgOptions={(["boot", "day", "week", "all"] as const).map(data => ({ data, label: zh.windows[data] }))}
      onChange={option => { setRange(option.data); cache.current = null; setReport(null); setMessage(""); }} /></PanelSectionRow>
    {([['copy', zh.copyReport], ['summary', zh.copySummary], ['export', zh.exportTxt]] as const).map(([action, label]) =>
      <PanelSectionRow key={action}><ButtonItem layout="below" disabled={busy || working}
        onClick={() => void act(action)}>{working ? zh.reportBusy : label}</ButtonItem></PanelSectionRow>)}
    <PanelSectionRow><div style={{ fontSize: 12, lineHeight: 1.5, overflowWrap: "anywhere" }}>
      <p>{zh.reportPrivacy}</p><p>{zh.reportLimit}</p>
      {report && <p>{time(report.generatedAt || null)} · {((report.size || 0) / 1024).toFixed(1)} KiB · {report.truncated ? zh.reportTruncated : zh.reportComplete}</p>}
      {message && <p role="status">{message}</p>}
    </div></PanelSectionRow>
  </PanelSection>;
}
