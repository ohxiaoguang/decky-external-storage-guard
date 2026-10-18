// Test-only React hooks, Decky modal and CEF host. No real storage or clipboard I/O.
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
let modal;
globalThis.DFL = { staticClasses: { Title: "title" }, PanelSection: "PanelSection", PanelSectionRow: "PanelSectionRow", ButtonItem: "ButtonItem", DialogButton: "DialogButton", Focusable: "Focusable", ModalRoot: "ModalRoot", ConfirmModal: "ConfirmModal", GamepadButton: { DIR_UP: 9, DIR_DOWN: 10 },
  showModal(element) {
    let resolve;
    const handle = { Close: () => resolve(), ClosedPromise: new Promise(r => { resolve = r; }) };
    modal = { element, handle }; return handle;
  },
};
const part = { name: "mmcblk0p1", path: "/dev/mmcblk0p1", size: 123456789, filesystem: "ext4", readOnly: false,
  mounts: [{ target: "/run/media/deck/card", readOnly: false }],
  actions: { unmount: { token: "unmount-token", reason: "" }, mount: { token: null, reason: "already mounted" } } };
const device = { id: "/dev/mmcblk0", model: "MicroSD fixture", kind: "SD", size: 123456789, mounted: true, readOnly: false, partitions: [part] };
let snapshot = { devices: [device], deviceStatus: { status: "ok", message: "" }, lastOperation: null };
const calls = [], copied = [];
let completeOperation, failSnapshot = false, clipboardOK = true, focusRestored = false;
let logResponse = { status: "ok", message: "日志已截断", limited: true, text: '__REALTIME_TIMESTAMP=123 _SYSTEMD_UNIT=udisks2.service\nraw 中文\n"); globalThis.compromised = true; //\nTuning failed' };
globalThis.window = { __DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit: {
  connect: version => ({ _version: version, callable: method => async (...args) => {
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
button(cardTree, "卸载").props.onClick();
assert.equal(modal.element.type, "ConfirmModal");
const canceled = modal.element.props.onOK;
modal.element.props.onCancel(); canceled(); await flush();
assert.equal(calls.filter(c => c.method === "unmount_partition").length, 0);
button(cardTree, "卸载").props.onClick();
const confirm = modal.element.props.onOK; confirm(); confirm();
assert.deepEqual(calls.filter(c => c.method === "unmount_partition").map(c => c.args), [["unmount-token"]]);
tree = render(); card = named(tree, "DeviceCard"); cardTree = card.type(card.props);
assert.equal(button(cardTree, "卸载").props.disabled, true);
assert.equal(card.key, initialKey, "operation does not replace device component identity");
const unmounted = { ...part, mounts: [], actions: { unmount: { token: null }, mount: { token: "mount-token" } } };
snapshot = { ...snapshot, devices: [{ ...device, mounted: false, partitions: [unmounted] }] };
completeOperation({ operation: { status: "success", action: "unmount", target: part.path, verified: true, mounts: [], message: "已卸载" }, snapshot });
await flush(); tree = render(); card = named(tree, "DeviceCard"); cardTree = card.type(card.props);
assert.match(text(tree), /卸载成功/); assert.match(text(cardTree), /未挂载/);
assert.equal(button(cardTree, "卸载").props.disabled, true);
assert.equal(button(cardTree, "挂载").props.disabled, false);
assert.equal(calls.filter(c => c.method === "get_snapshot").length, 1, "no whole-page reload after operation");
button(cardTree, "挂载").props.onClick(); button(cardTree, "挂载").props.onClick();
assert.deepEqual(calls.filter(c => c.method === "mount_partition").map(c => c.args), [["mount-token"]]);
completeOperation({ operation: { status: "mount_failed", action: "mount", verified: false, message: "bad superblock" }, snapshot: null });
await flush(); tree = render(); assert.match(text(tree), /失败.*bad superblock/);
card = named(tree, "DeviceCard"); assert.strictEqual(card.props.device, snapshot.devices[0]);
button(card.type(card.props), "挂载").props.onClick();
completeOperation({ operation: { status: "success", action: "mount", verified: false, message: "zero exit is insufficient" }, snapshot: null });
await flush(); tree = render(); assert.match(text(tree), /不确定/); assert.doesNotMatch(text(tree), /挂载成功/);
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
button(tree, "查看日志").props.onClick();
const logElement = modal.element;
assert.equal(logElement.type.name, "LogModal");
const logHost = new Host(); logHost.render(logElement.type, logElement.props); await flush();
const renderLog = () => logHost.render(logElement.type, logElement.props);
let logTree = renderLog();
assert.equal(logTree.type, "ModalRoot");
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
logResponse = { status: "ok", message: "", text: "EXT4-fs: actual raw mount message", limited: false };
button(logTree, "刷新").props.onClick(); await flush(); logTree = renderLog();
assert.doesNotMatch(text(logTree), /Tuning failed/); assert.match(text(logTree), /actual raw mount/);
const scroll = find(logTree, node => node.type === "Focusable" && node.props.tabIndex === 0)[0];
let scrolled = 0;
scroll.props.ref.current = { scrollTop: 0, clientHeight: 100, scrollHeight: 800, scrollBy({ top }) { scrolled += top; } };
scroll.props.onGamepadDirection({ detail: { button: 10 }, preventDefault() {}, stopPropagation() {} }); assert.equal(scrolled, 120);
scroll.props.onKeyDown({ key: "PageDown", preventDefault() {} }); assert.equal(scrolled, 440);
button(logTree, "复制").props.onClick(); await flush(); assert.equal(copied.at(-1), logResponse.text);
button(logTree, "关闭").props.onClick(); logHost.unmount();
const updateElement = named(tree, "Updates"); const updateHost = new Host();
let updateTree = updateHost.render(updateElement.type, updateElement.props);
button(updateTree, "复制更新链接").props.onClick(); await flush();
assert.equal(copied.at(-1), "https://github.com/ohxiaoguang/decky-external-storage-guard/releases/latest/download/External-Storage-Guard.zip");
assert.doesNotMatch(text(updateTree), /https:\/\//);
plugin.onDismount(); app.unmount(); updateHost.unmount();
console.log("Single-level UI, partition buttons / verification / local updates, raw log modal / refresh / exact copy / gamepad scroll: OK");
