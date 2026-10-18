// Test-only hook host, Decky API and CEF document. No real clipboard/device I/O.
import assert from "node:assert/strict";
import vm from "node:vm";
import { pathToFileURL } from "node:url";
let current;
const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => v === b[i]);
class Host {
  slots = []; effects = [];
  slot(initial) { return this.slots[this.index++] ??= { value: initial }; }
  render(component, props) {
    this.index = 0; current = this;
    const tree = component(props); current = undefined;
    this.effects.splice(0).forEach(effect => effect());
    return tree;
  }
}
const hooks = {
  createContext: value => ({ value }),
  useState(initial) { const slot = current.slot(initial); return [slot.value, value => { slot.value = typeof value === "function" ? value(slot.value) : value; }]; },
  useRef(initial) { return current.slot({ current: initial }).value; },
  useMemo(fn, deps) { const slot = current.slot(); if (!same(slot.deps, deps)) { slot.value = fn(); slot.deps = deps; } return slot.value; },
  useCallback(fn, deps) { return hooks.useMemo(() => fn, deps); },
  useEffect(fn, deps) { const slot = current.slot(); if (!same(slot.deps, deps)) { slot.deps = deps; current.effects.push(() => { slot.cleanup?.(); slot.cleanup = fn(); }); } },
};
const jsx = (type, props) => ({ type, props });
globalThis.SP_REACT = hooks;
globalThis.SP_JSX = { jsx, jsxs: jsx, Fragment: Symbol("Fragment") };
globalThis.DFL = { staticClasses: { Title: "title" }, PanelSection: "PanelSection", PanelSectionRow: "PanelSectionRow", ButtonItem: "ButtonItem", DropdownItem: "DropdownItem" };
const calls = [], clipboardValues = [];
let cefSuccess = true;
let previousRestored = false;
let throwTransport = false;
let reportText = '中文诊断\n"); globalThis.compromised = true; //\n原始 I/O error';
const sleep = { cycles: [{ id: "cycle", bootId: "boot", start: { timestamp: 1 }, wake: { timestamp: 2 },
  status: "paired", estimated: true, completion: "systemd", notes: [], records: [], observations: ["reset"], traceLimited: false, afterCounts: { "1": 1, "5": 2, "10": 3 } }], status: "ok", limited: false, message: "correlation only" };
const data = { devices: [], deviceStatus: { status: "ok", message: "ok" }, journalStatus: { status: "ok", message: "ok" },
  events: [{ id: "e", timestamp: 3, deviceId: null, deviceLabel: null, references: ["mmc0"], bootId: "boot", kind: "tuning", severity: "Warning", summary: "test", raw: "raw", wakeContext: { phase: "after_wake", cycleId: "cycle", delaySeconds: 38, estimated: true } }],
  warnings: [], window: "boot", refreshedAt: 1, lastOperation: null, sleepHistory: sleep };
globalThis.window = { __DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit: {
  connect: version => ({ _version: version,
    callable: method => async (...args) => {
      calls.push({ method, args });
      if (method === "get_snapshot") return data;
      if (method === "get_report") return { status: "ok", reportId: "cached-report", text: reportText, summary: "简短摘要", generatedAt: 1, size: reportText.length, truncated: false };
      if (method === "export_report") return { status: "ok", path: "/home/deck/Downloads/External-Storage-Guard/test.txt" };
      throw new Error("Unexpected device mutation during diagnostics: " + method);
    },
    executeInTab: async (tab, runAsync, code) => {
      assert.equal(runAsync, false);
      if (throwTransport) throw new Error("Steam tab unavailable");
      let copied;
      const input = { style: {}, focus() {}, select() {}, remove() {} };
      const context = { document: { activeElement: { focus() { previousRestored = true; } },
        body: { appendChild() {} }, createElement: () => input,
        execCommand(action) { assert.equal(action, "copy"); copied = input.value; return cefSuccess; } } };
      const result = vm.runInNewContext(code, context);
      assert.equal(context.compromised, undefined, "report text must never execute as JS");
      if (result) clipboardValues.push(copied);
      return { success: true, result };
    },
  }),
} };
function find(tree, predicate) {
  if (Array.isArray(tree)) return tree.flatMap(node => find(node, predicate));
  if (!tree || typeof tree !== "object") return [];
  return [...(predicate(tree) ? [tree] : []), ...find(tree.props?.children, predicate)];
}
const named = (tree, name) => find(tree, x => x.type?.name === name)[0];
const button = (tree, text) => find(tree, x => x.type === "ButtonItem" && x.props.children === text)[0];
const flattenText = tree => {
  if (Array.isArray(tree)) return tree.map(flattenText).join(" ");
  if (!tree || typeof tree !== "object") return String(tree ?? "");
  return flattenText(tree.props?.children);
};
const flush = () => new Promise(resolve => setImmediate(resolve));
const plugin = (await import(pathToFileURL(process.argv[2]).href)).default();
const app = new Host(); app.render(plugin.content.type, {}); await flush();
let appTree = app.render(plugin.content.type, {});
const reportElement = named(appTree, "ReportControls");
const host = new Host();
const render = () => host.render(reportElement.type, { busy: false, onBusy() {} });
let tree = render();
button(tree, "复制诊断报告").props.onClick();
button(tree, "复制诊断报告").props.onClick();
await flush();
assert.equal(calls.filter(x => x.method === "get_report").length, 1);
assert.deepEqual(clipboardValues, [reportText]);
assert.ok(previousRestored);
tree = render();
assert.match(flattenText(tree), /复制命令已确认/);
button(tree, "导出 TXT 文件").props.onClick(); await flush();
assert.deepEqual(calls.find(x => x.method === "export_report").args, ["cached-report"]);
tree = render();
assert.match(flattenText(tree), /\/home\/deck\/Downloads\/External-Storage-Guard\/test.txt/);
assert.equal(calls.filter(x => x.method === "get_report").length, 1, "export reuses the same report");
cefSuccess = false;
button(tree, "复制诊断报告").props.onClick(); await flush();
tree = render();
assert.match(flattenText(tree), /复制失败/);
throwTransport = true;
button(tree, "复制诊断报告").props.onClick(); await flush();
tree = render();
assert.match(flattenText(tree), /复制失败/);
// Range changes invalidate the cached report and preserve exact backend window.
find(tree, x => x.type === "DropdownItem")[0].props.onChange({ data: "week" });
tree = render();
reportText = "中文".repeat(40000);
button(tree, "复制诊断报告").props.onClick(); await flush();
tree = render();
assert.match(flattenText(tree), /64KiB/);
assert.equal(calls.filter(x => x.method === "get_report").at(-1).args[0], "week");
throwTransport = false; cefSuccess = true;
button(tree, "复制简短摘要").props.onClick(); await flush();
assert.equal(clipboardValues.at(-1), "简短摘要");
const historyElement = named(appTree, "SleepHistory");
let selected;
const historyHost = new Host();
const historyTree = historyHost.render(historyElement.type, { ...historyElement.props, onSelect: id => { selected = id; } });
find(historyTree, x => x.type === "ButtonItem")[0].props.onClick();
assert.equal(selected, "cycle");
historyElement.props.onSelect("cycle");
appTree = app.render(plugin.content.type, {});
const eventElement = named(appTree, "EventList");
assert.equal(eventElement.props.events.length, 1);
const eventsHost = new Host();
const eventTree = eventsHost.render(eventElement.type, eventElement.props);
const eventButton = find(eventTree, x => x.type === "ButtonItem")[0];
assert.match(flattenText(eventButton.props.description), /唤醒后约 38 秒/);
assert.equal(calls.filter(x => x.method === "remount_partition").length, 0);
plugin.onDismount();
console.log("Report copy/export/ranges, oversized/failed clipboard, safe encoding and sleep filters: OK");
