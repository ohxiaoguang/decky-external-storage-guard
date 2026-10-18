import { definePlugin } from "@decky/api";
import { staticClasses } from "@decky/ui";
import { FaHdd } from "react-icons/fa";
import { App, disposeViews } from "./App";
import { zh } from "./strings";

export default definePlugin(() => ({
  name: zh.name,
  titleView: <div className={staticClasses.Title}>{zh.name}</div>,
  content: <App />,
  icon: <FaHdd />,
  onDismount: disposeViews,
}));
