import { useEffect, useState } from "react";
import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { SleepHistory as History, StorageEvent } from "../types";
import { zh, time } from "../strings";

export function SleepHistory({ history, selected, onSelect, minutes, onMinutes, events = [] }: {
  history: History; selected: string | null; onSelect: (id: string | null) => void;
  events?: StorageEvent[];
  minutes: number; onMinutes: (value: number) => void;
}) {
  const [page, setPage] = useState(0);
  useEffect(() => { setPage(0); }, [history]);
  const [timelinePage, setTimelinePage] = useState(0);
  useEffect(() => { setTimelinePage(0); }, [selected, history]);
  const cycle = history.cycles.find(c => c.id === selected);
  const timeline = cycle?.timeline || [];
  const eventMap = new Map(events.map(event => [event.id, event]));
  const phases: Record<string, string> = { before_suspend: "休眠前", during_unknown: "进入 / 恢复期间，时序不确定", after_wake: "唤醒后", boundary: "休眠 / 唤醒依据" };
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
            {!cycle.timeline && cycle.records.map((record, i) => <pre key={i} style={{ whiteSpace: "pre-wrap" }}>{time(record.timestamp)} {record.message}</pre>)}
            {!cycle.timeline && cycle.traceLimited && <p>{zh.sleepLimited}</p>}
          </>}
        </div>}>
        {zh.sleepStates[cycle.status] || cycle.status} · {minutes} min · {cycle.afterCounts[String(minutes)] || 0} {zh.logs}
      </ButtonItem>
    </PanelSectionRow>)}
    {cycle && <>
      <PanelSectionRow><p style={{ fontSize: 12 }}>周期时间线：前 5 分钟、进入期间、后 10 分钟。仅已返回日志，时序为估计；缓冲 / 接收延迟可能改变边界，不代表因果。</p></PanelSectionRow>
      {timeline.slice(timelinePage * 20, (timelinePage + 1) * 20).map((item, index) => {
        const event = item.eventId ? eventMap.get(item.eventId) : undefined;
        return <PanelSectionRow key={`${selected}-${timelinePage}-${index}`}><div style={{ fontSize: 12, overflowWrap: "anywhere" }}>
          <div>{time(item.timestamp)} · {phases[item.phase] || item.phase} · {zh.eventKinds[item.kind] || item.kind}（估计）</div>
          <pre style={{ whiteSpace: "pre-wrap" }}>{item.message || event?.raw || "原始事件不在当前返回列表中，请查看完整报告"}</pre>
        </div></PanelSectionRow>;
      })}
      {timelinePage > 0 && <PanelSectionRow><ButtonItem layout="below" onClick={() => setTimelinePage(timelinePage - 1)}>时间线上一页</ButtonItem></PanelSectionRow>}
      {(timelinePage + 1) * 20 < timeline.length && <PanelSectionRow><ButtonItem layout="below" onClick={() => setTimelinePage(timelinePage + 1)}>时间线下一页 ({timelinePage + 1}/{Math.ceil(timeline.length / 20)})</ButtonItem></PanelSectionRow>}
    </>}
    {pages > 1 && <>
      <PanelSectionRow><ButtonItem layout="below" disabled={page === 0} onClick={() => setPage(page - 1)}>{zh.prev}</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>{zh.more} ({page + 1}/{pages})</ButtonItem></PanelSectionRow>
    </>}
  </PanelSection>;
}
