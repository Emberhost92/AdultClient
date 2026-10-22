(function (root) {
  "use strict";
  let S;
  const copy = (v) => JSON.parse(JSON.stringify(v));
  const asset = /^[a-f0-9]{64}\.(png|jpg|gif|webp|woff2?|ttf|otf)$/;
  const image = (v) =>
    typeof v === "string" && asset.test(v) && /\.(png|jpg|gif|webp)$/.test(v);
  const font = (v) =>
    typeof v === "string" && asset.test(v) && /\.(woff2?|ttf|otf)$/.test(v);
  const get = (v, path) => path.split(".").reduce((n, k) => n?.[k], v);
  function set(v, path, value) {
    const keys = path.split(".");
    let n = v;
    for (const k of keys.slice(0, -1)) n = n[k] ||= {};
    n[keys.at(-1)] = value;
  }
  function safeURL(v) {
    try {
      const u = new URL(v);
      return ["http:", "https:"].includes(u.protocol) &&
        !u.username &&
        !u.password
        ? u.href
        : "";
    } catch {
      return "";
    }
  }
  function value(v, r) {
    if (v == null) return r.default;
    switch (r.type) {
      case "boolean":
        return typeof v === "boolean" ? v : r.default;
      case "number":
        return Number.isFinite(Number(v))
          ? Math.round(Math.max(r.min, Math.min(r.max, Number(v))) * 100) / 100
          : r.default;
      case "color":
        return /^#[a-f0-9]{6}$/i.test(v) ? v.toLowerCase() : r.default;
      case "text":
        return typeof v === "string" ? v.trim().slice(0, r.max) : r.default;
      case "url":
        return typeof v === "string" ? safeURL(v).slice(0, 2000) : "";
      case "image":
        return image(v) ? v : "";
      case "enum":
        return r.values.includes(String(v)) ? String(v) : r.default;
      case "font":
        return S.fonts.includes(v) ||
          (typeof v === "string" && v.startsWith("asset:") && font(v.slice(6)))
          ? v
          : r.default;
      default:
        return r.default;
    }
  }
  function background(raw = {}) {
    return Object.fromEntries(
      Object.entries(S.background).map(([k, r]) => [k, value(raw?.[k], r)]),
    );
  }
  function appearance(raw = {}) {
    const out = {};
    for (const [k, d] of Object.entries(S.appearance)) {
      const v = raw[k];
      if (Array.isArray(d))
        out[k] = Array.isArray(v)
          ? v.filter((id) => S.menus.includes(id) && id !== "settings")
          : [];
      else if (d && typeof d === "object")
        out[k] = Object.fromEntries(
          Object.entries(v || {})
            .filter(
              ([id, t]) =>
                S.menus.includes(id) &&
                id !== "settings" &&
                typeof t === "string",
            )
            .map(([id, t]) => [id, t.trim().slice(0, 40)]),
        );
      else if (typeof d === "boolean") out[k] = typeof v === "boolean" ? v : d;
      else if (typeof d === "number")
        out[k] = Number.isFinite(Number(v))
          ? Math.max(0, Math.min(1000, Number(v)))
          : d;
      else if (d.startsWith("#")) out[k] = /^#[a-f0-9]{6}$/i.test(v) ? v : d;
      else if (k === "photo") out[k] = safeURL(v) || "";
      else out[k] = typeof v === "string" && v.length <= 80 ? v : d;
    }
    return out;
  }
  function normalize(raw = {}, profiles = true) {
    if (raw?.version != null && raw.version !== 1)
      throw Error(
        "Diese Designversion wird noch nicht unterstützt. Der bisherige Stand bleibt erhalten.",
      );
    const out = { version: 1 };
    for (const [path, r] of Object.entries(S.fields))
      set(out, path, value(get(raw, path), r));
    // Adopt the transparent official mark for profiles using our former bundled JPG.
    // User-uploaded logos and their chosen backgrounds remain configurable.
    if (out.brand.logo === 'c2cfefa1e3e32392f84cc37a80a29f68578996779285d13a8a067d4864090279.jpg') {
      out.brand.logo = '';
      out.brand.background = 'transparent';
    }
    if (["AdultHideout", "Adult Hideout"].includes(out.brand.name))
      out.brand.name = "Adult Client";
    if (["AdultHideout", "Adult Hideout"].includes(out.brand.title))
      out.brand.title = "Adult Client";
    out.backgrounds = { all: background(raw?.backgrounds?.all), pages: {} };
    for (const [k, v] of Object.entries(raw?.backgrounds?.pages || {}))
      if ([...S.menus, "browse", "watch"].includes(k))
        out.backgrounds.pages[k] = background(v);
    out.fonts = (Array.isArray(raw.fonts) ? raw.fonts : [])
      .filter((f) => font(f?.file) && typeof f.name === "string")
      .slice(0, 12)
      .map((f) => ({ file: f.file, name: f.name.slice(0, 80) }));
    out.siteLogos = Object.fromEntries(
      Object.entries(raw.siteLogos || {})
        .filter(([k, v]) => /^[a-zA-Z0-9_-]{1,100}$/.test(k) && image(v))
        .slice(0, 600),
    );
    out.menuIcons = {};
    for (const [k, v] of Object.entries(raw.menuIcons || {}))
      if (S.menus.includes(k))
        out.menuIcons[k] = {
          symbol: typeof v?.symbol === "string" ? v.symbol.slice(0, 8) : "",
          image: image(v?.image) ? v.image : "",
        };
    out.menuOrder = [
      ...new Set(
        (Array.isArray(raw.menuOrder) ? raw.menuOrder : []).filter(
          (k) => S.menus.includes(k) && k !== "settings",
        ),
      ),
    ];
    out.profiles = profiles
      ? (Array.isArray(raw.profiles) ? raw.profiles : [])
          .slice(0, 24)
          .filter((p) => typeof p.name === "string" && p.name.trim())
          .map((p, i) => ({
            id: typeof p.id === "string" ? p.id.slice(0, 100) : "profile-" + i,
            name: p.name.trim().slice(0, 80),
            design: normalize(p.design || {}, false),
            appearance: appearance(p.appearance || {}),
          }))
      : [];
    return out;
  }
  function refs(v, out = new Set()) {
    if (typeof v === "string" && asset.test(v)) out.add(v);
    else if (Array.isArray(v)) for (const item of v) refs(item, out);
    else if (v && typeof v === "object")
      for (const item of Object.values(v)) refs(item, out);
    return out;
  }
  function contrast(a, b) {
    const lum = (c) => {
      const p = c
        .match(/[a-f0-9]{2}/gi)
        .map((x) => parseInt(x, 16) / 255)
        .map((x) => (x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
      return p[0] * 0.2126 + p[1] * 0.7152 + p[2] * 0.0722;
    };
    const x = lum(a),
      y = lum(b);
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  }
  const api = {
    equal(a, b) {
      const canonical = (v) =>
        Array.isArray(v)
          ? v.map(canonical)
          : v && typeof v === "object"
            ? Object.fromEntries(
                Object.keys(v)
                  .sort()
                  .map((k) => [k, canonical(v[k])]),
              )
            : v;
      return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));
    },
    configure(schema) {
      S = schema;
    },
    get schema() {
      return S;
    },
    copy,
    get,
    set,
    value,
    normalize,
    background,
    appearance,
    refs,
    contrast,
    image,
    font,
    safeURL,
  };
  root.SettingsDomain = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis);
