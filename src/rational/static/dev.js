/* Rational Web development helper: live reload + event error overlay. Served only in debug mode. */
(() => {
  "use strict";
  // Live reload: the server's boot id changes whenever uvicorn restarts after a code change.
  const BOOT_URL = new URL("dev/boot", document.currentScript.src).href;  // works under any root path
  let boot = null;
  async function poll() {
    try {
      const r = await fetch(BOOT_URL, { cache: "no-store" });
      if (r.ok) {
        const id = await r.text();
        if (boot && id !== boot) { location.reload(); return; }
        boot = id;
      }
    } catch (_) { /* restarting */ }
    setTimeout(poll, 600);
  }
  poll();

  // Event-handler errors: show what happened and where, without leaving the page.
  document.addEventListener("rw:error", (e) => { if (e.detail && e.detail.debug) show(e.detail.debug); });
  function el(tag, css, text) {
    const n = document.createElement(tag);
    n.style.cssText = css;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function show(d) {
    document.getElementById("rw-dev-overlay")?.remove();
    const box = el("div", "position:fixed;inset:auto 16px 16px 16px;max-height:70vh;overflow:auto;z-index:2147483647;" +
      "background:#1b1020;color:#f5e9f2;border:1px solid #e0457b;border-radius:12px;padding:16px 18px;" +
      "font:13px/1.5 ui-monospace,Menlo,Consolas,monospace;box-shadow:0 20px 50px rgb(0 0 0/.45)");
    box.id = "rw-dev-overlay";
    box.setAttribute("role", "alert");
    const close = el("button", "float:right;background:none;border:1px solid #e0457b;color:inherit;border-radius:6px;" +
      "cursor:pointer;padding:2px 8px", "Close");
    close.onclick = () => box.remove();
    box.append(close, el("div", "color:#ff8fb3;font-weight:700;font-size:15px", d.type + ": " + d.message));
    if (d.file) {
      box.append(el("div", "opacity:.8;margin:4px 0 8px", `in ${d.function}() · ${d.file}:${d.line}`));
    }
    for (const note of d.notes || []) box.append(el("div", "opacity:.8", note));
    for (const [n, code, current] of d.snippet || []) {
      box.append(el("div", "white-space:pre;" + (current ? "background:#e0457b33;" : "opacity:.75"),
        String(n).padStart(4) + "  " + code));
    }
    if (d.hint) box.append(el("div", "margin-top:10px;color:#ffd479", "Hint: " + d.hint));
    const details = el("details", "margin-top:10px");
    details.append(el("summary", "cursor:pointer", "Full traceback"), el("pre", "white-space:pre-wrap", d.traceback));
    box.append(details);
    document.body.append(box);
  }
})();
