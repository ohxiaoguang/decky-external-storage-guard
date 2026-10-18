// Test-only React hooks, native Decky controls and CEF host (no modal APIs). No real storage or clipboard I/O.
import assert from "node:assert/strict";
import vm from "node:vm";
import { pathToFileURL } from "node:url";
let current;
const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => v === b[i]);
class Host {
  slots = []; effects = [];
  slot(initial) { return this.slots[this.index++] ??= { value: initial }; }
  render(component, props) { this.index = 0; current = this; const tree = component(props); current = undefined; this.effects.splice(0).forEach(effect => effect()); return tree; }
  unmount() { this.slots.forEach(slot => slot.cleanup?.()); }
}
const hooks = {
  createContext: value => ({ value }),
  useState(initial) { const slot = current.slot(initial); return [slot.value, value => { slot.value = typeof value === "function" ? value(slot.value) : value; }]; },
  useRef(initial) { return current.slot({ current: initial }).value; },
  useEffect(fn, deps) { const slot = current.slot(); if (!same(slot.deps, deps)) { slot.deps = deps; current.effects.push(() => { slot.cleanup?.(); slot.cleanup = fn(); }); } },
};
globalThis.SP_REACT = hooks;
const jsx = (type, props, key) => ({ type, props, key });
globalThis.SP_JSX = { jsx, jsxs: jsx, Fragment: Symbol("Fragment") };
// No modal APIs: real routes are registered independently of the sidebar content.
const LOG_ROUTE = "/external-storage-guard/logs";
const routes = new Map(), navigation = [], history = ["/library/home"];
let quickVisible = true, currentPath = history[0];
const navigate = path => { currentPath = path; history.push(path); navigation.push(["navigate", path]); };
const goBack = () => { if (history.length > 1) history.pop(); currentPath = history.at(-1); navigation.push(["back", currentPath]); };
globalThis.DFL = { staticClasses: { Title: "title" }, PanelSection: "PanelSection", PanelSectionRow: "PanelSectionRow", ButtonItem: "ButtonItem", DialogButton: "DialogButton", Focusable: "Focusable", GamepadButton: { DIR_UP: 9, DIR_DOWN: 10 },
  Router: { CloseSideMenus() { quickVisible = false; navigation.push(["close"]); }, Navigate: navigate },
  Navigation: { NavigateBack: goBack }, ReactRouter: { useLocation: () => ({ pathname: currentPath }) },
};
const realTimeout = globalThis.setTimeout, realClearTimeout = globalThis.clearTimeout;
const confirmationTimers = new Set();
globalThis.setTimeout = (callback, ms, ...args) => {
  if (ms !== 15000) return realTimeout(callback, ms, ...args);
  const timer = { callback }; confirmationTimers.add(timer); return timer;
};
globalThis.clearTimeout = timer => confirmationTimers.delete(timer) || realClearTimeout(timer);
const part = { name: "mmcblk0p1", path: "/dev/mmcblk0p1", size: 123456789, filesystem: "ext4", readOnly: false,
  mounts: [{ target: "/run/media/deck/card", readOnly: false }],
  actions: { unmount: { token: "unmount-token", reason: "" }, mount: { token: null, reason: "already mounted" } } };
const device = { id: "/dev/mmcblk0", model: "MicroSD fixture", kind: "SD", size: 123456789, mounted: true, readOnly: false, partitions: [part] };
let snapshot = { devices: [device], deviceStatus: { status: "ok", message: "" }, lastOperation: null };
const calls = [], copied = [];
let completeOperation, failSnapshot = false, clipboardOK = true, focusRestored = false;
let logResponse = { status: "ok", message: "日志已截断", limited: true, text: '2026-10-19 00:37:09.557 udisksd: raw 中文\n"); globalThis.compromised = true; //\nTuning failed' };
globalThis.window = { __DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit: {
  connect: version => ({ _version: version,
    useQuickAccessVisible: () => quickVisible,
    routerHook: { addRoute(path, component, props) { assert.equal(props.exact, true); assert.ok(!routes.has(path)); routes.set(path, component); navigation.push(["register", path]); },
      removeRoute(path) { routes.delete(path); navigation.push(["remove", path]); } },
    callable: method => async (...args) => {
    calls.push({ method, args });
    if (method === "get_snapshot") { if (failSnapshot) throw new Error("offline"); return snapshot; }
    if (method === "get_logs") return logResponse;
    return new Promise(resolve => { completeOperation = resolve; });
  }, executeInTab: async (tab, async, code) => {
    assert.equal(async, false);
    const input = { style: {}, focus() {}, select() {}, remove() {} };
    const context = { document: { activeElement: { focus() { focusRestored = true; } }, body: { appendChild() {} }, createElement: () => input,
      execCommand(action) { assert.equal(action, "copy"); return clipboardOK; } } };
    const result = vm.runInNewContext(code, context);
    assert.equal(context.compromised, undefined);
    if (result) copied.push(input.value);
    return { success: true, result };
  } }),
} };
function find(tree, predicate) {
  if (Array.isArray(tree)) return tree.flatMap(node => find(node, predicate));
  if (!tree || typeof tree !== "object") return [];
  return [...(predicate(tree) ? [tree] : []), ...find(tree.props?.children, predicate)];
}
const named = (tree, name) => find(tree, node => node.type?.name === name)[0];
const button = (tree, label) => find(tree, node => ["ButtonItem", "DialogButton"].includes(node.type) && node.props.children === label)[0];
const text = tree => Array.isArray(tree) ? tree.map(text).join(" ") : tree && typeof tree === "object" ? text(tree.props?.children) : String(tree ?? "");
const flush = () => new Promise(resolve => setImmediate(resolve));
const plugin = (await import(pathToFileURL(process.argv[2]).href)).default();
assert.equal(plugin.alwaysRender, true, "official flag keeps sidebar content mounted when closed");
assert.equal(routes.get(LOG_ROUTE)?.name, "LogPage");
const app = new Host(); app.render(plugin.content.type, {}); await flush();
const render = () => app.render(plugin.content.type, {});
let tree = render();
assert.equal(find(tree, node => node.type === "DropdownItem").length, 0);
assert.equal(button(tree, "查看详情"), undefined);
assert.equal(button(tree, "重新挂载"), undefined);
let card = named(tree, "DeviceCard");
const initialKey = card.key;
let cardTree = card.type(card.props);
assert.equal(button(cardTree, "卸载").props.disabled, false);
assert.equal(button(cardTree, "挂载").props.disabled, true);
const renderCard = () => { tree = render(); card = named(tree, "DeviceCard"); return card.type(card.props); };
const operationCount = () => calls.filter(c => c.method === "unmount_partition").length;
const arm = () => { button(renderCard(), "卸载").props.onClick(); return renderCard(); };
cardTree = arm();
assert.equal(operationCount(), 0, "first click never sends a device request");
assert.ok(button(cardTree, "确认卸载")); assert.ok(button(cardTree, "取消"));
const canceled = button(cardTree, "确认卸载").props.onClick;
button(cardTree, "取消").props.onClick(); canceled(); await flush();
assert.equal(operationCount(), 0, "a stale confirmed callback after cancel is harmless");
assert.ok(button(renderCard(), "卸载"));
cardTree = arm();
for (const timer of [...confirmationTimers]) timer.callback();
assert.equal(confirmationTimers.size, 0);
assert.ok(button(renderCard(), "卸载"), "confirmation expires without any RPC");
cardTree = arm();
const expired = button(cardTree, "确认卸载").props.onClick;
const now = Date.now; Date.now = () => now() + 16000;
expired(); Date.now = now;
assert.equal(operationCount(), 0, "deadline also blocks a delayed timer/queued click");
cardTree = arm();
card.props.focus("/dev/other-partition");
assert.ok(button(renderCard(), "卸载"), "switching target cancels confirmation");
cardTree = arm();
const beforeLogs = card.props.device;
const leftPageConfirm = button(cardTree, "确认卸载").props.onClick;
button(tree, "查看日志").props.onClick();
assert.deepEqual(navigation.slice(-2), [["close"], ["navigate", LOG_ROUTE]]);
assert.ok(named(render(), "DeviceCard"), "home stays mounted behind closed sidebar");
assert.equal(named(render(), "LogPage"), undefined, "logs are not rendered inside sidebar");
leftPageConfirm(); assert.equal(operationCount(), 0, "hidden home callbacks cannot operate");
const firstLogHost = new Host(); firstLogHost.render(routes.get(LOG_ROUTE), {}); await flush();
button(firstLogHost.render(routes.get(LOG_ROUTE), {}), "返回").props.onClick();
firstLogHost.unmount(); quickVisible = true; cardTree = renderCard();
assert.equal(currentPath, "/library/home");
assert.strictEqual(card.props.device, beforeLogs);
assert.ok(button(cardTree, "卸载"), "leaving home cancels confirmation");
assert.equal(calls.filter(c => c.method === "get_snapshot").length, 1, "back does not initialize App again");
// Closing QAM by itself also invalidates a pending unmount confirmation.
cardTree = arm(); quickVisible = false; render(); quickVisible = true;
assert.ok(button(renderCard(), "卸载")); assert.equal(operationCount(), 0);
cardTree = arm();
const beforeScanConfirm = button(cardTree, "确认卸载").props.onClick;
button(tree, "刷新").props.onClick(); await flush(); beforeScanConfirm();
assert.equal(operationCount(), 0, "a refreshed device scan invalidates pending confirmation");
cardTree = arm();
// Changing devices arms only the newly selected partition; no old confirmation survives.
const other = { ...part, name: "sda1", path: "/dev/sda1", actions: { ...part.actions, unmount: { token: "other-token" } } };
const originalSnapshot = snapshot;
snapshot = { ...snapshot, devices: [...snapshot.devices, { ...device, id: "/dev/sda", partitions: [other] }] };
button(tree, "刷新").props.onClick(); await flush(); cardTree = arm();
let cards = find(tree, node => node.type?.name === "DeviceCard");
button(cards[1].type(cards[1].props), "卸载").props.onClick(); tree = render();
cards = find(tree, node => node.type?.name === "DeviceCard");
assert.ok(button(cards[0].type(cards[0].props), "卸载"));
assert.ok(button(cards[1].type(cards[1].props), "确认卸载"));
assert.equal(operationCount(), 0);
snapshot = originalSnapshot;
button(tree, "刷新").props.onClick(); await flush(); cardTree = arm();
const confirm = button(cardTree, "确认卸载").props.onClick; confirm(); confirm();
assert.deepEqual(calls.filter(c => c.method === "unmount_partition").map(c => c.args), [["unmount-token"]]);
cardTree = renderCard();
assert.equal(button(cardTree, "卸载中…").props.disabled, true);
assert.equal(button(tree, "查看日志").props.disabled, true);
assert.equal(card.key, initialKey, "operation does not replace device component identity");
completeOperation({ operation: { status: "device_busy", action: "unmount", verified: false, message: "设备正在使用：Device busy" }, snapshot: null });
await flush(); cardTree = renderCard();
assert.match(text(tree), /失败.*设备正在使用/); assert.match(text(cardTree), /已挂载/);
assert.equal(button(cardTree, "挂载").props.disabled, true);
cardTree = arm(); button(cardTree, "确认卸载").props.onClick();
completeOperation({ operation: { status: "success", action: "unmount", target: part.path, verified: true, message: "已卸载" }, snapshot });
await flush(); cardTree = renderCard();
assert.match(text(tree), /操作结果不确定，请刷新确认/); assert.doesNotMatch(text(tree), /卸载成功/);
assert.match(text(cardTree), /已挂载/);
cardTree = arm(); button(cardTree, "确认卸载").props.onClick();
const unmounted = { ...part, mounts: [], actions: { unmount: { token: null }, mount: { token: "mount-token" } } };
snapshot = { ...snapshot, devices: [{ ...device, mounted: false, partitions: [unmounted] }] };
completeOperation({ operation: { status: "success", action: "unmount", target: part.path, verified: true, mounts: [], message: "已卸载" }, snapshot });
await flush(); tree = render(); card = named(tree, "DeviceCard"); cardTree = card.type(card.props);
assert.match(text(tree), /卸载成功/); assert.match(text(cardTree), /未挂载/);
assert.equal(button(cardTree, "卸载").props.disabled, true);
assert.equal(button(cardTree, "挂载").props.disabled, false);
assert.equal(calls.filter(c => c.method === "get_snapshot").length, 4, "no whole-page reload after operation");
const queuedMount = button(cardTree, "挂载").props.onClick;
button(tree, "查看日志").props.onClick(); queuedMount();
assert.equal(calls.filter(c => c.method === "mount_partition").length, 0, "queued hidden-home mount cannot execute during navigation");
render(); goBack(); quickVisible = true; cardTree = renderCard();
button(cardTree, "挂载").props.onClick(); button(cardTree, "挂载").props.onClick();
assert.deepEqual(calls.filter(c => c.method === "mount_partition").map(c => c.args), [["mount-token"]]);
assert.equal(button(renderCard(), "挂载中…").props.disabled, true);
completeOperation({ operation: { status: "mount_failed", action: "mount", verified: false, message: "bad superblock" }, snapshot: null });
await flush(); tree = render(); assert.match(text(tree), /失败.*bad superblock/);
card = named(tree, "DeviceCard"); assert.strictEqual(card.props.device, snapshot.devices[0]);
button(card.type(card.props), "挂载").props.onClick();
completeOperation({ operation: { status: "success", action: "mount", verified: false, message: "zero exit is insufficient" }, snapshot: null });
await flush(); tree = render(); assert.match(text(tree), /不确定/); assert.doesNotMatch(text(tree), /挂载成功/);
button(renderCard(), "挂载").props.onClick();
completeOperation({ operation: { status: "success", action: "unmount", target: part.path, verified: true, message: "old incompatible response" }, snapshot });
await flush(); tree = render(); assert.match(text(tree), /不确定.*接口返回不兼容/);
cardTree = named(tree, "DeviceCard").type(named(tree, "DeviceCard").props);
button(cardTree, "挂载").props.onClick();
snapshot = { ...snapshot, devices: [{ ...device, readOnly: true, partitions: [{ ...part, mounts: [{ target: "/run/media/deck/new", readOnly: true }] }] }] };
completeOperation({ operation: { status: "success", action: "mount", target: part.path, verified: true, message: "已挂载", mounts: [{ target: "/run/media/deck/new", readOnly: true }], readOnly: true }, snapshot });
await flush(); tree = render(); assert.match(text(tree), /挂载成功.*new.*只读/);
failSnapshot = true; button(tree, "刷新").props.onClick(); await flush(); tree = render();
assert.match(text(tree), /保留当前页面/); assert.ok(named(tree, "DeviceCard")); failSnapshot = false;
const second = { ...part, name: "mmcblk0p2", path: "/dev/mmcblk0p2" };
const multiple = card.type({ ...card.props, device: { ...device, partitions: [part, second] } });
assert.equal(find(multiple, node => node.type === "ButtonItem").length, 4);
assert.match(text(multiple), /mmcblk0p1/); assert.match(text(multiple), /mmcblk0p2/);
const beforeLogDevice = named(tree, "DeviceCard").props.device;
const readsBeforeLogs = calls.filter(c => c.method === "get_snapshot").length;
button(tree, "查看日志").props.onClick();
assert.equal(currentPath, LOG_ROUTE); render();
const logComponent = routes.get(LOG_ROUTE);
const logHost = new Host(); logHost.render(logComponent, {}); await flush();
const renderLog = () => logHost.render(logComponent, {});
let logTree = renderLog();
assert.equal(logTree.type, "Focusable");
assert.match(text(logTree), /External Storage Guard · 系统日志/);
assert.equal(logTree.props.style.position, "absolute");
assert.equal(logTree.props.style.inset, 0);
assert.ok(button(logTree, "返回").props.preferredFocus);
assert.equal(find(logTree, node => node.type === "DialogButton").length, 3);
assert.match(text(logTree), /Tuning failed/); assert.match(text(logTree), /日志已截断/);
button(logTree, "复制").props.onClick(); button(logTree, "复制").props.onClick(); await flush();
assert.equal(copied.length, 1); assert.equal(copied[0], logResponse.text); assert.ok(focusRestored);
logTree = renderLog(); assert.match(text(logTree), /已复制全部显示日志/); assert.match(text(logTree), /日志已截断/);
clipboardOK = false; button(logTree, "复制").props.onClick(); await flush(); logTree = renderLog(); assert.match(text(logTree), /复制失败/); clipboardOK = true;
const originalLog = logResponse.text;
logResponse = { status: "permission_denied", message: "无权限", text: "", limited: false };
button(logTree, "刷新").props.onClick(); button(logTree, "刷新").props.onClick(); await flush(); logTree = renderLog();
assert.match(text(logTree), /无权限/); assert.ok(text(logTree).includes(originalLog), "failed log read preserves displayed raw text");
logResponse = { status: "no_logs", message: "本次启动暂无可读取的相关日志", text: "", limited: false };
button(logTree, "刷新").props.onClick(); await flush(); logTree = renderLog();
assert.match(text(logTree), /本次启动暂无可读取的相关日志/);
assert.equal(button(logTree, "复制").props.disabled, true);
logResponse = { status: "ok", message: "", text: "2026-10-19 00:37:09.557 kernel: EXT4-fs: actual raw mount message", limited: false };
button(logTree, "刷新").props.onClick(); await flush(); logTree = renderLog();
assert.doesNotMatch(text(logTree), /Tuning failed/); assert.match(text(logTree), /actual raw mount/);
const scroll = find(logTree, node => node.type === "Focusable" && node.props.tabIndex === 0)[0];
let scrolled = 0;
scroll.props.ref.current = { scrollTop: 0, clientHeight: 100, scrollHeight: 800, scrollBy({ top }) { scrolled += top; } };
scroll.props.onGamepadDirection({ detail: { button: 10 }, preventDefault() {}, stopPropagation() {} }); assert.equal(scrolled, 120);
scroll.props.onKeyDown({ key: "PageDown", preventDefault() {} }); assert.equal(scrolled, 440);
button(logTree, "复制").props.onClick(); await flush(); assert.equal(copied.at(-1), logResponse.text);
const backCount = navigation.filter(n => n[0] === "back").length;
button(logTree, "返回").props.onClick(); button(logTree, "返回").props.onClick();
assert.equal(navigation.filter(n => n[0] === "back").length, backCount + 1, "duplicate Back cannot leave an additional Steam page");
assert.equal(currentPath, "/library/home");
logHost.unmount(); quickVisible = true; tree = render();
assert.strictEqual(named(tree, "DeviceCard").props.device, beforeLogDevice, "return preserves actual device state");
assert.equal(calls.filter(c => c.method === "get_snapshot").length, readsBeforeLogs, "no device initialization from log refresh or return");
assert.match(text(tree), /保留当前页面/, "home feedback survives log navigation");
// B/back uses native cancellation handling without bubbling into closing the plugin.
button(tree, "查看日志").props.onClick(); render();
const backHost = new Host(); backHost.render(logComponent, {}); await flush();
let prevented = false, stopped = false;
backHost.render(logComponent, {}).props.onCancel({ preventDefault() { prevented = true; }, stopPropagation() { stopped = true; } });
backHost.unmount(); quickVisible = true; tree = render(); assert.ok(named(tree, "DeviceCard")); assert.ok(prevented && stopped);
const updateElement = named(tree, "Updates"); const updateHost = new Host();
let updateTree = updateHost.render(updateElement.type, updateElement.props);
button(updateTree, "复制更新链接").props.onClick(); await flush();
assert.equal(copied.at(-1), "https://github.com/ohxiaoguang/decky-external-storage-guard/releases/latest/download/External-Storage-Guard.zip");
assert.doesNotMatch(text(updateTree), /https:\/\//);
cardTree = arm(); const afterDismount = button(cardTree, "确认卸载").props.onClick;
const operationsBeforeDismount = operationCount();
// Unloading while on the full-screen route exits it and unregisters exactly once.
button(tree, "查看日志").props.onClick(); render();
const unloadingLogHost = new Host(); unloadingLogHost.render(logComponent, {}); await flush();
plugin.onDismount(); afterDismount(); app.unmount(); updateHost.unmount(); unloadingLogHost.unmount();
assert.equal(currentPath, "/library/home"); assert.equal(routes.size, 0);
assert.deepEqual(navigation.slice(-2), [["back", "/library/home"], ["remove", LOG_ROUTE]]);
assert.equal(navigation.filter(n => n[0] === "register").length, 1, "all page operations reused one plugin initialization");
assert.equal(operationCount(), operationsBeforeDismount); assert.equal(confirmationTimers.size, 0);
globalThis.setTimeout = realTimeout; globalThis.clearTimeout = realClearTimeout;
console.log("Inline unmount first/second click / cancel / expiry / state changes, verified results, stable App, true fullscreen route / QAM close / back / unregister / refresh / exact copy / gamepad scroll: OK");
