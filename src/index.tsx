import { definePlugin, routerHook } from "@decky/api";
import { staticClasses } from "@decky/ui";
import { FaHdd } from "react-icons/fa";
import { App, disposeViews } from "./App";
import { LOG_ROUTE, LogPage, disposeLogViews } from "./components/LogPage";
import { zh } from "./strings";

export default definePlugin(() => {
  routerHook.addRoute(LOG_ROUTE, LogPage, { exact: true });
  let disposed = false;
  return {
    name: zh.name,
    titleView: <div className={staticClasses.Title}>{zh.name}</div>,
    content: <App />,
    alwaysRender: true,
    icon: <FaHdd />,
    onDismount() {
      if (disposed) return;
      disposed = true;
      disposeViews();
      disposeLogViews();
      routerHook.removeRoute(LOG_ROUTE);
    },
  };
});
