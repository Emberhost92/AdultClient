/* Video workspaces: persistent intent, never expiring resolved media handles. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.MultiTubeDomain = api;
})(globalThis, function () {
  "use strict";
  const LIVE = new Set([
    "chaturbate",
    "stripchat",
    "bongacams",
    "camsoda",
    "cam4",
    "xlovecam",
  ]);
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const clamp = (v, a, b, f = a) =>
    Number.isFinite(Number(v)) ? Math.max(a, Math.min(b, Number(v))) : f;
  const id = () =>
    globalThis.crypto?.randomUUID?.() ||
    "mt-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
  const text = (v, n = 500) =>
    String(v ?? "")
      .trim()
      .slice(0, n);
  const retain = (value, fields) => {
    for (const key of Object.keys(value))
      if (!fields.includes(key)) delete value[key];
    return value;
  };
  function safeURL(v) {
    try {
      const u = new URL(String(v));
      return ["http:", "https:"].includes(u.protocol) &&
        !u.username &&
        !u.password
        ? u.href
        : "";
    } catch {
      return "";
    }
  }
  function transientURL(value) {
    try {
      const u = new URL(value, "https://local.invalid");
      return [...u.searchParams.keys()].some((key) =>
        /^(token|sig|signature|expires|exp|auth|authorization|policy|x-amz-signature|x-amz-credential|hdnea|hdnts|key-pair-id)$/i.test(
          key,
        ),
      );
    } catch {
      return true;
    }
  }
  function publicImage(value) {
    if (typeof value !== "string" || transientURL(value)) return "";
    if (value.startsWith("/api/image?")) {
      const target = new URL(value, "https://local.invalid").searchParams.get(
        "url",
      );
      return safeURL(target) && !transientURL(target) ? value : "";
    }
    return safeURL(value);
  }
  function queryOf(input) {
    let raw =
      typeof input === "string" ? input : input?.query || input?.url || "";
    if (raw.startsWith("plugin://")) raw = raw.split("?").slice(1).join("?");
    const p = new URLSearchParams(raw.replace(/^\?/, "")),
      site = p.get("website") || "";
    if (
      p.get("mode") !== "4" ||
      !/^[a-zA-Z0-9_]+$/.test(site) ||
      LIVE.has(site)
    )
      throw Error(
        "Bitte ein festes Tube-Video wählen. Live-Cams gehören in Multicam.",
      );
    const url = safeURL((p.get("url") || "").split("|")[0]);
    if (!url) throw Error("Das Video hat keine gültige Anbieterseite.");
    const u = new URL(url);
    if (transientURL(u.href))
      throw Error(
        "Bitte die reguläre Videoseite statt einer kurzlebigen Medienadresse verwenden.",
      );
    return new URLSearchParams({ mode: "4", website: site, url }).toString();
  }
  function video(input) {
    const query = queryOf(input),
      p = new URLSearchParams(query),
      key = p.get("website") + ":" + p.get("url");
    return {
      key,
      query,
      site: p.get("website"),
      url: p.get("url"),
      title: text(input.title || input.name || p.get("url"), 300),
      thumb: publicImage(input.thumb) || "",
      facts: Object.fromEntries(["stars","tags","categories"].map(key => [key, (Array.isArray(input.facts?.[key] || input[key]) ? (input.facts?.[key] || input[key]) : []).slice(0,40).map(v => ({name:text(typeof v === "object" ? v?.name || v?.title : v,100)})).filter(v=>v.name)])),
      uploader: text(input.uploader, 160),
      plot: text(input.plot, 6000),
      duration: Math.max(0, seconds(input.duration)),
      preview: (Array.isArray(input.preview) ? input.preview : [])
        .map(publicImage)
        .filter(Boolean)
        .slice(0, 24),
    };
  }
  function workspace(name = "Mein Multitube", key = "default") {
    return {
      id: key,
      name: text(name, 80) || "Arbeitsbereich",
      description: "",
      archived: false,
      capacity: 4,
      layout: "grid",
      fit: "contain",
      sidebar: true,
      details: false,
      clean: false,
      focus: "",
      selected: "",
      slots: Array(20).fill(null),
      queue: [],
      entries: {},
      scenes: [],
      settings: {
        audio: "focus",
        solo: "",
        master: 1,
        muteAll: false,
        quality: 0,
        activeLimit: 20,
        performance: "manual",
        end: "stop",
        background: "pause",
        linked: false,
        offsets: {},
      },
    };
  }
  const initial = () => ({
    schema: 1,
    revision: 0,
    active: "default",
    videos: {},
    personal: {},
    workspaces: [workspace()],
    migration: 0,
  });
  const get = (state, key = state.active) =>
    state.workspaces.find((w) => w.id === key && !w.archived) ||
    state.workspaces.find((w) => w.id === "default");
  function instance(media) {
    return {
      id: id(),
      media,
      time: 0,
      duration: 0,
      paused: false,
      ended: false,
      pinned: false,
      volume: 1,
      muted: false,
      rate: 1,
      quality: 0,
      loop: { a: null, b: null, enabled: false },
      image: {
        zoom: 100,
        x: 0,
        y: 0,
        rotate: 0,
        flip: false,
        brightness: 100,
        contrast: 100,
        saturation: 100,
      },
      updated: 0,
    };
  }
  function add(state, key, inputs, options = {}) {
    const w = get(state, key),
      made = [];
    for (const input of inputs) {
      const v = video(input);
      state.videos[v.key] = { ...state.videos[v.key], ...v };
      const existing = Object.values(w.entries).find((e) => e.media === v.key);
      if (existing && !options.duplicate) {
        if (options.target != null) {
          place(w, existing.id, options.target);
        } else if (!w.slots.includes(existing.id)) {
          const free = w.slots.findIndex((v, i) => !v && i < w.capacity);
          if (free >= 0 && !options.queue) place(w, existing.id, free);
          else if (!w.queue.includes(existing.id)) w.queue.push(existing.id);
        }
        w.selected = existing.id;
        made.push(existing.id);
        continue;
      }
      if (Object.keys(w.entries).length >= 1000)
        throw Error("Dieser Arbeitsbereich enthält bereits 1000 Videos.");
      const e = instance(v.key);
      w.entries[e.id] = e;
      made.push(e.id);
      const slot =
        options.target != null
          ? clamp(options.target, 0, 19)
          : options.queue
            ? -1
            : w.slots.findIndex((value, i) => !value && i < w.capacity);
      if (slot >= 0) {
        if (w.slots[slot]) w.queue.push(w.slots[slot]);
        w.slots[slot] = e.id;
      } else w.queue.push(e.id);
      w.selected = e.id;
      if (!w.focus) w.focus = e.id;
    }
    return made;
  }
  function place(w, entry, slot) {
    slot = clamp(slot, 0, 19);
    if (!w.entries[entry])
      throw Error("Dieses Video ist nicht mehr vorhanden.");
    const old = w.slots.indexOf(entry),
      previous = w.slots[slot];
    if (old === slot) return;
    if (old >= 0) w.slots[old] = previous;
    else if (previous) w.queue.push(previous);
    w.slots[slot] = entry;
    w.queue = w.queue.filter((x) => x !== entry);
    w.selected = entry;
  }
  function remove(w, entry, toQueue = false) {
    const slot = w.slots.indexOf(entry);
    if (slot >= 0) w.slots[slot] = null;
    w.queue = w.queue.filter((x) => x !== entry);
    if (toQueue && w.entries[entry]) w.queue.push(entry);
    else delete w.entries[entry];
    if (w.focus === entry) w.focus = w.slots.find(Boolean) || "";
    if (w.selected === entry) w.selected = w.focus;
  }
  function advance(w, slot, expected, force = false) {
    if (
      w.slots[slot] !== expected ||
      !w.entries[expected] ||
      (w.entries[expected].pinned && !force)
    )
      return null;
    const next = w.queue.shift();
    if (!next) return null;
    w.entries[expected].paused = true;
    w.entries[expected].ended = true;
    w.slots[slot] = next;
    w.entries[next].ended = false;
    w.entries[next].paused = false;
    w.entries[next].time = 0;
    if (w.focus === expected) w.focus = next;
    if (w.selected === expected) w.selected = next;
    return next;
  }
  function scene(w, name, positions = true) {
    return {
      id: id(),
      name: text(name, 80) || "Sitzung",
      created: Date.now(),
      capacity: w.capacity,
      layout: w.layout,
      fit: w.fit,
      focus: w.focus,
      slots: w.slots.slice(),
      queue: w.queue.slice(),
      settings: clone(w.settings),
      positions: positions
        ? Object.fromEntries(
            Object.values(w.entries).map((e) => [
              e.id,
              { time: e.time, paused: true, rate: e.rate },
            ]),
          )
        : {},
    };
  }
  function applyScene(w, s) {
    w.capacity = s.capacity;
    w.layout = s.layout;
    w.fit = s.fit;
    w.focus = w.entries[s.focus] ? s.focus : "";
    w.slots = s.slots.map((k) => (w.entries[k] ? k : null));
    const occupied = new Set(w.slots.filter(Boolean));
    w.queue = [
      ...new Set(
        [...s.queue, ...w.queue, ...Object.keys(w.entries)].filter(
          (k) => w.entries[k] && !occupied.has(k),
        ),
      ),
    ];
    w.settings = { ...w.settings, ...clone(s.settings) };
    for (const [k, p] of Object.entries(s.positions || {}))
      if (w.entries[k]) Object.assign(w.entries[k], p, { ended: false });
  }
  function seconds(v) {
    if (typeof v === "number") return Number.isFinite(v) ? v : 0;
    const a = String(v || "")
      .split(":")
      .map(Number);
    return a.every(Number.isFinite) ? a.reduce((n, x) => n * 60 + x, 0) : 0;
  }
  function clock(v) {
    v = Math.max(0, Math.floor(Number(v) || 0));
    const h = Math.floor(v / 3600);
    return (
      (h ? h + ":" : "") +
      String(Math.floor(v / 60) % 60).padStart(h ? 2 : 1, "0") +
      ":" +
      String(v % 60).padStart(2, "0")
    );
  }
  function qualityIndex(levels, cap) {
    let rows = levels
      .map((v, i) => ({ i, h: Number(v.height) || 0 }))
      .filter((v) => v.h > 0)
      .sort((a, b) => a.h - b.h);
    if (!rows.length) return -1;
    if (!cap) return -1;
    return (rows.filter((v) => v.h <= cap).at(-1) || rows[0]).i;
  }
  function layout(count, width, height, aspect = 16 / 9) {
    let best = { columns: 1, rows: count, score: -Infinity };
    for (let c = 1; c <= count; c++) {
      let r = Math.ceil(count / c),
        x = Math.max(1, (width - (c - 1) * 8) / c),
        y = Math.max(1, (height - (r - 1) * 8) / r - 66);
      let area = Math.min(x, y * aspect) * Math.min(y, x / aspect) * count;
      let score = area / Math.max(1, width * height) - (r * c - count) * 0.015;
      if (score > best.score) best = { columns: c, rows: r, score };
    }
    return best;
  }
  function validate(value) {
    if (!value || value.schema !== 1)
      throw Error(
        "Diese Multitube-Datenversion wird nicht unterstützt. Vorhandene Daten bleiben erhalten.",
      );
    if (
      !Array.isArray(value.workspaces) ||
      !value.workspaces.length ||
      value.workspaces.length > 60 ||
      !value.workspaces.some((w) => w.id === "default" && !w.archived)
    )
      throw Error("Ungültige Arbeitsbereiche.");
    if (
      !value.videos ||
      !value.personal ||
      typeof value.videos !== "object" ||
      Array.isArray(value.videos) ||
      Object.keys(value.videos).length > 10000
    )
      throw Error("Ungültiger Videobestand.");
    if (Array.isArray(value.personal) || typeof value.personal !== "object")
      throw Error("Ungültige persönliche Videodaten.");
    retain(value, [
      "schema",
      "revision",
      "active",
      "videos",
      "personal",
      "workspaces",
      "migration",
      "candidates",
    ]);
    value.revision = Math.floor(
      clamp(value.revision, 0, Number.MAX_SAFE_INTEGER),
    );
    value.candidates = Array.isArray(value.candidates)
      ? value.candidates
          .filter((k) => typeof k === "string" && value.videos[k])
          .slice(0, 10000)
      : [];
    const keys = new Set();
    for (const [key, v] of Object.entries(value.videos)) {
      const clean = video(v);
      if (clean.key !== key) throw Error("Eine Videoidentität ist ungültig.");
      value.videos[key] = clean;
    }
    for (const w of value.workspaces) {
      if (
        !w.id ||
        keys.has(w.id) ||
        typeof w.name !== "string" ||
        !w.name.trim() ||
        w.name.length > 80 ||
        !Number.isInteger(w.capacity) ||
        w.capacity < 1 ||
        w.capacity > 20 ||
        !["grid", "focus", "compare"].includes(w.layout) ||
        !["contain", "cover"].includes(w.fit) ||
        !Array.isArray(w.slots) ||
        w.slots.length !== 20 ||
        !Array.isArray(w.queue) ||
        !w.entries ||
        !Array.isArray(w.scenes) ||
        w.scenes.length > 24
      )
        throw Error("Ein Arbeitsbereich ist beschädigt.");
      keys.add(w.id);
      if (!/^[a-zA-Z0-9_-]{1,100}$/.test(w.id) || Array.isArray(w.entries))
        throw Error("Ungültiger Arbeitsbereich.");
      retain(w, [
        "id",
        "name",
        "description",
        "archived",
        "capacity",
        "layout",
        "fit",
        "sidebar",
        "details",
        "clean",
        "focus",
        "selected",
        "slots",
        "queue",
        "entries",
        "scenes",
        "settings",
        "page",
        "filter",
      ]);
      w.description = text(w.description, 4000);
      w.page = Math.floor(clamp(w.page, 0, 19));
      w.filter = {
        search: text(w.filter?.search, 300),
        source: text(w.filter?.source, 160) || "all",
        sort: ["title", "site", "duration", "recent"].includes(w.filter?.sort)
          ? w.filter.sort
          : "title",
      };
      const used = [...w.slots.filter(Boolean), ...w.queue];
      if (
        new Set(used).size !== used.length ||
        Object.keys(w.entries).length > 1000 ||
        used.some((k) => !w.entries[k])
      )
        throw Error("Ungültige Platz- oder Warteschlangenzuordnung.");
      for (const [key, e] of Object.entries(w.entries)) {
        if (e.id !== key || !value.videos[e.media])
          throw Error("Ein Videoverweis fehlt.");
        if (!/^[a-zA-Z0-9_-]{1,100}$/.test(key))
          throw Error("Ungültige Wiedergabekennung.");
        retain(e, [
          "id",
          "media",
          "time",
          "duration",
          "paused",
          "ended",
          "pinned",
          "volume",
          "muted",
          "rate",
          "quality",
          "loop",
          "image",
          "updated",
        ]);
        e.muted = !!e.muted;
        e.updated = clamp(e.updated, 0, Number.MAX_SAFE_INTEGER);
        e.time = clamp(e.time, 0, 604800);
        e.duration = clamp(e.duration, 0, 604800);
        e.volume = clamp(e.volume, 0, 1, 1);
        e.rate = clamp(e.rate, 0.25, 4, 1);
        e.quality = clamp(e.quality, 0, 4320);
        e.paused = !!e.paused;
        e.ended = !!e.ended;
        e.pinned = !!e.pinned;
        e.loop = {
          a: e.loop?.a == null ? null : clamp(e.loop.a, 0, 604800),
          b: e.loop?.b == null ? null : clamp(e.loop.b, 0, 604800),
          enabled: !!e.loop?.enabled,
        };
        if (
          e.loop.enabled &&
          !(
            Number.isFinite(e.loop.a) &&
            Number.isFinite(e.loop.b) &&
            e.loop.b > e.loop.a
          )
        )
          throw Error("Das Schleifenende muss hinter dem Anfang liegen.");
        const im = e.image || {};
        e.image = {
          zoom: clamp(im.zoom, 50, 1000, 100),
          x: clamp(im.x, -5000, 5000),
          y: clamp(im.y, -5000, 5000),
          rotate: [0, 90, 180, 270].includes(im.rotate) ? im.rotate : 0,
          flip: !!im.flip,
          brightness: clamp(im.brightness, 25, 250, 100),
          contrast: clamp(im.contrast, 25, 250, 100),
          saturation: clamp(im.saturation, 0, 300, 100),
        };
      }
      const s = w.settings || {};
      if (
        !["focus", "solo", "manual"].includes(s.audio) ||
        !["stop", "repeat", "next"].includes(s.end) ||
        !["pause", "audio", "continue"].includes(s.background) ||
        !["manual", "economy", "balanced"].includes(s.performance)
      )
        throw Error("Ungültige Wiedergabeeinstellungen.");
      retain(s, [
        "audio",
        "solo",
        "master",
        "muteAll",
        "quality",
        "activeLimit",
        "performance",
        "end",
        "background",
        "linked",
        "offsets",
        "fitAll",
      ]);
      s.master = clamp(s.master, 0, 1, 1);
      s.quality = clamp(s.quality, 0, 4320);
      s.activeLimit = clamp(s.activeLimit, 1, 20, 20);
      s.offsets = s.offsets || {};
      s.offsets = Object.fromEntries(
        Object.entries(s.offsets)
          .filter(([k, v]) => w.entries[k] && Number.isFinite(v))
          .map(([k, v]) => [k, clamp(v, -604800, 604800)]),
      );
      for (const sc of w.scenes) {
        if (
          !sc ||
          !Array.isArray(sc.slots) ||
          sc.slots.length !== 20 ||
          !Array.isArray(sc.queue) ||
          !sc.settings ||
          !["grid", "focus", "compare"].includes(sc.layout) ||
          !["contain", "cover"].includes(sc.fit) ||
          !Number.isInteger(sc.capacity) ||
          sc.capacity < 1 ||
          sc.capacity > 20
        )
          throw Error("Ungültige gespeicherte Sitzung.");
        retain(sc, [
          "id",
          "name",
          "created",
          "capacity",
          "layout",
          "fit",
          "focus",
          "slots",
          "queue",
          "settings",
          "positions",
        ]);
        sc.name = text(sc.name, 80) || "Sitzung";
        sc.settings = { ...clone(s), ...retain(sc.settings, Object.keys(s)) };
        if (
          !["focus", "solo", "manual"].includes(sc.settings.audio) ||
          !["stop", "repeat", "next"].includes(sc.settings.end) ||
          !["pause", "audio", "continue"].includes(sc.settings.background) ||
          !["manual", "economy", "balanced"].includes(sc.settings.performance)
        )
          throw Error("Ungültige Sitzungseinstellungen.");
        sc.positions = Object.fromEntries(
          Object.entries(sc.positions || {})
            .filter(([k, p]) => w.entries[k] && p && typeof p === "object")
            .map(([k, p]) => [
              k,
              {
                time: clamp(p.time, 0, 604800),
                paused: true,
                rate: clamp(p.rate, 0.25, 4, 1),
              },
            ]),
        );
        sc.settings.offsets = Object.fromEntries(
          Object.entries(sc.settings.offsets || {}).filter(
            ([k, v]) => w.entries[k] && Number.isFinite(v),
          ),
        );
      }
    }
    for (const p of Object.values(value.personal)) {
      if (!p || typeof p !== "object" || Array.isArray(p))
        throw Error("Ungültige persönliche Videodaten.");
      retain(p, ["notes", "tags", "markers", "rating", "favorite", "revision"]);
      p.revision = Math.floor(clamp(p.revision, 0, Number.MAX_SAFE_INTEGER));
      p.notes = String(p.notes ?? "");
      if (p.notes.length > 1000000)
        throw Error(
          "Die Notiz ist größer als eine Million Zeichen. Der Entwurf bleibt erhalten.",
        );
      p.tags = Array.isArray(p.tags)
        ? p.tags.map((t) => text(t, 50)).slice(0, 100)
        : [];
      p.markers = Array.isArray(p.markers)
        ? p.markers.slice(0, 200).map((m) => ({
            id: text(m.id, 80) || id(),
            time: clamp(m.time, 0, 604800),
            label: text(m.label, 160) || "Zeitmarke",
          }))
        : [];
      p.rating = clamp(p.rating, 0, 5);
      p.favorite = !!p.favorite;
    }
    return value;
  }
  function migrate(rows, capacity = 4) {
    const s = initial();
    s.workspaces[0].capacity = clamp(capacity, 1, 20, 4);
    for (const row of Array.isArray(rows) ? rows : []) {
      try {
        add(s, "default", [row]);
      } catch {
        /* Unsupported legacy rows remain in the untouched legacy key. */
      }
    }
    s.migration = 1;
    return validate(s);
  }
  function exportState(state) {
    return {
      kind: "ah-multitube",
      schema: 1,
      created: Date.now(),
      state: clone(validate(clone(state))),
    };
  }
  function importState(payload) {
    if (payload?.kind !== "ah-multitube")
      throw Error("Keine Multitube-Sicherung.");
    return validate(clone(payload.state));
  }
  return {
    LIVE,
    clone,
    clamp,
    id,
    text,
    safeURL,
    queryOf,
    video,
    workspace,
    initial,
    get,
    instance,
    add,
    place,
    remove,
    advance,
    scene,
    applyScene,
    seconds,
    clock,
    qualityIndex,
    layout,
    validate,
    migrate,
    exportState,
    importState,
  };
});
