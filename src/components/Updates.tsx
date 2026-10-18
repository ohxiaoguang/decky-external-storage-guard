import { useEffect, useRef, useState } from "react";
import { ButtonItem, PanelSectionRow } from "@decky/ui";
import { repository } from "../../package.json";
import { copyDiagnostic } from "../clipboard";

const UPDATE_URL = repository.url.replace(/\.git$/, "") + "/releases/latest/download/External-Storage-Guard.zip";
export function Updates({ busy }: { busy: boolean }) {
  const [message, setMessage] = useState("");
  const [copying, setCopying] = useState(false);
  const running = useRef(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const copy = async () => {
    if (busy || running.current) return;
    running.current = true; setCopying(true); setMessage("");
    try { await copyDiagnostic(UPDATE_URL); if (alive.current) setMessage("已复制更新链接"); }
    catch { if (alive.current) setMessage("复制失败，请重试"); }
    finally { running.current = false; if (alive.current) setCopying(false); }
  };
  return <>
    <PanelSectionRow><ButtonItem layout="below" disabled={busy || copying} onClick={() => void copy()}>{copying ? "复制中…" : "复制更新链接"}</ButtonItem></PanelSectionRow>
    {message && <PanelSectionRow><p role="status" style={{ fontSize: 12 }}>{message}</p></PanelSectionRow>}
  </>;
}
