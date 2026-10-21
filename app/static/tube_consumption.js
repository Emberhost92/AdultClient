/* Sample actual media progress, not elapsed time since opening the player. */
(function (root) {
  "use strict";
  const players = new Set(),
    pending = new Map(),
    bus = new BroadcastChannel("ah-tube-measurement");
  let saveError = false;
  let enabled = true,
    timer,
    flushing,
    lastStatus = 0;
  const id = () => crypto.randomUUID();
  const merge = (rows, a, b) => {
    if (!(b > a)) return;
    if (rows.length && a <= rows.at(-1)[1] + 0.05)
      rows.at(-1)[1] = Math.max(b, rows.at(-1)[1]);
    else if (rows.length < 512) rows.push([a, b]);
  };
  const imageSafe = (v) =>
    String(v || "").startsWith("https://") ||
    String(v || "").startsWith("/api/") ||
    String(v || "").startsWith("http://127.0.0.1:")
      ? String(v)
      : "";
  function meta(row, facts = {}) {
    return {
      query: row.query,
      url: row.url,
      site: row.site,
      title: row.title,
      thumb: imageSafe(row.thumb),
      uploader: row.uploader || "",
      duration: Number(row.duration) || 0,
      facts: {
        categories: facts.categories || row.categories || [],
        tags: facts.tags || row.tags || [],
        stars: facts.stars || row.models || [],
      },
      film: row.film || {},
    };
  }
  function rectVisible(video) {
    if (!video.isConnected || video.closest("[hidden],.hidden")) return false;
    const r = video.getBoundingClientRect();
    return (
      r.width > 0 &&
      r.height > 0 &&
      r.bottom > 0 &&
      r.top < innerHeight &&
      r.right > 0 &&
      r.left < innerWidth
    );
  }
  class Measurement {
    constructor(video, row, source, facts) {
      this.video = video;
      this.listeners = [];
      this.stopped = false;
      this.last = performance.now();
      this.position = Number(video.currentTime) || 0;
      this.wasRunning = false;
      this.seeking = false;
      this.data = {
        id: id(),
        source,
        started: Date.now() / 1000,
        video: meta(row, facts),
        playing: [],
        visible: [],
        focused: [],
        coverage: [],
        duration: 0,
        seeks: 0,
        pauses: 0,
        stalls: 0,
        ended: false,
      };
      const on = (event, fn) => {
        video.addEventListener(event, fn);
        this.listeners.push(() => video.removeEventListener(event, fn));
      };
      on("seeking", () => {
        this.sample();
        this.seeking = true;
        if (enabled) {
          this.data.seeks++;
          this.changed();
        }
      });
      on("seeked", () => {
        this.position = Number(video.currentTime) || 0;
        this.last = performance.now();
        this.seeking = false;
      });
      on("pause", () => {
        this.sample();
        if (enabled && !video.ended) {
          this.data.pauses++;
          this.changed();
        }
      });
      on("waiting", () => {
        this.sample();
        if (enabled) {
          this.data.stalls++;
          this.changed();
        }
      });
      on("ended", () => {
        this.sample();
        this.data.ended = true;
        this.changed();
        flush();
      });
      on("playing", () => {
        this.last = performance.now();
        this.position = Number(video.currentTime) || 0;
        this.wasRunning = true;
      });
      on("loadedmetadata", () => {
        this.update({});
      });
      players.add(this);
      ensureTimer();
    }
    changed() {
      if (enabled) pending.set(this.data.id, this);
    }
    update(patch) {
      if (this.stopped) return;
      const v = this.data.video;
      if (patch.facts)
        for (const [key, value] of Object.entries(patch.facts))
          if (Array.isArray(value) && value.length) v.facts[key] = value;
      if (patch.film) v.film = patch.film;
      if (patch.models?.length) v.facts.stars = patch.models;
      this.data.duration = Number.isFinite(this.video.duration)
        ? Math.min(604800, this.video.duration)
        : this.data.duration;
      if (this.data.duration) v.duration = this.data.duration;
      if (this.data.playing.length) this.changed();
    }
    sample() {
      if (this.stopped) return;
      const now = performance.now(),
        wall = (now - this.last) / 1000,
        position = Number(this.video.currentTime) || 0,
        progress = position - this.position;
      const running =
        !this.video.paused && !this.video.ended && this.video.readyState >= 2;
      if (
        enabled &&
        this.wasRunning &&
        !this.seeking &&
        wall > 0 &&
        wall <= 2.5 &&
        progress > 0 &&
        progress <= Math.max(1, wall * this.video.playbackRate * 1.7)
      ) {
        const end = Date.now() / 1000,
          start = end - wall;
        merge(this.data.playing, start, end);
        merge(this.data.coverage, this.position, position);
        if (!document.hidden && rectVisible(this.video)) {
          merge(this.data.visible, start, end);
          if (document.hasFocus()) merge(this.data.focused, start, end);
        }
        this.update({});
        this.changed();
      }
      this.wasRunning = running;
      this.last = now;
      this.position = position;
    }
    stop() {
      if (this.stopped) return;
      this.sample();
      this.data.finished = true;
      this.changed();
      this.stopped = true;
      players.delete(this);
      for (const off of this.listeners) off();
      this.listeners = [];
      this.video = null;
      flush();
      if (!players.size && !pending.size && timer) {
        clearInterval(timer);
        timer = null;
      }
    }
  }
  async function flush(beacon = false) {
    if ((flushing && !beacon) || !pending.size) return;
    const rows = [...pending.values()].slice(0, 24),
      snapshots = rows.map((row) => JSON.parse(JSON.stringify(row.data))),
      batches = [];
    let current = [];
    const push = (copy) => {
      if (
        current.length >= 24 ||
        (current.length &&
          new Blob([JSON.stringify({ sessions: [...current, copy] })]).size >
            50000)
      ) {
        batches.push(current);
        current = [];
      }
      current.push(copy);
    };
    for (const copy of snapshots) {
      if (new Blob([JSON.stringify(copy)]).size > 45000) {
        const max = Math.max(
          ...["playing", "visible", "focused", "coverage"].map(
            (key) => copy[key].length,
          ),
        );
        for (let i = 0; i < max; i += 128)
          push({
            ...copy,
            ...Object.fromEntries(
              ["playing", "visible", "focused", "coverage"].map((key) => [
                key,
                copy[key].slice(i, i + 128),
              ]),
            ),
          });
      } else push(copy);
    }
    if (current.length) batches.push(current);
    if (beacon) {
      for (const batch of batches)
        navigator.sendBeacon(
          "/api/tube-profile",
          new Blob([JSON.stringify({ sessions: batch })], {
            type: "application/json",
          }),
        );
      return;
    }
    flushing = true;
    try {
      for (const batch of batches) {
        const response = await fetch("/api/tube-profile", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sessions: batch }),
          signal: AbortSignal.timeout(8000),
        });
        if (!response.ok)
          throw Error("Zeitmessung konnte nicht gespeichert werden.");
        const result = await response.json();
        if (result.recording === false) {
          enabled = false;
          break;
        }
      }
      if (enabled)
        for (const sent of snapshots) {
          const row = pending.get(sent.id);
          if (row && JSON.stringify(row.data) === JSON.stringify(sent))
            pending.delete(sent.id);
        }
      saveError = false;
      root.dispatchEvent(
        new CustomEvent("tube-measurement-status", {
          detail: { error: false },
        }),
      );
    } catch {
      saveError = true;
      root.dispatchEvent(
        new CustomEvent("tube-measurement-status", { detail: { error: true } }),
      );
    } finally {
      flushing = false;
      if (!players.size && !pending.size && timer) {
        clearInterval(timer);
        timer = null;
      }
    }
  }
  async function status() {
    lastStatus = Date.now();
    try {
      const r = await fetch("/api/tube-profile?status=1", {
        cache: "no-store",
      });
      if (r.ok) enabled = (await r.json()).recording !== false;
    } catch {
      /* Retry without disturbing playback. */
    }
  }
  function ensureTimer() {
    if (timer) return;
    timer = setInterval(() => {
      for (const p of players) p.sample();
      if (Date.now() - (ensureTimer.flushAt || 0) > 10000) {
        ensureTimer.flushAt = Date.now();
        flush();
      }
      if (Date.now() - lastStatus > 30000) status();
    }, 1000);
    status();
  }
  bus.onmessage = (e) => {
    if (typeof e.data?.recording === "boolean") {
      for (const p of players) p.sample();
      enabled = e.data.recording;
      for (const p of players) {
        p.last = performance.now();
        p.wasRunning = false;
      }
    }
  };
  root.addEventListener("pagehide", (event) => {
    for (const p of players) {
      p.sample();
      if (!event.persisted) {
        p.data.finished = true;
        p.changed();
      }
    }
    flush(true);
  });
  document.addEventListener("visibilitychange", () => {
    for (const p of players) {
      p.sample();
      p.wasRunning = false;
    }
    flush();
  });
  root.TubeConsumption = {
    attach(video, row, options = {}) {
      if (root.TubeProfileDomain.isLive(row) || options.live) return null;
      const raw = String(row.query || row.url || ""),
        p = new URLSearchParams(
          raw.startsWith("plugin:")
            ? raw.split("?").slice(1).join("?")
            : raw.replace(/^\?/, ""),
        );
      if (p.has("mode") && p.get("mode") !== "4") return null;
      const canonical = root.TubeProfileDomain.playable(row);
      if (!canonical) return null;
      try {
        const target = new URL(
          new URLSearchParams(canonical.split("?").slice(1).join("?")).get(
            "url",
          ),
        );
        if (target.username || target.password) return null;
      } catch {
        return null;
      }
      return new Measurement(
        video,
        {
          ...row,
          query: undefined,
          url: canonical,
          site: root.TubeProfileDomain.siteOf(row),
        },
        options.source || "player",
        options.facts || {},
      );
    },
    flush,
    async setRecording(on) {
      for (const p of players) p.sample();
      await flush();
      const response = await fetch("/api/tube-profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recording: !!on }),
      });
      if (!response.ok)
        throw Error("Die Erfassung konnte nicht geändert werden.");
      enabled = (await response.json()).recording;
      bus.postMessage({ recording: enabled });
      for (const p of players) {
        p.last = performance.now();
        p.wasRunning = false;
      }
      return enabled;
    },
    get error() {
      return saveError;
    },
    get recording() {
      return enabled;
    },
    get players() {
      return players;
    },
  };
})(window);
