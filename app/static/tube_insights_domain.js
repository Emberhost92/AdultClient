(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.TubeInsights = api;
})(globalThis, function () {
  "use strict";
  const union = (rows) => {
    const out = [];
    for (const [a, b] of rows
      .filter(
        (r) =>
          Array.isArray(r) &&
          Number.isFinite(r[0]) &&
          Number.isFinite(r[1]) &&
          r[1] > r[0],
      )
      .slice()
      .sort((a, b) => a[0] - b[0])) {
      if (out.length && a <= out.at(-1)[1] + 0.05)
        out.at(-1)[1] = Math.max(b, out.at(-1)[1]);
      else out.push([a, b]);
    }
    return out;
  };
  const seconds = (rows) => union(rows).reduce((n, [a, b]) => n + b - a, 0);
  const median = (values) => {
    const rows = values
      .filter(Number.isFinite)
      .slice()
      .sort((a, b) => a - b);
    return rows.length
      ? (rows[Math.floor(rows.length / 2)] +
          rows[Math.ceil(rows.length / 2) - 1]) /
          2
      : 0;
  };
  const names = (raw) => {
    const map = new Map();
    for (const v of Array.isArray(raw) ? raw : []) {
      const name = String(
        typeof v === "object" ? v?.name || v?.title || "" : v || "",
      ).trim();
      if (name && !map.has(name.toLocaleLowerCase("de")))
        map.set(name.toLocaleLowerCase("de"), name);
    }
    return [...map.values()];
  };
  function age(profile, now) {
    const raw = profile?.birthDate || "",
      match = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/),
      de = raw.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
    let y, m, d;
    if (match) [, y, m, d] = match.map(Number);
    else if (de) [, d, m, y] = de.map(Number);
    else if (Number(profile?.birthYear)) {
      const value = now.getFullYear() - Number(profile.birthYear);
      return value >= 18 && value < 100 ? { value, approximate: true } : null;
    } else return null;
    const valid = new Date(y, m - 1, d);
    if (
      valid.getFullYear() !== y ||
      valid.getMonth() !== m - 1 ||
      valid.getDate() !== d
    )
      return null;
    const value =
      now.getFullYear() -
      y -
      (now.getMonth() + 1 < m || (now.getMonth() + 1 === m && now.getDate() < d)
        ? 1
        : 0);
    return value >= 18 && value < 100 ? { value, approximate: false } : null;
  }
  function analyze(base, payload = {}, filter = {}, now = new Date()) {
    const metadata = new Map((payload.videos || []).map((v) => [v.key, v])),
      profiles = payload.models || {};
    const profileOf = (name) =>
      Object.hasOwn(profiles, String(name).toLocaleLowerCase("de"))
        ? profiles[String(name).toLocaleLowerCase("de")]
        : null;
    const from = base.start ? +base.start / 1000 : 0,
      to = +now / 1000;
    const clip = (rows) =>
      union((rows || []).map(([a, b]) => [Math.max(a, from), Math.min(b, to)]));
    const records = new Map(),
      sessions = [];
    function record(key, fallback = {}) {
      if (!records.has(key))
        records.set(key, {
          ...fallback,
          ...metadata.get(key),
          key,
          calls: 0,
          focus: 0,
          visible: 0,
          playing: 0,
          coverage: [],
          coverageMeasured: false,
          durations: [],
          sessionCount: 0,
          focusRanges: [],
          models: names(fallback.models),
          categories: names(fallback.categories),
          tags: names(fallback.tags),
          studio: "",
          ...metadata.get(key),
        });
      return records.get(key);
    }
    for (const event of base.plays) {
      const r = record(event.key, event);
      r.calls++;
      r.categories = names([...r.categories, ...names(event.categories)]);
      r.tags = names([...r.tags, ...names(event.tags)]);
      r.models = names([
        ...r.models,
        ...names(event.models),
        ...(metadata.get(event.key)?.models || []),
      ]);
      if (
        !(metadata.get(event.key)?.models || []).length &&
        event.performer &&
        profileOf(event.performer)
      )
        r.models = names([...r.models, event.performer]);
    }
    for (const s of payload.sessions || []) {
      const meta = metadata.get(s.key);
      if (
        !meta ||
        (filter.site && meta.site !== filter.site) ||
        (filter.source && s.source !== filter.source)
      )
        continue;
      const playing = clip(s.playing),
        visible = clip(s.visible),
        focused = clip(s.focused);
      if (!seconds(playing)) continue;
      const row = {
        ...s,
        video: meta,
        playing,
        visible,
        focused,
        playSeconds: seconds(playing),
        visibleSeconds: seconds(visible),
        focusSeconds: seconds(focused),
      };
      sessions.push(row);
      const r = record(s.key, meta);
      r.playing += row.playSeconds;
      r.visible += row.visibleSeconds;
      r.focusRanges.push(...focused);
      r.sessionCount++;
      if (!base.start || s.started >= from) {
        r.coverage.push(...(s.coverage || []));
        if (s.coverage?.length) r.coverageMeasured = true;
      }
      if (s.duration > 0) r.durations.push(s.duration);
    }
    const groups = {
      models: new Map(),
      categories: new Map(),
      tags: new Map(),
      studios: new Map(),
      hair: new Map(),
      eyes: new Map(),
      build: new Map(),
      height: new Map(),
      age: new Map(),
      cup: new Map(),
      length: new Map(),
      years: new Map(),
    };
    const coverage = {
      models: 0,
      categories: 0,
      tags: 0,
      appearance: 0,
      age: 0,
    };
    const rank = (map) =>
      [...map.values()]
        .map((r) => ({ ...r, unique: r.videos.size, videos: [...r.videos] }))
        .sort(
          (a, b) =>
            (filter.weight === "focus"
              ? b.focus - a.focus
              : b.calls - a.calls) ||
            b.unique - a.unique ||
            a.label.localeCompare(b.label, "de"),
        );
    const add = (map, label, r, extra = {}) => {
      if (!label) return;
      const key = String(label).trim().toLocaleLowerCase("de");
      if (!map.has(key))
        map.set(key, {
          label: String(label),
          calls: 0,
          focus: 0,
          videos: new Set(),
          ...extra,
        });
      const row = map.get(key);
      if (!row.videos.has(r.key)) {
        row.calls += r.calls;
        row.focus += r.focus;
        row.videos.add(r.key);
      }
    };
    for (const r of records.values()) {
      r.focus = seconds(r.focusRanges);
      r.models = names(r.models);
      r.categories = names(r.categories);
      r.tags = names(r.tags);
      r.duration = Math.max(0, ...r.durations, Number(r.duration) || 0);
      r.covered = Math.min(r.duration || Infinity, seconds(r.coverage));
      r.percent =
        r.duration && r.coverageMeasured
          ? Math.min(100, (r.covered / r.duration) * 100)
          : null;
      for (const key of ["models", "categories", "tags"]) {
        if (r[key].length) coverage[key] += r.calls;
      }
      for (const model of r.models) {
        const p = profileOf(model),
          person = p?.name || model;
        add(groups.models, person, r, { profile: p || null });
        if (!p) continue;
        let known = false;
        for (const [field, raw] of [
          ["hair", p.hair],
          ["eyes", p.eyes],
          ["build", p.build],
          ["cup", p.cup],
        ])
          if (raw) {
            add(groups[field], raw, r);
            known = true;
          }
        const h = Number(p.height_cm);
        if (h >= 120 && h <= 220) {
          add(
            groups.height,
            h < 160
              ? "Unter 160 cm"
              : h < 170
                ? "160–169 cm"
                : h < 180
                  ? "170–179 cm"
                  : "Ab 180 cm",
            r,
          );
          known = true;
        }
        const a = age(p, now);
        if (a) {
          const band =
            a.value < 25
              ? "18–24"
              : a.value < 35
                ? "25–34"
                : a.value < 45
                  ? "35–44"
                  : a.value < 55
                    ? "45–54"
                    : "55+";
          add(groups.age, band + " Jahre", r);
        }
        if (known) r.hasAppearance = true;
        if (a) r.hasAge = true;
      }
      if (r.hasAppearance) coverage.appearance += r.calls;
      if (r.hasAge) coverage.age += r.calls;
      for (const c of r.categories) add(groups.categories, c, r);
      for (const t of r.tags) add(groups.tags, t, r);
      add(groups.studios, r.studio, r);
      if (r.duration > 0) {
        const min = r.duration / 60;
        add(
          groups.length,
          min < 5
            ? "Unter 5 Min."
            : min < 15
              ? "5–14 Min."
              : min < 30
                ? "15–29 Min."
                : min < 60
                  ? "30–59 Min."
                  : "Ab 60 Min.",
          r,
        );
      }
      if (r.filmYear >= 1900 && r.filmYear <= now.getFullYear())
        add(groups.years, String(r.filmYear), r);
    }
    const focused = union(sessions.flatMap((s) => s.focused)),
      videos = [...records.values()];
    const confirmed = videos.filter((v) => v.duration > 0 && v.covered > 0);
    return {
      groups: Object.fromEntries(
        Object.entries(groups).map(([k, v]) => [k, rank(v)]),
      ),
      coverage,
      knownCalls: base.plays.length,
      videos,
      sessions,
      focus: seconds(focused),
      visible: seconds(sessions.flatMap((s) => s.visible)),
      playerTime: sessions.reduce((n, s) => n + s.playSeconds, 0),
      playerFocus: sessions.reduce((n, s) => n + s.focusSeconds, 0),
      medianPhase: median(focused.map(([a, b]) => b - a)),
      medianSession: median(
        sessions.map((s) => s.focusSeconds).filter((v) => v > 0),
      ),
      measuredVideos: videos.filter((v) => v.playing > 0).length,
      completion: confirmed.filter((v) => v.percent >= 90).length,
      completionKnown: confirmed.length,
      seeks: sessions.reduce((n, s) => n + (s.seeks || 0), 0),
      pauses: sessions.reduce((n, s) => n + (s.pauses || 0), 0),
      stalls: sessions.reduce((n, s) => n + (s.stalls || 0), 0),
      early: sessions.filter(
        (s) =>
          s.finished &&
          s.duration >= 120 &&
          s.focusSeconds > 0 &&
          s.focusSeconds < 30,
      ).length,
      recording: payload.recording !== false,
    };
  }
  return { analyze, union, seconds, median, age, names };
});
