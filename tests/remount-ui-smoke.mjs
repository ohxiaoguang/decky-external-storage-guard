// Test-only minimal hook host and Decky controls. Does not emulate Steam focus.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

let current;
const equalDeps = (a, b) => a && b && a.length === b.length && a.every((v, i) => v === b[i]);
class Host {
  slots = []; effects = [];
  render(Component, props) {
    this.index = 0; current = this;
    const result = Component(props); current = undefined;
    this.effects.splice(0).forEach(fn => fn());
    return result;
  }
  slot(initial) {
    const i = this.index++;
    return this.slots[i] ??= { value: initial };
  }
}
const hooks = {
  createContext: value => ({ value }),
  useState(initial) { const slot = current.slot(initial); return [slot.value, value => { slot.value = typeof value === "function" ? value(slot.value) : value; }]; },
  useRef(initial) { return current.slot({ current: initial }).value; },
  useMemo(fn, deps) { const slot = current.slot(); if (!equalDeps(slot.deps, deps)) { slot.value = fn(); slot.deps = deps; } return slot.value; },
  useCallback(fn, deps) { return hooks.useMemo(() => fn, deps); },
  useEffect(fn, deps) {
    const slot = current.slot();
    if (!equalDeps(slot.deps, deps)) {
      slot.deps = deps;
      current.effects.push(() => { slot.cleanup?.(); slot.cleanup = fn(); });
    }
  },
};
const jsx = (type, props) => ({ type, props });
globalThis.SP_REACT = hooks;
globalThis.SP_JSX = { jsx, jsxs: jsx, Fragment: Symbol("Fragment") };
let dialog;
globalThis.DFL = {
  staticClasses: { Title: "title" },
  PanelSection: "PanelSection", PanelSectionRow: "PanelSectionRow", ButtonItem: "ButtonItem",
  DropdownItem: "DropdownItem", ConfirmModal: "ConfirmModal",
  showModal(element) {
    let resolve;
    const handle = { ClosedPromise: new Promise(r => { resolve = r; }), Close: () => resolve() };
    dialog = { element, handle };
    return handle;
  },
};
const partition = { name: "mmcblk0p1", path: "/dev/mmcblk0p1", size: 1024, filesystem: "ext4", readOnly: false,
  mounts: [{ target: "/run/media/deck/card", readOnly: false }],
  management: { eligible: true, token: "test-only-token", reason: "", warnings: ["journal aborted"] } };
const device = { id: "/dev/mmcblk0", name: "mmcblk0", model: "Test fixture", kind: "SD", size: 1024,
  mounted: true, readOnly: false, partitions: [partition], counts: { Error: 0, Warning: 0, Info: 0 }, lastEvent: null };
let snapshot = { devices: [device], events: [], warnings: [], window: "boot", refreshedAt: 1, lastOperation: null,
  deviceStatus: { status: "ok", message: "ok" }, journalStatus: { status: "ok", message: "ok" } };
const mutations = [];
let finishOperation;
globalThis.window = { __DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit: {
  connect: version => ({ _version: version, callable: method => async (...args) => {
    if (method === "get_snapshot") return snapshot;
    mutations.push(args);
    return await new Promise(resolve => { finishOperation = resolve; });
  } }),
} };
const flush = () => new Promise(resolve => setImmediate(resolve));
function find(tree, predicate) {
  if (Array.isArray(tree)) return tree.flatMap(node => find(node, predicate));
  if (!tree || typeof tree !== "object") return [];
  return [...(predicate(tree) ? [tree] : []), ...find(tree.props?.children, predicate)];
}
const named = (tree, name) => find(tree, n => n.type?.name === name)[0];
const button = tree => find(tree, n => n.type === "ButtonItem")[0];
const { default: definePlugin } = await import(pathToFileURL(process.argv[2]).href);
const plugin = definePlugin();
const app = new Host();
app.render(plugin.content.type, {});
await flush();
let tree = app.render(plugin.content.type, {});
named(tree, "DeviceList").props.onSelect(device.id);
tree = app.render(plugin.content.type, {});
assert.equal(named(tree, "DeviceDetail"), undefined, "technical device details are secondary");
assert.equal(named(tree, "ReportControls").props.compact, true);
const compactDevice = named(tree, "DeviceList");
const deviceTree = compactDevice.type(compactDevice.props);
const card = button(deviceTree);
assert.match(card.props.description, /ext4/);
assert.match(card.props.description, /已挂载/);
assert.match(card.props.description, /可写/);
let controls = named(tree, "RemountControls");
const host = new Host();
let controlTree = host.render(controls.type, controls.props);
button(controlTree).props.onClick();
assert.equal(dialog.element.type, "ConfirmModal");
assert.equal(mutations.length, 0, "opening a confirmation must never mutate devices");
const cancelledConfirm = dialog.element.props.onOK;
dialog.element.props.onCancel();
cancelledConfirm();
await flush();
assert.equal(mutations.length, 0, "cancelling must never mutate devices");
button(controlTree).props.onClick();
const confirm = dialog.element.props.onOK;
confirm(); confirm();
assert.deepEqual(mutations, [["test-only-token"]], "only one RPC, with an opaque token and no arbitrary path");
tree = app.render(plugin.content.type, {});
assert.equal(named(tree, "RemountControls").props.busy, true);
assert.equal(named(tree, "OperationStatus").props.busy, true);
controlTree = host.render(controls.type, { ...controls.props, busy: true });
assert.equal(button(controlTree).props.disabled, true);
const operation = { status: "mount_failed", phase: "mount", partition: partition.path, warnings: [],
  message: "安全卸载后挂载失败", detail: "bad superblock", unmounted: true, mounted: null };
const unmounted = { ...partition, mounts: [], management: { ...partition.management, eligible: false, token: null } };
snapshot = { ...snapshot, devices: [{ ...device, mounted: false, partitions: [unmounted] }], lastOperation: operation };
finishOperation({ operation, snapshot });
await flush();
tree = app.render(plugin.content.type, {});
assert.equal(named(tree, "OperationStatus").props.operation.status, "mount_failed");
assert.equal(named(tree, "DeviceList").props.devices[0].mounted, false, "UI must use the fresh backend snapshot");
controlTree = host.render(controls.type, { ...controls.props, partition: unmounted, busy: false });
assert.equal(button(controlTree).props.disabled, true);
button(controlTree).props.onClick();
assert.equal(mutations.length, 1);
// A later, freshly authorized operation can succeed and updates the result panel.
snapshot = { ...snapshot, devices: [{ ...device, partitions: [{ ...partition, management: { ...partition.management, token: "fresh-test-token" } }] }] };
button(tree).props.onClick();
await flush();
tree = app.render(plugin.content.type, {});
controls = named(tree, "RemountControls");
controlTree = host.render(controls.type, controls.props);
button(controlTree).props.onClick();
dialog.element.props.onOK();
assert.equal(mutations.length, 2);
assert.deepEqual(mutations[1], ["fresh-test-token"]);
const success = { ...operation, status: "success", phase: "verify", message: "重新挂载完成", detail: "", mounted: true };
finishOperation({ operation: success, snapshot: { ...snapshot, lastOperation: success } });
await flush();
tree = app.render(plugin.content.type, {});
assert.equal(named(tree, "OperationStatus").props.operation.status, "success");
assert.equal(named(tree, "OperationStatus").props.busy, false);
plugin.onDismount();
console.log("Remount confirmation, cancel, duplicate prevention, busy/success/failure states and refresh: OK");
