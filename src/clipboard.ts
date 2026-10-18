import { executeInTab } from "@decky/api";
import { zh } from "./strings";

export const CLIPBOARD_LIMIT = 64 * 1024;

export function clipboardScript(text: string): string {
  // Text is data inside a JSON literal, never executable source supplied by logs.
  const encoded = JSON.stringify(text).replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
  return `(() => {
    if (typeof document === 'undefined' || !document.body || typeof document.execCommand !== 'function') return false;
    const previous = document.activeElement;
    const input = document.createElement('textarea');
    input.value = ${encoded};
    input.style.cssText = 'position:fixed;left:-10000px;top:0;opacity:0';
    document.body.appendChild(input);
    try { input.focus(); input.select(); return document.execCommand('copy') === true; }
    catch (_) { return false; }
    finally { input.remove(); if (previous && typeof previous.focus === 'function') previous.focus(); }
  })()`;
}

export async function copyDiagnostic(text: string): Promise<void> {
  if (new TextEncoder().encode(text).length > CLIPBOARD_LIMIT) throw new Error(zh.reportTooLarge);
  const code = clipboardScript(text);
  // These names are the Loader's SHARED_CTX_NAMES. The official API locates a
  // named Steam page; CEF performs the copy and returns its boolean result.
  for (const tab of ["SharedJSContext", "Steam Shared Context presented by Valve™", "Steam", "SP"]) {
    try {
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        const result = await Promise.race([
          executeInTab(tab, false, code),
          new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error("clipboard timeout")), 3000); }),
        ]);
        if (result.success && result.result === true) return;
      } finally { if (timer) clearTimeout(timer); }
    } catch { /* Try the next supported Steam page name; never claim success. */ }
  }
  throw new Error(zh.reportCopyFailed);
}
