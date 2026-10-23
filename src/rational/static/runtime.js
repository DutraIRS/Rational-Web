/* Rational Web browser runtime (protocol v1).
 * Event delegation -> POST /_rational/event -> morph patched components.
 * No framework, no build step. Python never runs here. */
(() => {
  "use strict";
  const manifestEl = document.getElementById("rw-manifest");
  if (!manifestEl || window.rational) return;
  let M = JSON.parse(manifestEl.textContent);
  const PROTOCOL = 1;
  const INPUT_DEBOUNCE_MS = 150;
  let rev = M.rev;
  let lastSeq = M.seq || 0;
  let busy = false;
  let source = null;
  let epoch = 0;  // bumped on every client-side navigation so late responses from the old page are ignored
  let navAbort = null;
  let here = location.pathname + location.search;
  const held = [];  // pushed batches that arrived while an event was in flight
  const queue = [];
  const timers = new Map();

  // ---- event delegation ------------------------------------------------------------
  const DOM_EVENTS = { click: "click", input: "input", change: "change", submit: "submit", keydown: "keydown", focusout: "blur" };

  for (const [domType, name] of Object.entries(DOM_EVENTS)) {
    document.addEventListener(domType, (e) => {
      handle(e, name);
      if (domType === "keydown" && e.key === "Enter" && !e.isComposing) handle(e, "enter");
    });
  }

  function handle(e, name) {
    const target = e.target instanceof Element ? e.target : null;
    if (!target) return;
    const el = target.closest(`[data-rw-on-${name}],[data-rw-js-${name}]`);
    if (!el) return;
    const ops = el.getAttribute(`data-rw-js-${name}`);
    const handler = el.getAttribute(`data-rw-on-${name}`);
    if (handler && (name === "submit" || name === "enter" || (name === "click" && el.closest("a[href]")))) {
      e.preventDefault();
    }
    if (ops && runOps(JSON.parse(ops), el) === false) { e.preventDefault(); return; }
    if (!handler) return;
    if (name === "click" && (el.disabled || el.getAttribute("aria-disabled") === "true")) return;
    if (name === "input") {
      clearTimeout(timers.get(el));
      timers.set(el, setTimeout(() => { timers.delete(el); enqueue(handler, name, el, e); }, INPUT_DEBOUNCE_MS));
      return;
    }
    flushPendingInputs();
    enqueue(handler, name, el, e);
  }

  function flushPendingInputs() {
    // Make sure "type then click" sends the typed value before the click.
    for (const [el, t] of timers) {
      clearTimeout(t);
      timers.delete(el);
      const h = el.getAttribute("data-rw-on-input");
      if (h) enqueue(h, "input", el, null);
    }
  }

  function valueOf(el) {
    if (el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio")) return el.checked;
    if (el instanceof HTMLSelectElement && el.multiple) return Array.from(el.selectedOptions, (o) => o.value);
    return "value" in el ? el.value : null;
  }

  function formData(form) {
    const out = {};
    for (const [k, v] of new FormData(form)) {
      if (typeof v !== "string") continue;
      if (k in out) out[k] = [].concat(out[k], v); else out[k] = v;
    }
    return out;
  }

  function payloadFor(name, el, e) {
    if (name === "submit") return { form: formData(el) };
    if (name === "input" || name === "change" || name === "blur") return { value: valueOf(el) };
    if (name === "keydown" || name === "enter") return { key: e ? e.key : null, value: valueOf(el) };
    return {};
  }

  // ---- transport ------------------------------------------------------------------------
  function enqueue(handler, name, el, e) {
    const payload = payloadFor(name, el, e);
    if (name === "input") {
      const pending = queue.find((q) => q.handler === handler && q.name === "input");
      if (pending) { pending.payload = payload; return; }
    }
    queue.push({ handler, name, el, payload });
    pump();
  }

  async function pump() {
    if (busy) return;
    const item = queue.shift();
    if (!item) return;
    if (!M.page) { queue.length = 0; return; }  // a page without events (navigation-only manifest)
    busy = true;
    const mine = epoch;
    const el = item.el;
    if (el && item.name !== "input") el.setAttribute("aria-busy", "true");
    try {
      const res = await fetch(M.endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-RW-CSRF": M.csrf },
        body: JSON.stringify({ v: PROTOCOL, page: M.page, rev, handler: item.handler, payload: item.payload }),
      });
      if (mine !== epoch) return;  // we navigated away while this was in flight
      if (res.status === 410) { location.reload(); return; }
      const data = await res.json().catch(() => ({ error: { code: "bad_response", message: "Unexpected response" } }));
      if (mine !== epoch) return;
      // Pushed batches rendered before this response go first, so older HTML never overwrites newer.
      const seq = typeof data.seq === "number" ? data.seq : Infinity;
      held.sort((a, b) => a.seq - b.seq);
      while (held.length && held[0].seq < seq) apply(held.shift());
      apply(data);
      while (held.length) apply(held.shift());
      if (data.error) showError(data.error, el);
      else if (el && item.name === "submit") clearErrors(el);
    } catch (err) {
      while (held.length) apply(held.shift());
      emit(document, "rw:offline", { error: String(err) });
      if (M.debug) console.error("[rational]", err);
    } finally {
      if (el) el.removeAttribute("aria-busy");
      busy = false;
      pump();
    }
  }

  // ---- server push -------------------------------------------------------------------------
  function openStream() {
    if (source || !M.stream || typeof EventSource === "undefined") return;
    source = new EventSource(`${M.stream}?page=${encodeURIComponent(M.page)}`);
    source.onmessage = (m) => {
      let data;
      try { data = JSON.parse(m.data); } catch { return; }
      // After a reconnect, a seq ahead of ours means batches were missed: resync with a reload.
      if (typeof data.hello === "number") { if (data.hello > lastSeq) location.reload(); return; }
      if (busy) held.push(data); else apply(data);
    };
    source.onerror = () => {
      if (source && source.readyState === EventSource.CLOSED) { source.close(); source = null; }
    };
  }

  function apply(data) {
    if (typeof data.seq === "number" && data.seq > lastSeq) lastSeq = data.seq;
    if (typeof data.rev === "number") rev = data.rev;
    if (data.csrf) M.csrf = data.csrf;
    if (data.css && data.css.length) insertCss(data.css);
    for (const p of data.patches || []) {
      if (p.op !== "morph") continue;
      const el = document.querySelector(`[data-rw-c="${CSS.escape(p.id)}"]`);
      if (!el) continue;
      const tpl = document.createElement("template");
      tpl.innerHTML = p.html;
      const next = tpl.content.firstElementChild;
      if (next) morph(el, next);
    }
    for (const a of data.actions || []) {
      if (a.op === "navigate" && isSameOrigin(a.url)) go(a.url.startsWith("/") ? (M.base || "") + a.url : a.url);
      else if (a.op === "reload") location.reload();
      else if (a.op === "stream") { M.stream = M.stream || M.endpoint.replace(/event$/, "stream"); openStream(); }
      else if (a.op === "js") runOps(a.ops, document.body);
    }
    emit(document, "rw:updated", { rev });
  }

  function insertCss(rules) {
    const sheet = document.getElementById("rw-styles").sheet;
    for (const rule of rules) {
      try { sheet.insertRule(rule, sheet.cssRules.length); } catch { if (M.debug) console.warn("[rational] bad rule", rule); }
    }
  }

  function isSameOrigin(url) {
    try { return new URL(url, location.href).origin === location.origin; } catch { return false; }
  }

  // ---- errors ------------------------------------------------------------------------------
  function showError(error, el) {
    const form = el && el.closest("form");
    if (error.code === "validation_error" && form) {
      clearErrors(form);
      let first = null;
      for (const d of error.details || []) {
        const name = String(d.field).split(".")[0];
        const field = form.querySelector(`[name="${CSS.escape(name)}"]`);
        const slot = form.querySelector(`[data-rw-error-for="${CSS.escape(name)}"]`);
        if (field) { field.setAttribute("aria-invalid", "true"); first = first || field; }
        if (slot) { slot.textContent = d.message; slot.hidden = false; }
      }
      if (first) first.focus();
    }
    emit(el || document, "rw:error", error);
    if (M.debug && error.code !== "validation_error") console.warn("[rational]", error.code, error.message);
  }

  function clearErrors(form) {
    for (const f of form.querySelectorAll("[aria-invalid=true]")) f.removeAttribute("aria-invalid");
    for (const s of form.querySelectorAll("[data-rw-error-for]")) { s.textContent = ""; s.hidden = true; }
  }

  function emit(target, type, detail) {
    target.dispatchEvent(new CustomEvent(type, { bubbles: true, detail }));
  }

  // ---- morphing --------------------------------------------------------------------------
  function keyOf(n) {
    if (n.nodeType !== 1) return null;
    return n.getAttribute("data-rw-key") ?? n.getAttribute("data-rw-c") ?? (n.id || null);
  }

  function same(a, b) {
    return a.nodeType === b.nodeType && a.nodeName === b.nodeName && keyOf(a) === keyOf(b);
  }

  function morph(from, to) {
    if (!same(from, to)) { from.replaceWith(to); return; }
    if (from.nodeType !== 1) {
      if (from.nodeValue !== to.nodeValue) from.nodeValue = to.nodeValue;
      return;
    }
    if (from.hasAttribute("data-rw-ignore")) return;
    syncAttributes(from, to);
    if (from instanceof HTMLTextAreaElement) {
      if (document.activeElement !== from && from.value !== to.value) from.value = to.value;
      return;
    }
    morphChildren(from, to);
    syncFormState(from, to);
  }

  function syncAttributes(from, to) {
    const focused = document.activeElement === from;
    for (const { name } of Array.from(from.attributes)) {
      if (!to.hasAttribute(name) && !(focused && name === "value")) from.removeAttribute(name);
    }
    for (const { name, value } of Array.from(to.attributes)) {
      if (focused && name === "value") continue;
      if (from.getAttribute(name) !== value) from.setAttribute(name, value);
    }
  }

  function syncFormState(from, to) {
    if (from instanceof HTMLInputElement) {
      if (from.type === "checkbox" || from.type === "radio") from.checked = to.hasAttribute("checked");
      else if (document.activeElement !== from) {
        const v = to.getAttribute("value") ?? "";
        if (from.value !== v) from.value = v;
      }
    } else if (from instanceof HTMLSelectElement) {
      const selected = Array.from(to.options).find((o) => o.hasAttribute("selected"));
      if (selected && from.value !== selected.value) from.value = selected.value;
    }
  }

  function morphChildren(parent, next) {
    const oldNodes = Array.from(parent.childNodes);
    const keyed = new Map();
    for (const n of oldNodes) { const k = keyOf(n); if (k !== null) keyed.set(k, n); }
    const used = new Set();
    let cursor = 0;
    Array.from(next.childNodes).forEach((n, idx) => {
      const k = keyOf(n);
      let match = null;
      if (k !== null) {
        const c = keyed.get(k);
        if (c && !used.has(c) && same(c, n)) match = c;
      } else {
        while (cursor < oldNodes.length && (used.has(oldNodes[cursor]) || keyOf(oldNodes[cursor]) !== null)) cursor++;
        const c = oldNodes[cursor];
        if (c && same(c, n)) { match = c; cursor++; }
      }
      let node = n;
      if (match) { used.add(match); morph(match, n); node = match; }
      const at = parent.childNodes[idx];
      if (at !== node) parent.insertBefore(node, at || null);
    });
    for (const n of oldNodes) if (!used.has(n) && n.parentNode === parent) parent.removeChild(n);
  }

  // ---- declarative client operations -----------------------------------------------------
  function targets(el, sel) {
    if (sel === null || sel === undefined) return [el];
    if (sel.startsWith("closest:")) { const t = el.closest(sel.slice(8)); return t ? [t] : []; }
    return Array.from(document.querySelectorAll(sel));
  }

  function setTheme(mode) {
    const root = document.documentElement;
    if (mode === "light" || mode === "dark") root.setAttribute("data-theme", mode);
    else root.removeAttribute("data-theme");
    document.cookie = `rw_theme=${mode === "system" ? "" : mode}; path=/; max-age=31536000; samesite=lax`;
  }

  const OPS = {
    toggle_class: (el, sel, cls) => targets(el, sel).forEach((t) => t.classList.toggle(cls)),
    add_class: (el, sel, cls) => targets(el, sel).forEach((t) => t.classList.add(cls)),
    remove_class: (el, sel, cls) => targets(el, sel).forEach((t) => t.classList.remove(cls)),
    set_attr: (el, sel, name, value) => targets(el, sel).forEach((t) => t.setAttribute(name, value)),
    toggle_attr: (el, sel, name, on, off) => targets(el, sel).forEach((t) => t.setAttribute(name, t.getAttribute(name) === on ? off : on)),
    focus: (el, sel) => { const t = targets(el, sel)[0]; if (t) t.focus(); },
    confirm: (_el, _sel, message) => window.confirm(message),
    set_theme: (_el, _sel, mode) => setTheme(mode),
    toggle_theme: () => {
      const root = document.documentElement;
      const current = root.getAttribute("data-theme") ||
        (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      setTheme(current === "dark" ? "light" : "dark");
    },
    show: (el, sel) => targets(el, sel).forEach((t) => { t.hidden = false; }),
    hide: (el, sel) => targets(el, sel).forEach((t) => { t.hidden = true; }),
    toggle: (el, sel) => targets(el, sel).forEach((t) => { t.hidden = !t.hidden; }),
    remove: (el, sel) => targets(el, sel).forEach((t) => t.remove()),
    set_text: (el, sel, text) => targets(el, sel).forEach((t) => { t.textContent = text; }),
    set_value: (el, sel, value) => targets(el, sel).forEach((t) => {
      t.value = value;
      t.dispatchEvent(new Event("input", { bubbles: true }));  // let on_input handlers see the change
    }),
    copy: (el, sel, text) => {
      const t = targets(el, sel)[0];
      const value = text ?? (t ? (("value" in t && t.value) || t.textContent) : "");
      if (navigator.clipboard) navigator.clipboard.writeText(value).catch(() => {});
    },
    scroll_to: (el, sel) => { const t = targets(el, sel)[0]; if (t) t.scrollIntoView({ block: "center" }); },
    open_dialog: (el, sel) => { const t = targets(el, sel)[0]; if (t && typeof t.showModal === "function" && !t.open) t.showModal(); },
    close_dialog: (el, sel) => { const t = targets(el, sel)[0]; if (t && typeof t.close === "function") t.close(); },
  };

  function runOps(ops, el) {
    for (const [op, ...args] of ops) {
      const fn = OPS[op];
      if (!fn) { if (M.debug) console.warn("[rational] unknown op", op); continue; }
      if (fn(el, ...args) === false) return false;  // e.g. a declined confirm()
    }
    return true;
  }

  // ---- client-side navigation (App(client_nav=True)) ---------------------------------------
  function go(url) {
    if (M.nav) navigate(url, true); else location.assign(url);
  }

  document.addEventListener("click", (e) => {
    if (!M.nav || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target instanceof Element ? e.target.closest("a[href]") : null;
    if (!a || (a.target && a.target !== "_self") || a.hasAttribute("download") || a.hasAttribute("data-rw-reload")) return;
    if (a.getAttribute("rel")?.split(/\s+/).includes("external")) return;
    const url = new URL(a.href, location.href);
    if (url.origin !== location.origin || !/^https?:$/.test(url.protocol)) return;
    if (url.pathname === location.pathname && url.search === location.search && url.hash) return;  // in-page anchor
    e.preventDefault();
    navigate(url.href, true);
  });

  window.addEventListener("popstate", () => {
    if (!M.nav || location.pathname + location.search === here) return;  // hash-only changes stay in place
    navigate(location.href, false);
  });

  async function navigate(url, push) {
    if (navAbort) navAbort.abort();
    const abort = navAbort = new AbortController();
    emit(document, "rw:navigating", { url });
    document.documentElement.setAttribute("aria-busy", "true");
    try {
      const res = await fetch(url, { credentials: "same-origin", headers: { Accept: "text/html" }, signal: abort.signal });
      if (!(res.headers.get("Content-Type") || "").includes("text/html")) throw new Error("not a page");
      const doc = new DOMParser().parseFromString(await res.text(), "text/html");
      if (abort.signal.aborted) return;
      swap(doc, res.url || url, push);
    } catch (err) {
      if (abort.signal.aborted) return;
      if (M.debug) console.warn("[rational] client navigation failed, loading normally:", err);
      location.assign(url);  // anything unexpected falls back to a normal page load
    } finally {
      if (navAbort === abort) { navAbort = null; document.documentElement.removeAttribute("aria-busy"); }
    }
  }

  function swap(doc, url, push) {
    const nextManifest = doc.getElementById("rw-manifest");
    if (!nextManifest) { location.assign(url); return; }  // a page without the runtime
    epoch++;
    if (source) { source.close(); source = null; }
    queue.length = 0;
    held.length = 0;
    for (const t of timers.values()) clearTimeout(t);
    timers.clear();
    M = JSON.parse(nextManifest.textContent);
    rev = M.rev;
    lastSeq = M.seq || 0;
    busy = false;
    if (push) history.pushState(null, "", url);
    here = location.pathname + location.search;
    document.title = doc.title;
    const description = doc.querySelector('meta[name="description"]');
    const current = document.querySelector('meta[name="description"]');
    if (description && current) current.setAttribute("content", description.getAttribute("content") || "");
    else if (description) document.head.appendChild(document.importNode(description, true));
    else if (current) current.remove();
    document.getElementById("rw-styles").textContent = doc.getElementById("rw-styles").textContent;
    const keep = document.getElementById("rw-manifest");
    for (const n of Array.from(document.body.childNodes)) if (n !== keep && n.nodeName !== "SCRIPT") n.remove();
    keep.textContent = nextManifest.textContent;
    for (const n of Array.from(doc.body.childNodes)) {
      if (n.nodeName === "SCRIPT") continue;
      document.body.insertBefore(document.importNode(n, true), keep);
    }
    openStream();
    const hash = new URL(url).hash;
    const anchor = hash && document.getElementById(decodeURIComponent(hash.slice(1)));
    if (anchor) anchor.scrollIntoView(); else window.scrollTo(0, 0);
    const heading = document.querySelector("main, h1");
    if (heading) { if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1"); heading.focus({ preventScroll: true }); }
    emit(document, "rw:navigated", { url });
  }

  // ---- public hook for custom scripts ------------------------------------------------------
  openStream();
  window.rational = {
    version: PROTOCOL,
    /** Call a @remote method: rational.call("todo", "add", {title: "x"}) -> POST /api/todo/add */
    async call(service, method, body) {
      const res = await fetch(`${M.api}/${encodeURIComponent(service)}/${encodeURIComponent(method)}`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-RW-CSRF": M.csrf },
        body: JSON.stringify(body || {}),
      });
      const data = await res.json();
      if (!res.ok) throw Object.assign(new Error(data.error?.message || res.statusText), { response: data });
      return data;
    },
  };
})();
