// Test-only Decky/React stubs: verify the built ESM entrypoint, not SteamOS UI.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const requests = [], routes = new Map();
globalThis.window = {
  __DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit: {
    connect(version, name) {
      assert.equal(name, "External Storage Guard");
      return {
        _version: version,
        routerHook: { addRoute(path, component, props) { assert.equal(props.exact, true); routes.set(path, component); }, removeRoute(path) { routes.delete(path); } },
        callable(method) {
          requests.push(method);
          return async () => { throw new Error("Backend must not run during entrypoint initialization"); };
        },
      };
    },
  },
};
globalThis.SP_REACT = { createContext: value => ({ value }) };
globalThis.SP_JSX = { jsx: (type, props) => ({ type, props }) };
globalThis.DFL = { staticClasses: { Title: "title" } };

const { default: definePlugin } = await import(pathToFileURL(process.argv[2]).href);
assert.equal(typeof definePlugin, "function");
const plugin = definePlugin();
assert.equal(plugin.name, "External Storage Guard");
assert.ok(plugin.content && plugin.icon && plugin.titleView);
assert.equal(plugin.alwaysRender, true);
assert.equal(routes.get("/external-storage-guard/logs")?.name, "LogPage");
assert.deepEqual(requests.sort(), ["get_snapshot", "mount_partition", "unmount_partition", "get_logs"].sort());
plugin.onDismount();
assert.equal(routes.size, 0);
console.log("Packaged frontend ESM entrypoint with test stubs: OK");
