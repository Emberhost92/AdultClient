(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.TubeProfileDomain = api;
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
  const text = (v) => String(v || "").trim();
  function params(row) {
    const raw = text(row.query || row.url);
    return new URLSearchParams(
      raw.includes("?") && raw.startsWith("plugin:")
        ? raw.slice(raw.indexOf("?") + 1)
        : raw.startsWith("mode=") || raw.startsWith("?")
          ? raw.replace(/^\?/, "")
          : "",
    );
  }
  const siteOf = (row) =>
    text(
      params(row).get("website") || row.site || row.media?.provider,
    ).toLowerCase();
  function isLive(row, live = LIVE) {
    return (
      [
        siteOf(row),
        text(row.site).toLowerCase(),
        text(row.media?.provider).toLowerCase(),
      ].some((s) => LIVE.has(s) || live.has(s)) ||
      ["live", "cam", "multicam"].includes(
        row.mediaType || row.media?.kind || row.kind,
      ) ||
      row.scope === "live" ||
      row.source === "live" ||
      row.liveCam === true
    );
  }
  function identity(row) {
    const p = params(row),
      site = siteOf(row),
      url = p.get("url") || text(row.url);
    return url ? site + "|" + url : "title|" + site + "|" + text(row.title);
  }
  function playable(row) {
    if (isLive(row)) return "";
    const p = params(row),
      site = siteOf(row),
      url = p.get("url") || text(row.url);
    if (!/^[a-z0-9_]+$/i.test(site) || !/^https?:\/\//i.test(url)) return "";
    return (
      "plugin://plugin.video.adulthideout/?" +
      new URLSearchParams({ mode: "4", website: site, url })
    );
  }
  function dateOf(row) {
    const raw = text(row.at);
    // Do not invent a date for older events that only have an hour/weekday.
    const parts = raw.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    if (!parts) return null;
    const [, y, m, day, h, minute] = parts.map(Number);
    if (
      m < 1 ||
      m > 12 ||
      day < 1 ||
      day > new Date(Date.UTC(y, m, 0)).getUTCDate() ||
      h > 23 ||
      minute > 59
    )
      return null;
    const d = new Date(raw);
    return Number.isFinite(+d) ? d : null;
  }
  const dayKey = (d) =>
    [
      d.getFullYear(),
      String(d.getMonth() + 1).padStart(2, "0"),
      String(d.getDate()).padStart(2, "0"),
    ].join("-");
  function midnight(d) {
    return new Date(d.getFullYear(), d.getMonth(), d.getDate());
  }
  function shift(d, n) {
    const v = new Date(d);
    v.setDate(v.getDate() + n);
    return v;
  }
  const rank = (map) =>
    [...map]
      .map(([label, count]) => ({ label, count }))
      .sort(
        (a, b) => b.count - a.count || a.label.localeCompare(b.label, "de"),
      );
  function library(ui, live) {
    const videos = new Map(),
      groups = [];
    function add(row, group = "") {
      if (!row || isLive(row, live)) return;
      const kind = row.mediaType || row.media?.kind || row.kind || "video";
      if (kind !== "video" || row.folder) return;
      const key = identity(row),
        old = videos.get(key);
      if (!row.url && !row.query) return;
      if (old) {
        if (group && !old.groups.includes(group)) old.groups.push(group);
        return;
      }
      videos.set(key, { ...row, key, groups: group ? [group] : [] });
    }
    for (const row of ui.saved || []) add(row);
    function walk(nodes, parent = "") {
      for (const group of nodes || []) {
        const name = parent ? parent + " / " + group.name : group.name;
        const rows = (group.items || []).filter(
          (r) =>
            !isLive(r, live) &&
            (r.mediaType || r.media?.kind || r.kind || "video") === "video",
        );
        if (rows.length)
          groups.push({
            id: group.id,
            name,
            count: new Set(rows.map(identity)).size,
          });
        for (const row of rows) add(row, name);
        walk(group.children, name);
      }
    }
    walk(ui.groups);
    return {
      videos: [...videos.values()],
      groups,
      follows: (ui.follows || []).filter((r) => !isLive(r, live)),
      stars: ui.starFavs || [],
      favorites: (ui.favorites || []).filter(
        (id) => !LIVE.has(id) && !live.has(id),
      ),
    };
  }
  function analyze(ui, catalog = {}, filter = {}, now = new Date()) {
    const live = new Set([
      ...(catalog.liveSites || []).map((s) => s.id),
      ...(catalog.sites || []).filter((s) => s.liveOnly).map((s) => s.id),
    ]);
    const all = (ui.events || [])
      .filter((r) => r && !isLive(r, live))
      .map((r, index) => {
        const date = dateOf(r);
        return {
          ...r,
          index,
          date,
          site: siteOf(r),
          source: ["player", "multitube"].includes(r.source)
            ? r.source
            : "legacy",
          kind: r.kind === "open" ? "open" : "play",
          key: identity(r),
        };
      });
    const days = [7, 30, 90].includes(Number(filter.days))
      ? Number(filter.days)
      : 0;
    const today = midnight(now),
      start = days ? shift(today, 1 - days) : null,
      end = +now;
    const base = all.filter(
      (r) =>
        (!filter.site || r.site === filter.site) &&
        (!filter.source || r.source === filter.source),
    );
    const events = base.filter(
      (r) =>
        (!start || (r.date && r.date >= start)) && (!r.date || +r.date <= end),
    );
    const plays = events.filter((r) => r.kind === "play"),
      opens = events.filter((r) => r.kind === "open");
    const dated = plays.filter((r) => r.date),
      activeDays = new Set(dated.map((r) => dayKey(r.date)));
    const sites = new Map(),
      categories = new Map(),
      performers = new Map(),
      opened = new Map(),
      videos = new Map();
    const hours = Array(24).fill(0),
      weekdays = Array(7).fill(0),
      heat = Array.from({ length: 7 }, () => Array(24).fill(0));
    const count = (map, key) => {
      if (key) map.set(key, (map.get(key) || 0) + 1);
    };
    const lib = library(ui, live),
      images = new Map(
        [...lib.videos, ...(ui.history || [])].map((r) => [
          identity(r),
          r.thumb,
        ]),
      );
    for (const r of plays) {
      count(sites, r.site);
      count(categories, r.category);
      count(performers, r.performer);
      const old = videos.get(r.key);
      if (!old)
        videos.set(r.key, {
          ...r,
          thumb: r.thumb || images.get(r.key) || "",
          count: 1,
        });
      else {
        old.count++;
        if (r.date && (!old.date || r.date > old.date))
          Object.assign(old, {
            ...r,
            count: old.count,
            thumb: r.thumb || old.thumb,
          });
      }
      const h = r.date ? r.date.getHours() : r.hour,
        w = r.date ? r.date.getDay() : r.weekday;
      if (Number.isInteger(h) && h >= 0 && h < 24) hours[h]++;
      if (Number.isInteger(w) && w >= 0 && w < 7) weekdays[w]++;
      if (
        Number.isInteger(h) &&
        h >= 0 &&
        h < 24 &&
        Number.isInteger(w) &&
        w >= 0 &&
        w < 7
      )
        heat[w][h]++;
    }
    for (const r of opens) count(opened, r.category || r.title);
    const chronological = dated.slice().sort((a, b) => a.date - b.date);
    const first = chronological[0]?.date,
      last = chronological.at(-1)?.date;
    let longest = 0,
      run = 0,
      prior;
    for (const key of [...activeDays].sort()) {
      const d = new Date(key + "T00:00:00");
      run = prior && dayKey(shift(prior, 1)) === key ? run + 1 : 1;
      longest = Math.max(longest, run);
      prior = d;
    }
    const span =
      days ||
      Math.min(
        90,
        first ? Math.round((today - midnight(first)) / 86400000) + 1 : 30,
      );
    const timeline = Array.from({ length: Math.max(1, span) }, (_, i) => ({
      day: dayKey(shift(today, i - span + 1)),
      play: 0,
      open: 0,
    }));
    const buckets = new Map(timeline.map((r) => [r.day, r]));
    for (const r of events)
      if (r.date && buckets.has(dayKey(r.date)))
        buckets.get(dayKey(r.date))[r.kind]++;
    const previous = days
      ? base.filter(
          (r) =>
            r.kind === "play" &&
            r.date &&
            r.date >= shift(start, -days) &&
            r.date < start,
        ).length
      : null;
    return {
      all,
      events,
      plays,
      opens,
      days,
      start,
      previous,
      timeline,
      hours,
      weekdays,
      heat,
      sites: rank(sites),
      categories: rank(categories),
      performers: rank(performers),
      opened: rank(opened),
      videos: [...videos.values()].sort(
        (a, b) =>
          b.count - a.count ||
          (b.date || 0) - (a.date || 0) ||
          a.title.localeCompare(b.title, "de"),
      ),
      unique: videos.size,
      repeats: plays.length - videos.size,
      activeDays: activeDays.size,
      average: activeDays.size ? dated.length / activeDays.size : 0,
      longest,
      first,
      last,
      undated: base.filter((r) => !r.date).length,
      excluded: (ui.events || []).length - all.length,
      library: lib,
    };
  }
  function csv(events) {
    const cell = (v) =>
      '"' +
      String(v ?? "")
        .replace(/^(?:\s*[=+@\-]|[\t\r\n])/, "'$&")
        .replaceAll('"', '""') +
      '"';
    return (
      "\uFEFF" +
      [
        [
          "Zeitpunkt",
          "Aktion",
          "Seite",
          "Titel",
          "Kategorie",
          "Model / Kanal",
          "Quelle",
          "URL",
        ],
        ...events.map((r) => [
          r.at,
          r.kind === "open" ? "Bereich geöffnet" : "Videoaufruf",
          r.site,
          r.title,
          r.category,
          r.performer,
          r.source,
          r.url,
        ]),
      ]
        .map((row) => row.map(cell).join(";"))
        .join("\r\n")
    );
  }
  return { analyze, identity, isLive, siteOf, playable, dateOf, dayKey, csv };
});
