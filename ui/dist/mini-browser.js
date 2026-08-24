function o(i) {
  function e() {
    const n = i.app.absoluteApiUrl("/view");
    return /* @__PURE__ */ i.h(
      "button",
      {
        onClick: () => window.open(n, "mini-browser-main", "popup=1,width=1200,height=800"),
        className: "p-1 rounded hover:bg-white/10 text-[var(--color-text-muted)]",
        title: "Pop out to new window"
      },
      /* @__PURE__ */ i.h("svg", { width: "14", height: "14", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2" }, /* @__PURE__ */ i.h("path", { d: "M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" }), /* @__PURE__ */ i.h("polyline", { points: "15 3 21 3 21 9" }), /* @__PURE__ */ i.h("line", { x1: "10", y1: "14", x2: "21", y2: "3" }))
    );
  }
  i.registerWindowActions("mini-browser.main", e);
}
export {
  o as default,
  o as register
};
