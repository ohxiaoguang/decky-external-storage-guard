import { useEffect, useRef, useState } from "react";
import { callable } from "@decky/api";
import { DialogButton, Focusable, GamepadButton, Navigation, ReactRouter } from "@decky/ui";
import { copyDiagnostic } from "../clipboard";
import { Logs } from "../types";

const getLogs = callable<[], Logs>("get_logs");
export const LOG_ROUTE = "/external-storage-guard/logs";
const cleanups = new Set<() => void>();
export function disposeLogViews() { cleanups.forEach(fn => fn()); cleanups.clear(); }

export function LogPage() {
  const [text, setText] = useState("");
  const [message, setMessage] = useState("");
  const [limited, setLimited] = useState(false);
  const [busy, setBusy] = useState(false);
  const running = useRef(false);
  const alive = useRef(true);
  const scroll = useRef<HTMLDivElement>(null);
  const location = ReactRouter.useLocation() as { pathname: string };
  const path = useRef(location.pathname);
  path.current = location.pathname;
  const leaving = useRef(false);
  const back = () => {
    if (!alive.current || leaving.current) return;
    leaving.current = true;
    Navigation.NavigateBack();
  };
  const refresh = async () => {
    if (running.current || !alive.current) return;
    running.current = true; setBusy(true); setMessage("读取中…");
    try {
      const result = await getLogs();
      if (!alive.current) return;
      if (result.status === "ok" || result.status === "no_logs") {
        setText(result.text); setLimited(result.limited); setMessage(result.message === "日志已截断" ? "" : result.message);
      } else { if (result.limited) setLimited(true); setMessage(result.message || "日志读取失败"); }
    } catch { if (alive.current) setMessage("日志读取失败；保留上次内容"); }
    finally { running.current = false; if (alive.current) setBusy(false); }
  };
  const copy = async () => {
    if (running.current || !text || !alive.current) return;
    running.current = true; setBusy(true);
    try { await copyDiagnostic(text); if (alive.current) setMessage("已复制全部显示日志"); }
    catch (error) { if (alive.current) setMessage(error instanceof Error ? error.message : "复制失败"); }
    finally { running.current = false; if (alive.current) setBusy(false); }
  };
  useEffect(() => {
    alive.current = true;
    const stop = () => { if (path.current === LOG_ROUTE) back(); alive.current = false; };
    cleanups.add(stop); void refresh();
    return () => { alive.current = false; cleanups.delete(stop); };
  }, []);
  useEffect(() => { if (location.pathname === LOG_ROUTE) leaving.current = false; }, [location.pathname]);
  return <Focusable onCancel={event => { event.preventDefault(); event.stopPropagation(); back(); }}
    style={{ position: "absolute", inset: 0, boxSizing: "border-box", display: "flex", flexDirection: "column", gap: 16,
      padding: "clamp(48px, 7vh, 80px) clamp(16px, 4vw, 64px) clamp(48px, 8vh, 88px)", overflow: "hidden", background: "#101822", color: "#dce1e7" }}>
      <h2 style={{ margin: 0, fontSize: "clamp(18px, 2vw, 26px)" }}>External Storage Guard · 系统日志</h2>
      <Focusable flow-children="row" style={{ display: "flex", gap: 12, flexShrink: 0 }}>
        <DialogButton preferredFocus style={{ minWidth: 0, maxWidth: 200, flex: 1, padding: "10px 16px" }} onClick={back}>返回</DialogButton>
        <DialogButton style={{ minWidth: 0, maxWidth: 200, flex: 1, padding: "10px 16px" }} disabled={busy} onClick={() => void refresh()}>刷新</DialogButton>
        <DialogButton style={{ minWidth: 0, maxWidth: 200, flex: 1, padding: "10px 16px" }} disabled={busy || !text} onClick={() => void copy()}>复制</DialogButton>
      </Focusable>
      {(message || limited) && <div role="status" style={{ fontSize: 12 }}>{limited ? "日志已截断 · " : ""}{message}</div>}
      <Focusable ref={scroll} tabIndex={0} style={{ overflowY: "auto", overflowX: "hidden", flex: 1, minHeight: 0, minWidth: 0, touchAction: "pan-y", background: "#080e16", padding: 16 }}
        onCancel={event => { event.preventDefault(); event.stopPropagation(); back(); }}
        onGamepadDirection={event => {
          const element = scroll.current;
          const amount = event.detail.button === GamepadButton.DIR_DOWN ? 120 : event.detail.button === GamepadButton.DIR_UP ? -120 : 0;
          if (element && ((amount > 0 && element.scrollTop + element.clientHeight < element.scrollHeight) || (amount < 0 && element.scrollTop > 0))) {
            event.preventDefault(); event.stopPropagation(); element.scrollBy({ top: amount });
          }
        }}
        onActivate={() => scroll.current?.scrollBy({ top: 260 })}
        onKeyDown={event => {
          const amount = { ArrowDown: 80, ArrowUp: -80, PageDown: 320, PageUp: -320 }[event.key];
          if (amount) { event.preventDefault(); scroll.current?.scrollBy({ top: amount }); }
        }}>
        <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: "clamp(13px, 1.25vw, 19px)", lineHeight: 1.6, margin: 0 }}>{text}</pre>
      </Focusable>
  </Focusable>;
}
