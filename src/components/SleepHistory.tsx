import { useEffect, useState } from "react";
import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { SleepHistory as History } from "../types";
import { zh, time } from "../strings";

export function SleepHistory({ history, selected, onSelect, minutes, onMinutes }: {
  history: History; selected: string | null; onSelect: (id: string | null) => void;
  minutes: number; onMinutes: (value: number) => void;
}) {
  const [page, setPage] = useState(0);
  useEffect(() => { setPage(0); }, [history]);
  const pages = Math.ceil(history.cycles.length / 10);
  return <PanelSection title={zh.sleep}>
    <PanelSectionRow><div style={{ fontSize: 12, lineHeight: 1.5 }}>
      <p>{zh.causal}</p>
      {history.status !== "ok" && <p>{history.status === "no_records" ? zh.sleepMissing : zh.sleepUnavailable} ({history.status})</p>}
      {history.limited && <p style={{ color: "#ffce70" }}>{zh.sleepLimited}</p>}
    </div></PanelSectionRow>
    <PanelSectionRow><DropdownItem label={zh.afterWindow} selectedOption={minutes}
      rgOptions={[1, 5, 10].map(data => ({ data, label: `${data} min` }))}
      onChange={option => onMinutes(option.data)} /></PanelSectionRow>
    {selected && <PanelSectionRow><ButtonItem layout="below" onClick={() => onSelect(null)}>{zh.allSleepEvents}</ButtonItem></PanelSectionRow>}
    {history.cycles.slice(page * 10, (page + 1) * 10).map(cycle => <PanelSectionRow key={cycle.id}>
      <ButtonItem layout="below" onClick={() => onSelect(selected === cycle.id ? null : cycle.id)}
        description={<div style={{ whiteSpace: "normal", overflowWrap: "anywhere", fontSize: 12 }}>
          <div>{zh.sleepStart}：{time(cycle.start?.timestamp ?? null)}</div>
          <div>{zh.wakeEnd}：{time(cycle.wake?.timestamp ?? null)} · {zh.estimated}</div>
          <div>{zh.boot}：{cycle.bootId}</div>
          {cycle.observations.length > 0 && <div>{zh.sleepObservations}：{cycle.observations.map(kind => zh.eventKinds[kind] || kind).join(" · ")}</div>}
          {selected === cycle.id && <>
            {cycle.notes.map(note => <p key={note}>{note}</p>)}
            {cycle.records.map((record, i) => <pre key={i} style={{ whiteSpace: "pre-wrap" }}>{time(record.timestamp)} {record.message}</pre>)}
            {cycle.traceLimited && <p>{zh.sleepLimited}</p>}
          </>}
        </div>}>
        {zh.sleepStates[cycle.status] || cycle.status} · {minutes} min · {cycle.afterCounts[String(minutes)] || 0} {zh.logs}
      </ButtonItem>
    </PanelSectionRow>)}
    {pages > 1 && <>
      <PanelSectionRow><ButtonItem layout="below" disabled={page === 0} onClick={() => setPage(page - 1)}>{zh.prev}</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>{zh.more} ({page + 1}/{pages})</ButtonItem></PanelSectionRow>
    </>}
  </PanelSection>;
}
