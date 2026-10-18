import { useEffect, useState } from "react";
import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { StorageEvent } from "../types";
import { zh, time } from "../strings";

export function EventList({ events }: { events: StorageEvent[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  useEffect(() => { setPage(0); setExpanded(null); }, [events]);
  const pages = Math.ceil(events.length / 20);
  return <PanelSection title={`${zh.logs} · ${events.length}`}>
    {!events.length && <PanelSectionRow><p>{zh.noEvents}</p></PanelSectionRow>}
    {events.slice(page * 20, (page + 1) * 20).map(e => <PanelSectionRow key={e.id}>
      <ButtonItem layout="below" onClick={() => setExpanded(expanded === e.id ? null : e.id)}
        description={<div style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>
          <div>{time(e.timestamp)} · {e.deviceLabel || zh.unassociated}</div>
          <div>{zh.kind}：{zh.eventKinds[e.kind] || e.kind} · {zh.refs}：{e.references.join(", ") || zh.unavailable}</div>
          {e.wakeContext && <div>
            {e.wakeContext.phase === "after_wake" ? `${zh.afterWake}${e.wakeContext.estimated ? zh.estimated : ""} ${Math.round(e.wakeContext.delaySeconds || 0)} ${zh.seconds}` :
              e.wakeContext.phase === "before_suspend" ? zh.beforeSleep : e.wakeContext.phase === "during_unknown" ? zh.duringSleep : zh.wakeUnknown}
            {e.wakeContext.clockAdjusted && ` · ${zh.clockAdjusted}`}
            {e.wakeContext.beforeNextSuspend && ` · ${zh.beforeNextSleep}`}
          </div>}
          {expanded === e.id ? <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{e.raw}</pre> : zh.raw}
        </div>}>
        <span style={{ color: e.severity === "Error" ? "#ff9a9a" : e.severity === "Warning" ? "#ffce70" : undefined }}>
          {zh.levels[e.severity]} · {e.summary}
        </span>
      </ButtonItem>
    </PanelSectionRow>)}
    {pages > 1 && <>
      <PanelSectionRow><p>{page + 1} / {pages} {zh.page}</p></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={page === 0} onClick={() => setPage(page - 1)}>{zh.prev}</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>{zh.more}</ButtonItem></PanelSectionRow>
    </>}
  </PanelSection>;
}
