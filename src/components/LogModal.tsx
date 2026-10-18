import { useEffect, useRef, useState } from "react";
import { callable } from "@decky/api";
import { DialogButton, Focusable, GamepadButton, ModalRoot } from "@decky/ui";
import { copyDiagnostic } from "../clipboard";
import { Logs } from "../types";

const getLogs = callable<[], Logs>("get_logs");
export function LogModal({ closeModal }: { closeModal: () => void }) {
  const [text, setText] = useState("");
  const [message, setMessage] = useState("");
  const [limited, setLimited] = useState(false);
  const [busy, setBusy] = useState(false);
  const running = useRef(false);
  const alive = useRef(true);
  const scroll = useRef<HTMLDivElement>(null);
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
  useEffect(() => { alive.current = true; void refresh(); return () => { alive.current = false; }; }, []);
  return <ModalRoot bAllowFullSize bHideCloseIcon onCancel={closeModal} closeModal={closeModal}>
    <div style={{ width: "92vw", height: "84vh", maxWidth: "none", display: "flex", flexDirection: "column", gap: 10 }}>
      <Focusable flow-children="row" style={{ display: "flex", gap: 8 }}>
        <DialogButton disabled={busy} onClick={() => void refresh()}>刷新</DialogButton>
        <DialogButton disabled={busy || !text} onClick={() => void copy()}>复制</DialogButton>
        <DialogButton onClick={closeModal}>关闭</DialogButton>
      </Focusable>
      {(message || limited) && <div role="status" style={{ fontSize: 12 }}>{limited ? "日志已截断 · " : ""}{message}</div>}
      <Focusable ref={scroll} tabIndex={0} style={{ overflowY: "auto", flex: 1, minHeight: 0 }}
        onCancel={closeModal}
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
        <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: 13, lineHeight: 1.5, margin: 0 }}>{text}</pre>
      </Focusable>
    </div>
  </ModalRoot>;
}
