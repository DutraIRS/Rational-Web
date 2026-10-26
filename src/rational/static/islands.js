/* Rational Web client components (islands): Python semantics for compiled code ($rt) and hydration.
 * Loaded only on pages that use a ClientComponent, after runtime.js. Each compiled component module
 * calls rational.island(key, factory); every <rw-island> element of that key then comes alive. */
(() => {
  "use strict";
  const R = window.rational;
  if (!R || R.island) return;

  // ---- errors --------------------------------------------------------------------------------
  class PyError extends Error {
    constructor(type, message) { super(message); this.name = type; this.pyType = type; }
  }
  class Cancelled extends Error {}
  const none = (x) => x === null || x === undefined;
  const error = (type, message) => new PyError(type, none(message) ? "" : str(message));
  const caught = (e, types) => e instanceof PyError ? types.includes(e.pyType) : types.includes("RuntimeError");

  // ---- types, truthiness, equality ------------------------------------------------------------------
  const hasOwn = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const isDict = (x) => x !== null && typeof x === "object" && !Array.isArray(x);
  const isNum = (x) => typeof x === "number" || typeof x === "boolean";

  function typeName(x) {
    if (x === null || x === undefined) return "NoneType";
    if (typeof x === "boolean") return "bool";
    if (typeof x === "number") return Number.isInteger(x) ? "int" : "float";
    if (typeof x === "string") return "str";
    if (Array.isArray(x)) return "list";
    if (typeof x === "function") return "function";
    return "dict";
  }

  function truthy(x) {
    if (x === null || x === undefined || x === false || x === 0 || x === "") return false;
    if (Array.isArray(x)) return x.length > 0;
    if (isDict(x)) return Object.keys(x).length > 0;
    return true;
  }

  function eq(a, b) {
    if (a === b) return true;
    if (none(a) || none(b)) return none(a) && none(b);
    if (isNum(a) && isNum(b)) return Number(a) === Number(b);
    if (Array.isArray(a)) return Array.isArray(b) && a.length === b.length && a.every((x, i) => eq(x, b[i]));
    if (isDict(a)) {
      if (!isDict(b)) return false;
      const keys = Object.keys(a);
      return keys.length === Object.keys(b).length && keys.every((k) => hasOwn(b, k) && eq(a[k], b[k]));
    }
    return false;
  }

  function cmp(a, b) {
    if (isNum(a) && isNum(b)) { a = Number(a); b = Number(b); return a < b ? -1 : a > b ? 1 : 0; }
    if (typeof a === "string" && typeof b === "string") return a < b ? -1 : a > b ? 1 : 0;
    if (Array.isArray(a) && Array.isArray(b)) {
      for (let i = 0; i < Math.min(a.length, b.length); i++) { if (!eq(a[i], b[i])) return cmp(a[i], b[i]); }
      return a.length - b.length;
    }
    throw error("TypeError", `'<' not supported between instances of '${typeName(a)}' and '${typeName(b)}'`);
  }

  function contains(container, item) {
    if (typeof container === "string") {
      if (typeof item !== "string") throw error("TypeError", "'in <string>' requires string as left operand");
      return container.includes(item);
    }
    if (Array.isArray(container)) return container.some((x) => eq(x, item));
    if (isDict(container)) return hasOwn(container, item);
    throw error("TypeError", `argument of type '${typeName(container)}' is not iterable`);
  }

  // ---- arithmetic --------------------------------------------------------------------------------
  function operands(op, a, b) {
    return error("TypeError", `unsupported operand type(s) for ${op}: '${typeName(a)}' and '${typeName(b)}'`);
  }
  function add(a, b) {
    if (isNum(a) && isNum(b)) return Number(a) + Number(b);
    if (typeof a === "string" && typeof b === "string") return a + b;
    if (Array.isArray(a) && Array.isArray(b)) return a.concat(b);
    throw operands("+", a, b);
  }
  function repeat(seq, n) {
    if (!Number.isInteger(Number(n))) throw error("TypeError", "can't multiply sequence by non-int");
    const k = Math.max(0, Number(n));
    if (typeof seq === "string") return seq.repeat(k);
    let out = [];
    for (let i = 0; i < k; i++) out = out.concat(seq);
    return out;
  }
  function mul(a, b) {
    if (isNum(a) && isNum(b)) return Number(a) * Number(b);
    if ((typeof a === "string" || Array.isArray(a)) && isNum(b)) return repeat(a, b);
    if ((typeof b === "string" || Array.isArray(b)) && isNum(a)) return repeat(b, a);
    throw operands("*", a, b);
  }
  function numbers(op, a, b) {
    if (!isNum(a) || !isNum(b)) throw operands(op, a, b);
    if (Number(b) === 0) throw error("ZeroDivisionError", op === "/" ? "division by zero" : "integer division or modulo by zero");
    return [Number(a), Number(b)];
  }
  const div = (a, b) => { const [x, y] = numbers("/", a, b); return x / y; };
  const floordiv = (a, b) => { const [x, y] = numbers("//", a, b); return Math.floor(x / y); };
  function mod(a, b) {
    if (typeof a === "string") throw error("TypeError", "printf-style formatting is not supported in client code; use an f-string");
    const [x, y] = numbers("%", a, b);
    const r = x % y;
    return r !== 0 && (r < 0) !== (y < 0) ? r + y : r;
  }
  function round(x, n) {
    if (n === undefined || n === null) {
      const r = Math.round(x);
      return Math.abs(x % 1) === 0.5 ? 2 * Math.round(x / 2) : r;  // half to even, like Python
    }
    if (n < 0) { const f = 10 ** -n; return round(x / f) * f; }
    return Number(Number(x).toFixed(n));
  }

  // ---- text ---------------------------------------------------------------------------------------
  function numStr(n) {
    if (Number.isNaN(n)) return "nan";
    if (n === Infinity) return "inf";
    if (n === -Infinity) return "-inf";
    return String(n);
  }
  function str(x) {
    if (x === null || x === undefined) return "None";
    if (x === true) return "True";
    if (x === false) return "False";
    if (typeof x === "string") return x;
    if (typeof x === "number") return numStr(x);
    if (x instanceof Error) return x.message;
    return repr(x);
  }
  function reprStr(s) {
    const quote = s.includes("'") && !s.includes('"') ? '"' : "'";
    let out = "";
    for (const ch of s) {
      if (ch === "\\") out += "\\\\";
      else if (ch === quote) out += "\\" + quote;
      else if (ch === "\n") out += "\\n";
      else if (ch === "\r") out += "\\r";
      else if (ch === "\t") out += "\\t";
      else out += ch;
    }
    return quote + out + quote;
  }
  function repr(x) {
    if (typeof x === "string") return reprStr(x);
    if (Array.isArray(x)) return "[" + x.map(repr).join(", ") + "]";
    if (isDict(x)) return "{" + Object.keys(x).map((k) => `${reprStr(k)}: ${repr(x[k])}`).join(", ") + "}";
    if (typeof x === "function") return "<function>";
    return str(x);
  }

  const SPEC = /^(?:(.)?([<>=^]))?([+\- ])?(z)?(#)?(0)?(\d+)?([,_])?(?:\.(\d+))?([bcdeEfFgGosxX%])?$/su;
  function group(digits, sep) {
    const [whole, frac] = digits.split(".");
    const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, sep);
    return frac === undefined ? grouped : grouped + "." + frac;
  }
  function general(n, precision, upper) {
    const p = precision === 0 ? 1 : precision;
    if (n === 0) return "0";
    const exp = Math.floor(Math.log10(Math.abs(n)));
    let out;
    if (exp < -4 || exp >= p) {
      out = n.toExponential(p - 1).replace(/\.?0+e/, "e");
      out = out.replace(/e([+-])(\d)$/, "e$10$2");
    } else {
      out = n.toFixed(Math.max(0, p - 1 - exp));
      if (out.includes(".")) out = out.replace(/\.?0+$/, "");
    }
    return upper ? out.toUpperCase() : out;
  }
  function fmt(value, spec) {
    if (spec === "") return str(value);
    const m = SPEC.exec(spec);
    if (!m) throw error("ValueError", `Invalid format specifier '${spec}'`);
    const [, , , sign, , , zero, width, sep, precision, type] = m;
    let [, fill, align] = m;
    const numeric = isNum(value);
    let body;
    if (!numeric || type === "s") {
      if (type !== undefined && type !== "s") throw error("ValueError", `Unknown format code '${type}' for object of type '${typeName(value)}'`);
      if (numeric) throw error("ValueError", `Unknown format code 's' for object of type '${typeName(value)}'`);
      body = str(value);
      if (precision !== undefined) body = Array.from(body).slice(0, Number(precision)).join("");
    } else {
      let n = Number(value);
      const negative = n < 0 || Object.is(n, -0);
      n = Math.abs(n);
      const p = precision === undefined ? 6 : Number(precision);
      let digits;
      switch (type) {
        case "d":
          if (!Number.isInteger(n)) throw error("ValueError", "Unknown format code 'd' for object of type 'float'");
          digits = String(n);
          break;
        case "f": case "F": digits = Number.isFinite(n) ? n.toFixed(p) : numStr(n); break;
        case "%": digits = (n * 100).toFixed(p) + "%"; break;
        case "e": case "E":
          digits = n.toExponential(p).replace(/e([+-])(\d)$/, "e$10$2");
          if (type === "E") digits = digits.toUpperCase();
          break;
        case "g": case "G": digits = general(n, p, type === "G"); break;
        case "x": digits = Math.trunc(n).toString(16); break;
        case "X": digits = Math.trunc(n).toString(16).toUpperCase(); break;
        case "o": digits = Math.trunc(n).toString(8); break;
        case "b": digits = Math.trunc(n).toString(2); break;
        case "c": digits = String.fromCodePoint(n); break;
        default:
          digits = precision === undefined ? numStr(n) : general(n, p, false);
          if (precision !== undefined && !/[.e]|inf|nan/.test(digits)) digits += ".0";
      }
      if (sep) digits = group(digits, sep);
      body = (negative ? "-" : sign === "+" ? "+" : sign === " " ? " " : "") + digits;
      if (zero && fill === undefined && align === undefined) { fill = "0"; align = "="; }
    }
    const w = width === undefined ? 0 : Number(width);
    const len = Array.from(body).length;
    if (len >= w) return body;
    const pad = (k) => (fill === undefined ? " " : fill).repeat(k);
    switch (align || (numeric ? ">" : "<")) {
      case "<": return body + pad(w - len);
      case ">": return pad(w - len) + body;
      case "^": { const left = Math.floor((w - len) / 2); return pad(left) + body + pad(w - len - left); }
      default: { const s = /^[+\- ]/.test(body) ? body[0] : ""; return s + pad(w - len) + body.slice(s.length); }
    }
  }

  // ---- conversions and builtins ------------------------------------------------------------------
  function int(x, base) {
    if (typeof x === "boolean") return Number(x);
    if (typeof x === "number") {
      if (!Number.isFinite(x)) throw error("ValueError", `cannot convert float ${numStr(x)} to integer`);
      return Math.trunc(x);
    }
    if (typeof x === "string") {
      const b = base === undefined || base === null ? 10 : base;
      const s = x.trim().replace(/(?<=[0-9a-zA-Z])_(?=[0-9a-zA-Z])/g, "");
      const digits = "0123456789abcdefghijklmnopqrstuvwxyz".slice(0, b);
      const re = new RegExp(`^[+-]?[${digits}]+$`, "i");
      if (!re.test(s)) throw error("ValueError", `invalid literal for int() with base ${b}: ${repr(x)}`);
      return parseInt(s, b);
    }
    throw error("TypeError", `int() argument must be a string or a number, not '${typeName(x)}'`);
  }
  function float(x) {
    if (isNum(x)) return Number(x);
    if (typeof x === "string") {
      const s = x.trim().toLowerCase().replace(/(?<=\d)_(?=\d)/g, "");
      if (/^[+-]?(inf|infinity)$/.test(s)) return s.startsWith("-") ? -Infinity : Infinity;
      if (/^[+-]?nan$/.test(s)) return NaN;
      if (/^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/.test(s)) return Number(s);
      throw error("ValueError", `could not convert string to float: ${repr(x)}`);
    }
    throw error("TypeError", `float() argument must be a string or a real number, not '${typeName(x)}'`);
  }
  function convert(value, kind) {
    if (kind === "str") return none(value) ? "" : str(value);
    if (kind === "bool") return typeof value === "boolean" ? value : truthy(value);
    if (kind === "int") return int(value);
    return float(value);
  }
  function len(x) {
    if (typeof x === "string") return Array.from(x).length;
    if (Array.isArray(x)) return x.length;
    if (isDict(x)) return Object.keys(x).length;
    throw error("TypeError", `object of type '${typeName(x)}' has no len()`);
  }
  function iter(x) {
    if (Array.isArray(x)) return x;
    if (typeof x === "string") return Array.from(x);
    if (isDict(x)) return Object.keys(x);
    throw error("TypeError", `'${typeName(x)}' object is not iterable`);
  }
  const list = (x) => (x === undefined ? [] : Array.from(iter(x)));
  function dict(x) {
    if (x === undefined || x === null) return {};
    if (isDict(x)) return { ...x };
    const out = {};
    for (const pair of iter(x)) { const [k, v] = unpack(pair, 2); set(out, k, v); }
    return out;
  }
  function unpack(x, n) {
    const items = list(x);
    if (items.length !== n) throw error("ValueError", `expected ${n} values to unpack, got ${items.length}`);
    return items;
  }
  function range(start, stop, step) {
    if (stop === undefined) { stop = start; start = 0; }
    step = step === undefined ? 1 : step;
    if (step === 0) throw error("ValueError", "range() arg 3 must not be zero");
    const out = [];
    for (let i = start; step > 0 ? i < stop : i > stop; i += step) out.push(i);
    return out;
  }
  const enumerate = (xs, start = 0) => iter(xs).map((x, i) => [i + start, x]);
  function zip(...seqs) {
    const lists = seqs.map(list);
    const n = lists.length ? Math.min(...lists.map((l) => l.length)) : 0;
    return Array.from({ length: n }, (_, i) => lists.map((l) => l[i]));
  }
  function sorted(xs, key, reverse) {
    const k = key || ((x) => x);
    const out = list(xs).map((x) => [k(x), x]);
    out.sort((a, b) => cmp(a[0], b[0]) * (reverse ? -1 : 1));
    return out.map((pair) => pair[1]);
  }
  const reversed = (xs) => list(xs).reverse();
  function extreme(sign, items, opts) {
    const xs = list(items);
    if (!xs.length) {
      if (opts.default !== undefined) return opts.default;
      throw error("ValueError", `${sign > 0 ? "max" : "min"}() arg is an empty sequence`);
    }
    const k = opts.key || ((x) => x);
    let best = xs[0];
    let bestKey = k(best);
    for (const x of xs.slice(1)) { const kx = k(x); if (cmp(kx, bestKey) * sign > 0) { best = x; bestKey = kx; } }
    return best;
  }
  function sum(xs, start = 0) {
    let total = start;
    for (const x of iter(xs)) total = add(total, x);
    return total;
  }
  function isinstance(x, kinds) {
    const t = typeName(x);
    return kinds.some((k) => k === t || (k === "int" && t === "bool"));
  }

  // ---- items, slices -----------------------------------------------------------------------------
  function index(seq, i, what) {
    if (typeof i === "boolean") i = Number(i);
    if (!Number.isInteger(i)) throw error("TypeError", `${what} indices must be integers`);
    const j = i < 0 ? seq.length + i : i;
    if (j < 0 || j >= seq.length) throw error("IndexError", `${what} index out of range`);
    return j;
  }
  function get(x, k) {
    if (Array.isArray(x)) return x[index(x, k, "list")];
    if (typeof x === "string") { const chars = Array.from(x); return chars[index(chars, k, "string")]; }
    if (isDict(x)) { if (!hasOwn(x, k)) throw error("KeyError", repr(k)); return x[k]; }
    throw error("TypeError", `'${typeName(x)}' object is not subscriptable`);
  }
  function set(x, k, v) {
    if (Array.isArray(x)) { x[index(x, k, "list")] = v; return null; }
    if (isDict(x)) {
      if (k === "__proto__") Object.defineProperty(x, k, { value: v, writable: true, enumerable: true, configurable: true });
      else x[k] = v;
      return null;
    }
    throw error("TypeError", `'${typeName(x)}' object does not support item assignment`);
  }
  function del(x, k) {
    if (Array.isArray(x)) { x.splice(index(x, k, "list"), 1); return null; }
    if (isDict(x)) { if (!hasOwn(x, k)) throw error("KeyError", repr(k)); delete x[k]; return null; }
    throw error("TypeError", `'${typeName(x)}' object doesn't support item deletion`);
  }
  function slice(x, lo, hi, step) {
    const seq = typeof x === "string" ? Array.from(x) : x;
    if (!Array.isArray(seq)) throw error("TypeError", `'${typeName(x)}' object is not subscriptable`);
    const n = seq.length;
    const s = step === null || step === undefined ? 1 : step;
    if (s === 0) throw error("ValueError", "slice step cannot be zero");
    const clamp = (v, dflt) => {
      if (v === null || v === undefined) return dflt;
      if (v < 0) v += n;
      return s > 0 ? Math.min(Math.max(v, 0), n) : Math.min(Math.max(v, -1), n - 1);
    };
    const start = clamp(lo, s > 0 ? 0 : n - 1);
    const stop = clamp(hi, s > 0 ? n : -1);
    const out = [];
    for (let i = start; s > 0 ? i < stop : i > stop; i += s) out.push(seq[i]);
    return typeof x === "string" ? out.join("") : out;
  }

  // ---- methods of str, list and dict ------------------------------------------------------------------
  const isSpace = (c) => /\s/.test(c);
  function stripChars(s, chars, left, right) {
    const test = none(chars) ? isSpace : (c) => chars.includes(c);
    const cs = Array.from(s);
    let a = 0;
    let b = cs.length;
    if (left) while (a < b && test(cs[a])) a++;
    if (right) while (b > a && test(cs[b - 1])) b--;
    return cs.slice(a, b).join("");
  }
  function split(s, sep, maxsplit) {
    const limit = none(maxsplit) || maxsplit < 0 ? Infinity : maxsplit;
    if (none(sep)) {
      const out = [];
      let rest = s.replace(/^\s+/, "");
      while (rest) {
        const m = /\s+/.exec(rest);
        if (out.length >= limit || !m) { out.push(rest); break; }
        out.push(rest.slice(0, m.index));
        rest = rest.slice(m.index + m[0].length);
      }
      return out;
    }
    if (sep === "") throw error("ValueError", "empty separator");
    const out = [];
    let rest = s;
    while (out.length < limit) {
      const i = rest.indexOf(sep);
      if (i < 0) break;
      out.push(rest.slice(0, i));
      rest = rest.slice(i + sep.length);
    }
    out.push(rest);
    return out;
  }
  function count(seq, value) {
    if (typeof seq === "string") {
      if (value === "") return Array.from(seq).length + 1;
      return seq.split(value).length - 1;
    }
    return seq.filter((x) => eq(x, value)).length;
  }
  function find(s, sub, start, end, last) {
    const part = slice(s, none(start) ? null : start, none(end) ? null : end, null);
    const at = last ? part.lastIndexOf(sub) : part.indexOf(sub);
    if (at < 0) return -1;
    const offset = none(start) ? 0 : start < 0 ? Math.max(0, Array.from(s).length + start) : start;
    return Array.from(part.slice(0, at)).length + offset;
  }
  const affix = (s, test, start, end, which) => {
    const part = slice(s, none(start) ? null : start, none(end) ? null : end, null);
    return (Array.isArray(test) ? test : [test]).some((t) => (which ? part.endsWith(t) : part.startsWith(t)));
  };
  const justify = (s, width, fill, where) => {
    const f = none(fill) ? " " : fill;
    const n = Array.from(s).length;
    if (width <= n) return s;
    if (where === "l") return s + f.repeat(width - n);
    if (where === "r") return f.repeat(width - n) + s;
    const total = width - n;
    const left = Math.floor(total / 2) + (total & width & 1);  // CPython's rounding
    return f.repeat(left) + s + f.repeat(total - left);
  };
  const STR = {
    upper: (s) => s.toUpperCase(),
    lower: (s) => s.toLowerCase(),
    casefold: (s) => s.toLowerCase(),
    swapcase: (s) => Array.from(s, (c) => (c === c.toUpperCase() ? c.toLowerCase() : c.toUpperCase())).join(""),
    title: (s) => s.toLowerCase().replace(/(^|[^\p{L}])(\p{L})/gu, (_, a, b) => a + b.toUpperCase()),
    capitalize: (s) => (s ? Array.from(s)[0].toUpperCase() + Array.from(s).slice(1).join("").toLowerCase() : s),
    strip: (s, chars) => stripChars(s, chars, true, true),
    lstrip: (s, chars) => stripChars(s, chars, true, false),
    rstrip: (s, chars) => stripChars(s, chars, false, true),
    split,
    rsplit: (s, sep, maxsplit) => {
      if (none(maxsplit) || maxsplit < 0) return split(s, sep);
      const rev = (t) => Array.from(t).reverse().join("");
      return split(rev(s), none(sep) ? sep : rev(sep), maxsplit).map(rev).reverse();
    },
    splitlines: (s, keepends) => {
      const out = s.match(/[^\r\n]*(\r\n|\r|\n)|[^\r\n]+$/g) || [];
      return keepends ? out : out.map((line) => line.replace(/(\r\n|\r|\n)$/, ""));
    },
    join: (s, items) => list(items).map((x) => {
      if (typeof x !== "string") throw error("TypeError", `sequence item: expected str instance, ${typeName(x)} found`);
      return x;
    }).join(s),
    replace: (s, old, neu, n) => {
      if (none(n) || n < 0) return s.split(old).join(neu);
      let out = s;
      let done = 0;
      let at = 0;
      while (done < n) {
        const i = out.indexOf(old, at);
        if (i < 0) break;
        out = out.slice(0, i) + neu + out.slice(i + old.length);
        at = i + neu.length + (old === "" ? 1 : 0);
        done++;
      }
      return out;
    },
    startswith: (s, prefix, start, end) => affix(s, prefix, start, end, false),
    endswith: (s, suffix, start, end) => affix(s, suffix, start, end, true),
    find: (s, sub, start, end) => find(s, sub, start, end, false),
    rfind: (s, sub, start, end) => find(s, sub, start, end, true),
    index: (s, sub, start, end) => {
      const i = find(s, sub, start, end, false);
      if (i < 0) throw error("ValueError", "substring not found");
      return i;
    },
    count: (s, sub) => count(s, sub),
    isdigit: (s) => /^\p{Nd}+$/u.test(s),
    isnumeric: (s) => /^\p{N}+$/u.test(s),
    isalpha: (s) => /^\p{L}+$/u.test(s),
    isalnum: (s) => /^[\p{L}\p{N}]+$/u.test(s),
    isspace: (s) => /^\s+$/.test(s),
    isupper: (s) => /\p{Lu}/u.test(s) && s === s.toUpperCase(),
    islower: (s) => /\p{Ll}/u.test(s) && s === s.toLowerCase(),
    zfill: (s, width) => {
      const sign = /^[+-]/.test(s) ? s[0] : "";
      const body = s.slice(sign.length);
      return sign + "0".repeat(Math.max(0, width - Array.from(s).length)) + body;
    },
    center: (s, width, fill) => justify(s, width, fill, "c"),
    ljust: (s, width, fill) => justify(s, width, fill, "l"),
    rjust: (s, width, fill) => justify(s, width, fill, "r"),
    partition: (s, sep) => { const i = s.indexOf(sep); return i < 0 ? [s, "", ""] : [s.slice(0, i), sep, s.slice(i + sep.length)]; },
    rpartition: (s, sep) => { const i = s.lastIndexOf(sep); return i < 0 ? ["", "", s] : [s.slice(0, i), sep, s.slice(i + sep.length)]; },
    removeprefix: (s, p) => (p && s.startsWith(p) ? s.slice(p.length) : s),
    removesuffix: (s, p) => (p && s.endsWith(p) ? s.slice(0, -p.length) : s),
  };
  const LIST = {
    append: (l, x) => { l.push(x); return null; },
    extend: (l, xs) => { l.push(...list(xs)); return null; },
    insert: (l, i, x) => {
      const j = i < 0 ? Math.max(0, l.length + i) : Math.min(i, l.length);
      l.splice(j, 0, x);
      return null;
    },
    pop: (l, i) => {
      if (!l.length) throw error("IndexError", "pop from empty list");
      return l.splice(index(l, none(i) ? -1 : i, "pop"), 1)[0];
    },
    remove: (l, x) => {
      const i = l.findIndex((y) => eq(x, y));
      if (i < 0) throw error("ValueError", "list.remove(x): x not in list");
      l.splice(i, 1);
      return null;
    },
    index: (l, x) => { const i = l.findIndex((y) => eq(x, y)); if (i < 0) throw error("ValueError", `${repr(x)} is not in list`); return i; },
    count: (l, x) => count(l, x),
    sort: (l, key, reverse) => { const s = sorted(l, key, reverse); l.splice(0, l.length, ...s); return null; },
    reverse: (l) => { l.reverse(); return null; },
    copy: (l) => l.slice(),
    clear: (l) => { l.length = 0; return null; },
  };
  const DICT = {
    get: (d, k, dflt) => (hasOwn(d, k) ? d[k] : none(dflt) ? null : dflt),
    keys: (d) => Object.keys(d),
    values: (d) => Object.values(d),
    items: (d) => Object.keys(d).map((k) => [k, d[k]]),
    pop: (d, k, dflt) => {
      if (hasOwn(d, k)) { const v = d[k]; delete d[k]; return v; }
      if (dflt !== undefined) return dflt;
      throw error("KeyError", repr(k));
    },
    setdefault: (d, k, dflt) => { if (!hasOwn(d, k)) set(d, k, none(dflt) ? null : dflt); return d[k]; },
    update: (d, other) => { for (const [k, v] of Object.entries(dict(other))) set(d, k, v); return null; },
    copy: (d) => ({ ...d }),
    clear: (d) => { for (const k of Object.keys(d)) delete d[k]; return null; },
  };
  function method(obj, name, ...args) {
    const table = typeof obj === "string" ? STR : Array.isArray(obj) ? LIST : isDict(obj) ? DICT : null;
    if (!table || !hasOwn(table, name)) throw error("AttributeError", `'${typeName(obj)}' object has no attribute '${name}'`);
    return table[name](obj, ...args);
  }

  // ---- safety and environment ----------------------------------------------------------------------
  function url(v) {
    if (v === null || v === undefined || v === false) return v;
    const s = str(v);
    const n = s.replace(/[\x00-\x20\x7f]+/g, "").toLowerCase();  // eslint-disable-line no-control-regex
    if (n.startsWith("data:image/") && !n.startsWith("data:image/svg")) return s;
    if (/^(javascript|vbscript|data):/.test(n)) throw error("ValueError", `unsafe URL scheme in ${repr(s.slice(0, 40))}`);
    return s;
  }
  function callable(f) {
    if (typeof f !== "function") throw error("TypeError", `'${typeName(f)}' object is not callable`);
    return f;
  }
  const sleep = (c, seconds) => new Promise((resolve, reject) => {
    setTimeout(() => (!c || c.el.isConnected ? resolve(null) : reject(new Cancelled())), Math.max(0, Number(seconds) * 1000));
  });
  async function remote(target, args) {
    try {
      return await R.call(target.service, target.method, args, { verb: target.verb, path: target.path });
    } catch (err) {
      throw err && err.response ? error("RemoteError", err.message) : err;
    }
  }

  // ---- instances --------------------------------------------------------------------------------------
  const defs = new Map();
  const instances = new Map();
  const KEEP = { t: "rw-slot", a: {}, c: [], keep: true };
  const SVG = "http://www.w3.org/2000/svg";

  function report(c, err) {
    if (err instanceof Cancelled) return;
    if (R._debug) console.error(`[rational] ${c ? c.el.getAttribute("data-rw-island") : "island"}:`, err);
    const target = c && c.el.isConnected ? c.el : document;
    target.dispatchEvent(new CustomEvent("rw:error", {
      bubbles: true,
      detail: { code: err instanceof PyError ? err.pyType : "client_error", message: String(err && err.message) },
    }));
  }

  function run(c, fn) {
    let result;
    try { result = fn(); } catch (err) { report(c, err); schedule(c); return; }
    schedule(c);
    if (result && typeof result.then === "function") {
      result.then(() => schedule(c), (err) => { report(c, err); schedule(c); });
    }
  }

  function schedule(c) {
    if (c.queued || !c.alive) return;
    c.queued = true;
    queueMicrotask(() => { if (c.queued) render(c); });
  }

  function build(v, parent, ns) {
    if (v === null || v === undefined || v === false || v === true) return;
    if (Array.isArray(v)) { for (const x of v) build(x, parent, ns); return; }
    if (typeof v === "string" || typeof v === "number") {
      const text = typeof v === "string" ? v : str(v);
      if (!text) return;
      const last = parent.lastChild;
      if (last && last.nodeType === 3) last.nodeValue += text; else parent.appendChild(document.createTextNode(text));
      return;
    }
    if (v.raw !== undefined) {
      const tpl = document.createElement("template");
      tpl.innerHTML = v.raw;
      parent.appendChild(tpl.content);
      return;
    }
    const space = v.t === "svg" ? SVG : ns;
    const el = space ? document.createElementNS(space, v.t) : document.createElement(v.t);
    for (const name of Object.keys(v.a)) {
      const value = v.a[name];
      if (value === null || value === undefined || value === false) continue;
      el.setAttribute(name, value === true ? "" : typeof value === "string" ? value : str(value));
    }
    if (v.island) el.__rwInit = v.island;
    if (v.keep) el.__rwKeep = true;
    build(v.c, el, v.t === "foreignObject" ? null : space);
    parent.appendChild(el);
  }

  // Like the server: one element is the root; anything else is wrapped in a <div>.
  function root(v) {
    const items = [];
    const flat = (x) => {
      if (x === null || x === undefined || x === true || x === false) return;
      if (Array.isArray(x)) x.forEach(flat); else items.push(x);
    };
    flat(v);
    if (items.length === 1 && typeof items[0] === "object" && items[0].t !== undefined) return items[0];
    return { t: "div", a: {}, c: items };
  }

  function render(c) {
    c.queued = false;
    if (!c.el.isConnected) { dispose(c); return; }
    c.handlers = [];
    c.ids = 0;
    c.kids = 0;
    let tree;
    try { tree = root(c.def.render(c)); } catch (err) { report(c, err); return; }
    if (c.cls) tree = { ...tree, a: { ...tree.a, class: tree.a.class ? `${tree.a.class} ${c.cls}` : c.cls } };
    const next = document.createElement("rw-island");
    build(tree, next, c.el.namespaceURI === SVG ? SVG : null);
    R._morphChildren(c.el, next);
    hydrateWithin(c.el);
  }

  function dispose(c) {
    c.alive = false;
    instances.delete(c.uid);
  }

  function ownSlots(el) {
    return Array.from(el.querySelectorAll("rw-slot")).filter((s) => s.closest("rw-island") === el);
  }

  function hydrate(el) {
    const def = defs.get(el.getAttribute("data-rw-island"));
    const init = el.__rwInit;  // set when a parent island built (or re-rendered) this element
    const fromServer = el.hasAttribute("data-rw-state");
    const c = {
      el, def, alive: true, queued: false, handlers: [], ids: 0, kids: 0,
      uid: el.getAttribute("data-rw-uid") || init.uid,
      p: init ? init.props : JSON.parse(el.getAttribute("data-rw-props") || "{}"),
      slot: init ? init.slot : ownSlots(el).length ? [KEEP] : [],
      cls: init ? init.cls : el.getAttribute("data-rw-class"),
    };
    const state = Object.assign(def.init(), fromServer ? JSON.parse(el.getAttribute("data-rw-state")) : {});
    c.s = new Proxy(state, {
      set(target, key, value) { target[key] = value; schedule(c); return true; },
      deleteProperty(target, key) { delete target[key]; schedule(c); return true; },
    });
    el.__rw = c;
    instances.set(c.uid, c);
    if (!fromServer && def.mount) run(c, () => def.mount(c));
    render(c);
    if (def.hydrated) run(c, () => def.hydrated(c));
  }

  function hydrateWithin(scope) {
    for (const el of scope.querySelectorAll("rw-island")) {
      if (!el.__rw && el.isConnected && defs.has(el.getAttribute("data-rw-island"))) hydrate(el);
    }
  }

  function prune() {
    for (const c of instances.values()) if (!c.el.isConnected) dispose(c);
  }

  // Called by runtime.js morph() for <rw-island> elements: the server (or a parent island) may change
  // props, the style class and server-rendered slot content, never the island's own DOM.
  R._islandMorph = (from, to) => {
    const props = to.getAttribute("data-rw-props");
    if (props !== null && props !== from.getAttribute("data-rw-props")) from.setAttribute("data-rw-props", props);
    const fromSlots = ownSlots(from);
    const toSlots = ownSlots(to);
    for (let i = 0; i < Math.min(fromSlots.length, toSlots.length); i++) {
      if (!to.__rwInit) R._morphChildren(fromSlots[i], toSlots[i]);
    }
    const c = from.__rw;
    if (!c) { if (to.__rwInit) from.__rwInit = to.__rwInit; return; }
    if (to.__rwInit) {
      c.p = to.__rwInit.props;
      c.slot = to.__rwInit.slot;
      c.cls = to.__rwInit.cls;
    } else {
      if (props !== null) c.p = JSON.parse(props);
      c.cls = to.getAttribute("data-rw-class");
    }
    schedule(c);
  };

  R._islandEvent = (ref, name, el, payload) => {
    const at = ref.lastIndexOf(":");
    const c = instances.get(ref.slice(0, at));
    const fn = c && c.handlers[Number(ref.slice(at + 1))];
    if (!fn) return;
    const value = name === "submit" ? payload.form : payload.value;
    run(c, () => fn(value === undefined ? null : value));
  };

  const rt = {
    error, caught, truthy, eq, cmp, contains, add, mul, div, floordiv, mod, round, str, repr, fmt,
    int, float, convert, len, iter, list, dict, unpack, range, enumerate, zip, sorted, reversed, sum,
    min: (items, opts) => extreme(-1, items, opts),
    max: (items, opts) => extreme(1, items, opts),
    abs: (x) => Math.abs(Number(x)),
    any: (xs) => iter(xs).some(truthy),
    all: (xs) => iter(xs).every(truthy),
    chr: (i) => String.fromCodePoint(i),
    ord: (s) => { const cs = Array.from(s); if (cs.length !== 1) throw error("TypeError", "ord() expected a character"); return cs[0].codePointAt(0); },
    print: (...args) => console.log(args.map(str).join(" ")),
    isinstance, get, set, del, slice, m: method, url, callable, sleep, remote,
    sqrt: (x) => { if (x < 0) throw error("ValueError", "math domain error"); return Math.sqrt(x); },
    time: () => Date.now() / 1000,
    randint: (a, b) => a + Math.floor(Math.random() * (b - a + 1)),
    choice: (seq) => { const xs = list(seq); if (!xs.length) throw error("IndexError", "Cannot choose from an empty sequence"); return xs[Math.floor(Math.random() * xs.length)]; },
    and: (a, rest) => (truthy(a) ? rest() : a),
    or: (a, rest) => (truthy(a) ? a : rest()),
    cls: (...parts) => parts.filter((p) => typeof p === "string" && p).join(" "),
    on: (c, fn) => `${c.uid}:${c.handlers.push(fn) - 1}`,
    id: (c, slug) => `${c.uid}-${slug}-${++c.ids}`,
    island: (c, key, props, slot, k, cls) => {
      const uid = k === null ? `${c.uid}.${++c.kids}` : `${c.uid}.k${k}`;
      const a = { "data-rw-island": key, "data-rw-uid": uid };
      if (k !== null) a["data-rw-key"] = k;
      return { t: "rw-island", a, c: [], island: { uid, props, slot, cls } };
    },
    navigate: (target) => { R._go(target); return null; },
    touch: (c) => { schedule(c); return null; },
    runjs: (c, ops) => { R._runOps(ops, c.el); return null; },
  };

  R.island = (key, factory) => {
    if (defs.has(key)) return;
    defs.set(key, factory(rt));
    hydrateWithin(document);
  };
  document.addEventListener("rw:updated", () => { prune(); hydrateWithin(document); });
  document.addEventListener("rw:navigated", () => { prune(); hydrateWithin(document); });
})();
