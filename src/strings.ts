export const zh = {
  name: "External Storage Guard",
  reportTooLarge: "内容超出剪贴板限制，未复制",
  reportCopyFailed: "复制失败，Steam 剪贴板不可用，请重试",
};
export const size = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GiB`;
