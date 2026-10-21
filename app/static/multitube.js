(function (root) {
  "use strict";
  const D = root.MultiTubeDomain;
  const el = (tag, props = {}, ...children) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "text") n.textContent = v;
      else if (k === "class") n.className = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (k in n) n[k] = v;
      else n.setAttribute(k, v);
    }
    n.append(...children.filter(Boolean));
    return n;
  };
  const button = (label, action, props = {}) =>
    el("button", { type: "button", text: label, onclick: action, ...props });
  const option = (value, label) =>
    el("option", { value: String(value), text: label });
  function select(label, rows, change) {
    const s = el("select", {
      "aria-label": label,
      onchange: (e) => change(e.target.value),
    });
    for (const [v, t] of rows) s.append(option(v, t));
    return s;
  }
  const field = (name, node) =>
    el("label", {}, el("span", { text: name }), node);
  const icon = (label, sign, action) =>
    button(sign, action, { title: label, "aria-label": label });
  const input = (label, value, change, type = "text") =>
    el("input", {
      type,
      value: value ?? "",
      "aria-label": label,
      onchange: (e) => change(e.target.value),
    });
  const download = (blob, name) => {
    const u = URL.createObjectURL(blob),
      a = el("a", { href: u, download: name });
    a.click();
    setTimeout(() => URL.revokeObjectURL(u), 10000);
  };
  let shared, opening, instance, context;
  const owner = D.id(),
    peers = new Map(),
    bus = new BroadcastChannel("ah-multitube-window");
  bus.onmessage = (e) => {
    const m = e.data || {};
    if (m.owner === owner) return;
    if (m.type === "presence")
      peers.set(m.owner, { at: Date.now(), workspace: m.workspace });
    if (m.type === "ping" && instance?.active) announce();
    if (
      m.type === "takeover" &&
      instance?.owner &&
      instance.workspaceId === m.workspace
    ) {
      instance.flushProgress().finally(() => {
        instance.owner = false;
        instance.destroyAll();
        shared.release(m.workspace, owner).catch(() => {});
        instance.render();
      });
    }
  };
  function announce() {
    if (instance?.active)
      bus.postMessage({
        type: "presence",
        owner,
        workspace: instance.workspaceId,
      });
  }
  function hasWindow() {
    return (
      instance?.active ||
      [...peers.values()].some((p) => Date.now() - p.at < 6500)
    );
  }
  async function store() {
    if (shared?.value) return shared;
    if (opening) return opening;
    opening = (async () => {
      const s = new root.MultiTubeStore();
      s.onError = (e) => instance?.notice(e.message, true);
      let old = [];
      try {
        old = JSON.parse(localStorage.getItem("ah-multi") || "[]");
      } catch {
        /* Keep the original key unchanged. */
      }
      await s.open(
        D.migrate(old, Number(localStorage.getItem("ah-multi-count") || 4)),
      );
      shared = s;
      return s;
    })();
    try {
      return await opening;
    } catch (e) {
      opening = null;
      throw e;
    }
  }
  class Studio {
    constructor() {
      this.players = new Map();
      this.active = false;
      this.owner = false;
      this.workspaceId = null;
      this.selection = new Set();
      this.search = "";
      this.source = "all";
      this.sort = "title";
      this.epoch = 0;
      this.pending = 0;
      this.progress = new Map();
      this.restorePaused = new Set();
      this.userAudio = false;
      this.detailsSignature = "";
      this.sidebarSignature = "";
      this.pendingPersonal = new Map();
      this.personalTimers = new Map();
      this.personalSaves = new Map();
      this.dialogs = new Set();
      this.handleKey = (e) => this.onKey(e);
      this.handleVisibility = () => this.policy();
      this.onPageHide = () => {
        this.flushProgress();
        this.destroyAll();
        if (this.owner)
          this.store?.release(this.workspaceId, owner).catch(() => {});
      };
      root.addEventListener("pagehide", this.onPageHide);
    }
    w() {
      return D.get(this.data, this.workspaceId);
    }
    async open(panel, ctx) {
      this.ctx = ctx;
      this.panel = panel;
      this.active = true;
      this.store = await store();
      this.data = this.store.value;
      this.store.onMessage = (message) => {
        if (
          this.active &&
          this.owner &&
          message.lease === this.workspaceId &&
          message.owner !== owner
        ) {
          this.owner = false;
          this.epoch++;
          this.destroyAll();
          this.notice("Wiedergabe wurde in einem anderen Fenster übernommen.");
          this.render();
        }
      };
      this.unsubscribe?.();
      this.unsubscribe = this.store.subscribe((v) => {
        this.data = v;
        if (
          !this.importing &&
          !v.workspaces.some((w) => w.id === this.workspaceId && !w.archived)
        )
          this.switchWorkspace("default");
        this.render();
      });
      const requested = new URLSearchParams(location.search).get("workspace");
      this.workspaceId =
        requested &&
        this.data.workspaces.some((w) => w.id === requested && !w.archived)
          ? requested
          : this.data.active;
      this.restorePaused = new Set(Object.keys(this.w().entries));
      this.owner = await this.store.claim(this.workspaceId, owner);
      if (!this.root?.isConnected) this.build();
      else this.resize?.observe(this.stage);
      this.loadFilter();
      document.addEventListener("keydown", this.handleKey, true);
      document.addEventListener("visibilitychange", this.handleVisibility);
      clearInterval(this.timer);
      this.timer = setInterval(() => this.tick(), 1000);
      this.render();
      announce();
    }
    leave() {
      if (!this.active) return;
      this.active = false;
      this.epoch++;
      this.flushProgress();
      this.destroyAll();
      this.unsubscribe?.();
      this.unsubscribe = null;
      clearInterval(this.timer);
      this.resize?.disconnect();
      document.removeEventListener("keydown", this.handleKey, true);
      document.removeEventListener("visibilitychange", this.handleVisibility);
      if (this.owner)
        this.store.release(this.workspaceId, owner).catch(() => {});
      this.owner = false;
      for (const d of this.dialogs) d.close();
    }
    async change(fn, backup = false) {
      if (!this.data) throw Error("Multitube lädt noch.");
      return this.store.mutate(
        (s) => {
          fn(s, D.get(s, this.workspaceId));
          return s;
        },
        true,
        backup,
      );
    }
    action(fn) {
      return async (...args) => {
        try {
          await fn(...args);
        } catch (e) {
          this.notice(e.message || String(e), true);
        }
      };
    }
    notice(message, error = false) {
      if (!this.message) return;
      this.message.textContent = message;
      this.message.hidden = !message;
      this.message.classList.toggle("mt-error", error);
    }
    async toggleSidebar(force) {
      if (innerWidth <= 760) {
        this.mobileSidebar = force ?? !this.mobileSidebar;
        this.render();
        return;
      }
      await this.change((s, w) => {
        w.sidebar = force ?? !w.sidebar;
      });
    }
    async takeOver() {
      bus.postMessage({ type: "takeover", owner, workspace: this.workspaceId });
      await new Promise((r) => setTimeout(r, 250));
      this.owner = await this.store.claim(this.workspaceId, owner, true);
      this.restorePaused = new Set(Object.keys(this.w().entries));
      this.notice(
        "Wiedergabe in diesem Fenster übernommen. Mit ▶ fortsetzen.",
      );
      this.render();
    }
    async switchWorkspace(key) {
      if (key === this.workspaceId) return;
      await this.flushProgress();
      if (this.owner) await this.store.release(this.workspaceId, owner);
      this.epoch++;
      this.destroyAll();
      this.workspaceId = key;
      this.loadFilter();
      await this.change((s) => {
        s.active = key;
      });
      this.owner = await this.store.claim(key, owner);
      this.restorePaused = new Set(Object.keys(this.w().entries));
      this.detailsSignature = "";
      this.render();
      announce();
    }
    build() {
      this.panel.closest("#view-multi")?.classList.add("mt-host");
      this.panel.replaceChildren();
      this.panel.style.cssText = "display:flex;flex:1;min-height:0;min-width:0";
      this.root = el("section", {
        class: "mt-root",
        "aria-label": "Multitube-Arbeitsbereich",
      });
      this.panel.append(this.root);
      this.top = el("div", { class: "mt-top" });
      this.workspaces = select("Arbeitsbereich", [], (v) =>
        this.action(() => this.switchWorkspace(v))(),
      );
      this.capacity = select(
        "Plätze",
        Array.from({ length: 20 }, (_, i) => [i + 1, String(i + 1)]),
        (v) =>
          this.action(() =>
            this.change((s, w) => {
              w.capacity = Number(v);
            }),
          )(),
      );
      this.view = select(
        "Ansicht",
        [
          ["grid", "Raster"],
          ["focus", "Fokus"],
          ["compare", "Vergleich"],
        ],
        (v) =>
          this.action(() =>
            this.change((s, w) => {
              w.layout = v;
            }),
          )(),
      );
      this.audio = select(
        "Tonmodus",
        [
          ["focus", "Ton folgt Fokus"],
          ["solo", "Ein Video mit Ton"],
          ["manual", "Manuell mischen"],
        ],
        (v) => {
          this.userAudio = true;
          this.action(() =>
            this.change((s, w) => {
              w.settings.audio = v;
              if (v === "solo") w.settings.solo = w.selected || w.focus;
            }),
          )();
        },
      );
      this.pauseAllButton = button(
        "Ⅱ Alle",
        this.action(() => this.pauseAll()),
        {
          title: "Alle pausieren; erneut drücken setzt nur diese Videos fort",
          "aria-label": "Alle pausieren oder fortsetzen",
        },
      );
      this.pagePrevious = icon(
        "Vorherige Videoseite",
        "‹",
        this.action(() =>
          this.change((s, w) => {
            w.page = Math.max(0, (w.page || 0) - 1);
          }),
        ),
      );
      this.pageNext = icon(
        "Nächste Videoseite",
        "›",
        this.action(() =>
          this.change((s, w) => {
            w.page = (w.page || 0) + 1;
          }),
        ),
      );
      this.pageIndicator = el("span", { class: "mt-progress" });
      this.top.append(
        el("strong", { class: "mt-title", text: "Multitube" }),
        this.workspaces,
        icon("Arbeitsbereiche verwalten", "⚙", () => this.workspacePanel()),
        button("+ Videos", () => {
          this.mobileSidebar = true;
          this.source = "current";
          this.search = "";
          this.searchInput.value = "";
          this.sourceSelect.value = "current";
          this.saveFilter();
          this.change((s, w) => {
            w.sidebar = true;
          }).catch((e) => this.notice(e.message, true));
          this.sidebarSignature = "";
          this.renderSidebar();
        }),
        field("Plätze", this.capacity),
        this.view,
        this.pagePrevious,
        this.pageIndicator,
        this.pageNext,
        button(
          "▶ Alle",
          this.action(() => this.playAll()),
        ),
        this.pauseAllButton,
        this.audio,
        (this.muteAllButton = icon(
          "Vorübergehend alles stumm",
          "♪",
          this.action(() =>
            this.change((s, w) => {
              w.settings.muteAll = !w.settings.muteAll;
            }),
          ),
        )),
        el("span", { class: "mt-grow" }),
        icon(
          "Videoauswahl ein-/ausblenden",
          "☰",
          this.action(() => this.toggleSidebar()),
        ),
        icon(
          "Details ein-/ausblenden",
          "ⓘ",
          this.action(() =>
            this.change((s, w) => {
              w.details = !w.details;
            }),
          ),
        ),
        button("Mehr ⋯", () => this.morePanel()),
      );
      this.message = el("p", {
        class: "mt-notice",
        role: "status",
        hidden: true,
      });
      this.work = el("div", { class: "mt-work" });
      this.sidebar = el("aside", {
        class: "mt-sidebar",
        "aria-label": "Videoauswahl und Warteschlange",
      });
      this.searchInput = el("input", {
        type: "search",
        placeholder: "Titel, Site, Tags, Notizen …",
        "aria-label": "Videos durchsuchen",
        oninput: (e) => {
          this.search = e.target.value;
          this.saveFilter();
          this.sidebarSignature = "";
          this.renderSidebar();
        },
      });
      this.sourceSelect = select(
        "Videoquelle",
        [
          ["all", "Alle gespeicherten Videos"],
          ["queue", "Warteschlange"],
          ["favorites", "Favoriten"],
          ["current", "Aktuelle Suchergebnisse"],
          ["groups", "Videos aus Gruppen"],
        ],
        (v) => {
          this.source = v;
          this.saveFilter();
          this.selection.clear();
          this.sidebarSignature = "";
          this.renderSidebar();
        },
      );
      this.sortSelect = select(
        "Sortierung",
        [
          ["title", "Titel A–Z"],
          ["site", "Anbieter"],
          ["duration", "Dauer"],
          ["recent", "Zuletzt hinzugefügt"],
        ],
        (v) => {
          this.sort = v;
          this.saveFilter();
          this.sidebarSignature = "";
          this.renderSidebar();
        },
      );
      this.sideCount = el("small", { class: "mt-progress" });
      this.sideTools = el(
        "div",
        { class: "mt-side-tools" },
        button("Alle wählen", () => {
          for (const r of this.filteredRows()) this.selection.add(r.key);
          this.sidebarSignature = "";
          this.renderSidebar();
        }),
        button(
          "Einsetzen",
          this.action(() => this.addSelection(false)),
        ),
        button(
          "Vormerken",
          this.action(() => this.addSelection(true)),
        ),
      );
      this.list = el("div", { class: "mt-list" });
      this.sidebar.append(
        this.searchInput,
        this.sourceSelect,
        this.sortSelect,
        this.sideCount,
        this.sideTools,
        this.list,
      );
      this.stage = el("div", { class: "mt-stage" });
      this.canvas = el("div", {
        class: "mt-canvas",
        "aria-label": "Videoplätze",
      });
      this.stage.append(
        this.canvas,
        button(
          "Bedienung einblenden",
          this.action(() =>
            this.change((s, w) => {
              w.clean = false;
              w.sidebar = true;
            }),
          ),
          { class: "mt-reveal" },
        ),
      );
      this.details = el("section", {
        class: "mt-details",
        "aria-label": "Ausgewähltes Video",
      });
      this.work.append(this.sidebar, this.stage, this.details);
      this.footer = el("div", { class: "mt-footer", role: "status" });
      this.root.append(this.top, this.message, this.work, this.footer);
      this.resize = new ResizeObserver(() => {
        this.scheduleLayout();
        this.render();
      });
      this.resize.observe(this.stage);
    }
    render() {
      if (!this.active || !this.root) return;
      if (this.renderFrame) return;
      this.renderFrame = requestAnimationFrame(() => {
        this.renderFrame = 0;
        if (!this.active) return;
        const w = this.w();
        this.root.classList.toggle("mt-clean", w.clean);
        this.work.classList.toggle("no-sidebar", !w.sidebar);
        this.work.classList.toggle("has-details", w.details);
        this.sidebar.hidden =
          !w.sidebar || (innerWidth <= 760 && !this.mobileSidebar);
        this.details.hidden = !w.details;
        const signature = this.data.workspaces
          .map((w) => w.id + w.name + w.archived)
          .join("|");
        if (signature !== this.workspaceSignature) {
          this.workspaceSignature = signature;
          this.workspaces.replaceChildren(
            ...this.data.workspaces
              .filter((w) => !w.archived)
              .map((w) => option(w.id, w.name)),
          );
        }
        this.workspaces.value = w.id;
        this.capacity.value = String(w.capacity);
        this.view.value = w.layout;
        this.audio.value = w.settings.audio;
        this.muteAllButton.classList.toggle("mt-active", !!w.settings.muteAll);
        this.muteAllButton.setAttribute(
          "aria-pressed",
          String(!!w.settings.muteAll),
        );
        this.pauseAllButton.textContent = this.batchPaused
          ? "▶ Fortsetzen"
          : "Ⅱ Alle";
        const paging = this.paging();
        this.pagePrevious.hidden =
          this.pageNext.hidden =
          this.pageIndicator.hidden =
            paging.pages <= 1;
        this.pagePrevious.disabled = paging.page === 0;
        this.pageNext.disabled = paging.page >= paging.pages - 1;
        this.pageIndicator.textContent = paging.page + 1 + " / " + paging.pages;
        this.reconcile();
        this.renderSidebar();
        this.renderDetails();
        this.status();
        this.scheduleLayout();
      });
    }
    libraryRows() {
      const isVideo = row => !root.MediaLibrary || root.MediaLibrary.media(row).kind === 'video';
      const all = new Map(
        Object.values(this.data.videos).filter(isVideo).map((v) => [v.key, v]),
      );
      for (const row of this.ctx.library?.() || []) {
        try {
          if (!isVideo(row)) continue;
          const v = D.video(row);
          all.set(v.key, { ...all.get(v.key), ...v });
        } catch {
          /* Non-video entries are deliberately excluded. */
        }
      }
      return [...all.values()];
    }
    filteredRows() {
      let rows;
      if (this.source === "queue") {
        return this.w()
          .queue.map((k) => {
            const e = this.w().entries[k];
            return { ...this.data.videos[e.media], entryId: k };
          })
          .filter((r) => this.matches(r));
      }
      rows = this.libraryRows();
      if (this.source === "favorites")
        rows = rows.filter(
          (r) =>
            this.data.personal[r.key]?.favorite ||
            (this.ctx.favorites?.() || []).some((v) => {
              try {
                return D.video(v).key === r.key;
              } catch {
                return false;
              }
            }),
        );
      if (this.source === "current") {
        const keys = new Set(this.data.candidates || []);
        for (const row of this.ctx.current?.() || []) {
          try {
            keys.add(D.video(row).key);
          } catch {}
        }
        rows = rows.filter((r) => keys.has(r.key));
      }
      if (this.source === "groups" || this.source.startsWith("group:")) {
        const keys = new Set(
          (this.ctx.groups?.() || [])
            .filter(
              (g) => this.source === "groups" || g.id === this.source.slice(6),
            )
            .flatMap((g) => g.items || [])
            .map((v) => {
              try {
                return D.video(v).key;
              } catch {
                return "";
              }
            }),
        );
        rows = rows.filter((r) => keys.has(r.key));
      }
      rows = rows.filter((r) => this.matches(r));
      rows.sort((a, b) =>
        this.sort === "site"
          ? a.site.localeCompare(b.site) || a.title.localeCompare(b.title)
          : this.sort === "duration"
            ? (b.duration || 0) - (a.duration || 0)
            : this.sort === "recent"
              ? Object.keys(this.data.videos).indexOf(b.key) -
                Object.keys(this.data.videos).indexOf(a.key)
              : a.title.localeCompare(b.title, "de", { numeric: true }),
      );
      return rows;
    }
    matches(r) {
      const p = this.data.personal[r.key] || {};
      return [r.title, r.site, r.uploader, p.notes, ...(p.tags || [])]
        .join(" ")
        .toLocaleLowerCase()
        .includes(this.search.trim().toLocaleLowerCase());
    }
    renderSidebar() {
      if (!this.list) return;
      const groups = this.ctx.groups?.() || [],
        signature = JSON.stringify(groups.map((g) => [g.id, g.title]));
      if (signature !== this.groupSignature) {
        this.groupSignature = signature;
        for (const o of [...this.sourceSelect.options])
          if (o.value.startsWith("group:")) o.remove();
        for (const g of groups)
          this.sourceSelect.append(
            option("group:" + g.id, "Gruppe: " + g.title),
          );
        this.sourceSelect.value = this.source;
      }
      const rows = this.filteredRows(),
        w = this.w();
      const sig = JSON.stringify([
        rows.map((r) => [r.key, r.entryId, r.title]),
        w.slots,
        w.queue,
        [...this.selection],
        this.source,
        this.search,
      ]);
      if (sig === this.sidebarSignature) return;
      this.sidebarSignature = sig;
      const scroll = this.list.scrollTop;
      this.list.replaceChildren();
      this.sideCount.textContent =
        rows.length + " Videos · " + this.selection.size + " ausgewählt";
      for (const row of rows.slice(0, this.listLimit || 100)) {
        const occupied = w.slots.findIndex(
            (k) => k && w.entries[k]?.media === row.key,
          ),
          queued = w.queue.some((k) => w.entries[k]?.media === row.key);
        const check = el("input", {
            type: "checkbox",
            checked: this.selection.has(row.key),
            "aria-label": "Auswählen: " + row.title,
            onchange: (e) => {
              if (e.target.checked) this.selection.add(row.key);
              else this.selection.delete(row.key);
              this.sidebarSignature = "";
              this.renderSidebar();
            },
          }),
          img = el("img", {
            src: row.thumb || this.ctx.image?.(row.preview?.[0]) || "",
            alt: "",
            loading: "lazy",
          });
        const fallback = () =>
          el("span", {
            class: "mt-poster-letter",
            text: row.site.slice(0, 1).toUpperCase(),
          });
        img.onerror = () => img.replaceWith(fallback());
        if (!img.getAttribute("src")) img.replaceWith(fallback());
        const actions = el("div", { class: "mt-row-actions" });
        if (row.entryId) {
          actions.append(
            button(
              "▶",
              this.action(() => this.placeEntry(row.entryId)),
              { title: "In einen freien Platz einsetzen" },
            ),
            button(
              "↑",
              this.action(() => this.moveQueue(row.entryId, -1)),
            ),
            button(
              "↓",
              this.action(() => this.moveQueue(row.entryId, 1)),
            ),
            button(
              "×",
              this.action(() => this.remove(row.entryId)),
            ),
          );
        } else
          actions.append(
            button(
              occupied >= 0
                ? "Platz " + (occupied + 1)
                : queued
                  ? "Vorgemerkt"
                  : "+ Einsetzen",
              this.action(() => this.addRows([row], false)),
            ),
            button(
              "+ Liste",
              this.action(() => this.addRows([row], true)),
            ),
          );
        const body = el(
          "div",
          {},
          el("strong", {
            class: "mt-row-title",
            text: row.title,
            title: row.title,
          "data-i18n-content":""}),
          el("small", {
            class: "mt-row-meta",
            text:
              row.site +
              (row.duration ? " · " + D.clock(row.duration) : "") +
              (occupied >= 0 ? " · Platz " + (occupied + 1) : ""),
          }),
          actions,
        );
        const n = el(
          "div",
          {
            class: "mt-list-row",
            draggable: true,
            ondragstart: (e) => {
              e.dataTransfer.setData(
                "application/x-multitube-video",
                JSON.stringify(row),
              );
            },
          },
          check,
          img.getAttribute("src") ? img : fallback(),
          body,
        );
        this.list.append(n);
      }
      if (rows.length > (this.listLimit || 100))
        this.list.append(
          button("Weitere 100 anzeigen", () => {
            this.listLimit = (this.listLimit || 100) + 100;
            this.sidebarSignature = "";
            this.renderSidebar();
          }),
        );
      if (!rows.length)
        this.list.append(
          el("p", {
            class: "mt-progress",
            text:
              this.source === "current"
                ? "Videos in einer Seitenliste suchen und über „Zu Multitube“ hinzufügen. Oder eine Videoseite über „Mehr → Videolink hinzufügen“ öffnen."
                : "Keine passenden Videos. Die Suche verändert keine laufende Wiedergabe.",
          }),
        );
      this.list.scrollTop = scroll;
    }
    async addRows(rows, queue = false, duplicate = false, target = null) {
      await this.change((s, w) =>
        D.add(s, w.id, rows, { queue, duplicate, target }),
      );
      this.notice(
        rows.length + " Video(s) übernommen. Belegte Plätze bleiben erhalten.",
      );
    }
    async addSelection(queue) {
      const rows = this.filteredRows().filter((r) => this.selection.has(r.key));
      if (!rows.length) throw Error("Bitte zuerst Videos auswählen.");
      await this.addRows(rows, queue);
      this.selection.clear();
      this.sidebarSignature = "";
      this.renderSidebar();
    }
    async moveQueue(entry, delta) {
      await this.change((s, w) => {
        const a = w.queue.indexOf(entry),
          b = D.clamp(a + delta, 0, w.queue.length - 1);
        if (a >= 0) [w.queue[a], w.queue[b]] = [w.queue[b], w.queue[a]];
      });
    }
    async placeEntry(entry) {
      await this.change((s, w) => {
        const at = w.slots.findIndex((k, i) => !k && i < w.capacity);
        if (at < 0)
          throw Error(
            "Alle sichtbaren Plätze sind belegt. Bitte die Platzzahl erhöhen oder das Video auf einen Platz ziehen.",
          );
        D.place(w, entry, at);
      });
    }
    paging() {
      const w = this.w();
      if (w.layout === "compare")
        return { size: w.capacity, pages: 1, page: 0 };
      const width = this.stage?.clientWidth || 1100,
        height = this.stage?.clientHeight || 700;
      const size = w.settings.fitAll
        ? w.capacity
        : Math.max(
            1,
            Math.min(
              w.capacity,
              Math.max(1, Math.floor(width / 210)) *
                Math.max(1, Math.floor(height / 180)),
            ),
          );
      const pages = Math.ceil(w.capacity / size),
        page = Math.min(Math.max(0, w.page || 0), pages - 1);
      return { size, pages, page };
    }
    visible() {
      const w = this.w(),
        all = w.slots.slice(0, w.capacity).map((id, slot) => ({ id, slot }));
      if (w.layout === "compare") {
        const used = all.filter((r) => r.id),
          a = used.find((r) => r.id === w.focus) || used[0],
          b =
            used.find((r) => r.id === w.selected && r.id !== a?.id) ||
            used.find((r) => r.id !== a?.id);
        return [a, b].filter(Boolean);
      }
      const paging = this.paging();
      let rows = all.slice(
        paging.page * paging.size,
        (paging.page + 1) * paging.size,
      );
      if (
        w.layout === "focus" &&
        w.focus &&
        all.some((r) => r.id === w.focus) &&
        !rows.some((r) => r.id === w.focus)
      ) {
        rows = [all.find((r) => r.id === w.focus), ...rows.slice(1)];
      }
      return rows;
    }
    reconcile() {
      const w = this.w();
      for (const [id, p] of this.players)
        if (!w.entries[id] || !w.slots.includes(id)) this.dispose(p);
      for (const row of w.slots
        .map((id, slot) => ({ id, slot }))
        .filter((r) => r.id)) {
        if (!this.players.has(row.id))
          this.makeTile(w.entries[row.id], row.slot);
      }
      const visible = new Set(this.visible().map((r) => r.id));
      for (const p of this.players.values()) {
        p.cell.hidden = !visible.has(p.id);
        p.cell.classList.toggle("is-selected", w.selected === p.id);
        p.cell.classList.toggle(
          "is-focus",
          (w.focus || w.slots.find(Boolean)) === p.id,
        );
        const e = w.entries[p.id],
          v = this.data.videos[e.media];
        (globalThis.AppI18n?.protect(p.name), p.name.textContent = v.title);
        p.name.title = v.title + " · " + v.site;
        p.pin.textContent = e.pinned ? "◆" : "◇";
        this.applyPlayer(p);
      }
      for (const n of this.canvas.querySelectorAll(".mt-free,.mt-empty"))
        n.remove();
      if (!Object.keys(w.entries).length) {
        const n = el(
          "div",
          { class: "mt-empty" },
          el("strong", { text: "Deine Videos. Dein Arbeitsbereich." }),
          el("p", {
            text: "Videos aus beliebigen Tube-Seiten sammeln, nebeneinander ansehen und später an derselben Stelle fortsetzen. Belegte Plätze werden beim Hinzufügen weiterer Videos nicht ersetzt.",
          }),
          button(
            "Videoauswahl öffnen",
            this.action(() => this.toggleSidebar(true)),
          ),
          button("Videolink hinzufügen", () => this.linkPanel()),
        );
        this.canvas.append(n);
      } else
        for (const row of this.visible().filter((r) => !r.id)) {
          const n = el(
            "div",
            { class: "mt-tile mt-free", "data-slot": row.slot },
            button("Platz " + (row.slot + 1) + " belegen", () =>
              this.pickSlot(row.slot),
            ),
          );
          this.installDrop(n, row.slot);
          this.canvas.append(n);
        }
      this.policy();
      this.pump();
    }
    makeTile(entry, slot) {
      const v = this.data.videos[entry.media],
        video = el("video", {
          playsInline: true,
          muted: true,
          preload: "metadata",
          crossOrigin: "anonymous",
          "aria-label": v.title,
        });
      const name = el("strong", {
          class: "mt-tile-title",
          text: v.title,
          draggable: true,
        "data-i18n-content":""}),
        state = el("span", { text: "Wartet" }),
        retry = button(
          "Erneut laden",
          this.action(() => this.retry(entry.id)),
          { hidden: true },
        ),
        picture = el(
          "div",
          { class: "mt-picture" },
          video,
          el("div", { class: "mt-state-overlay" }, state, retry),
        );
      const play = icon(
          "Pause / Fortsetzen",
          "▶",
          this.action(() => this.toggle(entry.id)),
        ),
        focus = icon(
          "Fokussieren",
          "◎",
          this.action(() => this.focus(entry.id)),
        ),
        audio = icon(
          "Ton dieses Videos",
          "♪",
          this.action(() => this.solo(entry.id)),
        ),
        menu = icon(
          "Videowerkzeuge",
          "⋯",
          this.action(() => this.select(entry.id, true)),
        ),
        pin = icon(
          "Platz anheften",
          "◇",
          this.action(() =>
            this.patch(entry.id, (e) => {
              e.pinned = !e.pinned;
            }),
          ),
        );
      const head = el(
          "div",
          { class: "mt-tile-head" },
          name,
          play,
          focus,
          audio,
          menu,
          pin,
        ),
        slider = el("input", {
          type: "range",
          min: 0,
          max: 1000,
          step: 1,
          value: 0,
          "aria-label": "Spielposition: " + v.title,
        }),
        clock = el("span", { class: "mt-clock", text: "0:00 / –" }),
        bar = el("div", { class: "mt-timebar" }, slider, clock);
      const cell = el(
        "article",
        {
          class: "mt-tile",
          "data-instance": entry.id,
          tabIndex: 0,
          "aria-label": v.title,
          onclick: () => {
            if (this.w().selected !== entry.id)
              this.action(() => this.select(entry.id, false))();
          },
        },
        picture,
        head,
        bar,
      );
      this.canvas.append(cell);
      const p = {
        id: entry.id,
        cell,
        video,
        name,
        state,
        retry,
        play,
        pin,
        slider,
        clock,
        slot,
        phase: "queued",
        closed: false,
        hls: null,
        controller: null,
        cleanup: [],
        frames: 0,
        dropped: 0,
        stalls: 0,
        attempt: 0,
        userPaused: false,
        started: performance.now(),
        generation: 0,
      };
      this.players.set(entry.id, p);
      const listen = (event, fn) => {
        video.addEventListener(event, fn);
        p.cleanup.push(() => video.removeEventListener(event, fn));
      };
      listen("loadedmetadata", () => {
        if (p.closed) return;
        const e = this.w().entries[p.id];
        p.duration = Number.isFinite(video.duration) ? video.duration : 0;
        if (p.duration) {
          const at = p.restoreTime ?? e.time;
          video.currentTime = Math.min(at, Math.max(0, p.duration - 0.05));
        }
        p.restoreTime = null;
        this.scheduleLayout();
        this.policy();
        this.readout(p);
      });
      listen("playing", () => {
        if (p.closed) return;
        p.phase = "playing";
        p.state.textContent = "Spielt";
        p.retry.hidden = true;
        p.firstFrame ??= performance.now() - p.started;
        this.status();
      });
      listen("pause", () => {
        if (p.closed || p.phase === "error" || p.phase === "ended") return;
        p.phase = p.ready ? "paused" : p.phase;
        p.state.textContent =
          p.phase === "paused" ? "Pausiert" : p.state.textContent;
        this.remember(p);
        this.readout(p);
      });
      listen("waiting", () => {
        if (!video.paused && !p.closed) {
          p.phase = "buffering";
          p.stalls++;
          p.state.textContent = "Puffert …";
        }
      });
      listen("timeupdate", () => {
        if (p.closed) return;
        const loop = this.w().entries[p.id]?.loop;
        if (loop?.enabled && loop.b > loop.a && video.currentTime >= loop.b)
          video.currentTime = loop.a;
        this.remember(p);
        this.readout(p);
      });
      listen("ended", () => this.action(() => this.ended(p))());
      listen("error", () => {
        if (!p.closed && !p.hls && p.ready)
          this.failed(p, "Die Videodatei konnte nicht gelesen werden.");
      });
      slider.addEventListener("input", () => {
        const t = (Number(slider.value) / 1000) * (video.duration || 0);
        clock.textContent = D.clock(t) + " / " + D.clock(video.duration);
      });
      slider.addEventListener("change", () =>
        this.seek(p.id, (Number(slider.value) / 1000) * (video.duration || 0)),
      );
      name.addEventListener("dragstart", (e) => {
        e.dataTransfer.setData("application/x-multitube-instance", entry.id);
      });
      this.installDrop(cell, () => this.w().slots.indexOf(entry.id));
      let drag = null;
      picture.addEventListener("pointerdown", (e) => {
        if (this.w().entries[p.id].image.zoom <= 100 || e.button !== 0) return;
        drag = {
          x: e.clientX,
          y: e.clientY,
          image: D.clone(this.w().entries[p.id].image),
        };
        picture.setPointerCapture(e.pointerId);
      });
      picture.addEventListener("pointermove", (e) => {
        if (!drag) return;
        const im = {
          ...drag.image,
          x: drag.image.x + e.clientX - drag.x,
          y: drag.image.y + e.clientY - drag.y,
        };
        p.draftImage = im;
        this.applyPlayer(p);
      });
      picture.addEventListener("pointerup", () => {
        if (!drag) return;
        drag = null;
        const im = p.draftImage;
        p.draftImage = null;
        this.action(() =>
          this.patch(p.id, (e) => {
            e.image = im;
          }),
        )();
      });
      picture.addEventListener(
        "wheel",
        (e) => {
          if (!e.ctrlKey && !e.metaKey) return;
          e.preventDefault();
          const im = p.draftImage || this.w().entries[p.id].image;
          p.draftImage = {
            ...im,
            zoom: D.clamp(im.zoom + (e.deltaY < 0 ? 15 : -15), 50, 1000),
          };
          this.applyPlayer(p);
          clearTimeout(p.imageTimer);
          p.imageTimer = setTimeout(() => {
            const image = p.draftImage;
            p.draftImage = null;
            this.action(() =>
              this.patch(p.id, (e) => {
                e.image = image;
              }),
            )();
          }, 150);
        },
        { passive: false },
      );
      picture.addEventListener("dblclick", () =>
        this.action(() =>
          this.patch(p.id, (e) => {
            e.image.zoom = 100;
            e.image.x = 0;
            e.image.y = 0;
          }),
        )(),
      );
      if (video.requestVideoFrameCallback) {
        const frame = (now, m) => {
          if (p.closed) return;
          p.frames++;
          p.presented = m.presentedFrames;
          p.frameAt = now;
          p.frameCallback = video.requestVideoFrameCallback(frame);
        };
        p.frameCallback = video.requestVideoFrameCallback(frame);
      }
      this.readout(p);
      return p;
    }
    installDrop(node, slot) {
      node.addEventListener("dragover", (e) => e.preventDefault());
      node.addEventListener(
        "drop",
        this.action(async (event) => {
          event.preventDefault();
          const target = typeof slot === "function" ? slot() : slot,
            id = event.dataTransfer.getData("application/x-multitube-instance"),
            raw = event.dataTransfer.getData("application/x-multitube-video");
          if (id) await this.change((s, w) => D.place(w, id, target));
          else if (raw)
            await this.addRows([JSON.parse(raw)], false, false, target);
        }),
      );
    }
    permitted() {
      const w = this.w(),
        visible = this.visible().filter((r) => r.id),
        focus = w.focus || visible[0]?.id;
      visible.sort((a, b) => (b.id === focus) - (a.id === focus));
      let limit = w.settings.activeLimit;
      if (w.settings.performance === "economy") limit = Math.min(limit, 4);
      if (w.settings.performance === "balanced" && this.adaptiveLimit)
        limit = Math.min(limit, this.adaptiveLimit);
      return new Set(visible.slice(0, limit).map((r) => r.id));
    }
    pump() {
      if (!this.owner || !this.active) return;
      const allowed = this.permitted();
      for (const p of this.players.values()) {
        if (this.pending >= 3) break;
        if (allowed.has(p.id) && p.phase === "queued" && !p.cell.hidden) {
          this.pending++;
          this.connect(p, !!p.fresh).finally(() => {
            this.pending = Math.max(0, this.pending - 1);
            this.pump();
          });
        }
      }
    }
    async connect(p, fresh = false) {
      const generation = ++p.generation,
        epoch = this.epoch;
      const valid = () =>
        !p.closed &&
        p.generation === generation &&
        epoch === this.epoch &&
        this.owner &&
        this.active;
      p.phase = "loading";
      p.waitingSince=null;
      p.fresh = false;
      p.state.textContent = "Quelle wird geladen …";
      p.retry.hidden = true;
      p.controller = new AbortController();
      p.requestId = D.id();
      try {
        const e = this.w().entries[p.id],
          v = this.data.videos[e.media],
          result = await this.ctx.resolve(
            v.query,
            p.requestId,
            p.controller.signal,
            fresh,
          );
        if (!valid()) return;
        if (!result.ok || !result.resolved?.path)
          throw Error(result.error || "Keine Videoquelle.");
        p.resolved = result.resolved;
        p.sources = (
          p.resolved.sources?.length
            ? p.resolved.sources
            : [{ label: "Original", path: p.resolved.path }]
        ).filter((s) => typeof s.path === "string" && /^https?:/i.test(s.path));
        if (!p.sources.length) throw Error("Keine unterstützte Videoquelle.");
        if (!p.measurement) p.measurement = this.ctx.track?.(p.video, v, {...v.facts,...p.resolved.facts});
        else p.measurement.update({facts:p.resolved.facts});
        if (!p.profileRecorded) {
          p.profileRecorded = true;
          this.ctx.record?.({...v,facts:{...v.facts,...p.resolved.facts}}, p.measurement?.data.id).catch(() => {
            this.notice("Der Videoaufruf konnte nicht im Tube-Profil gespeichert werden.", true);
          });
        }
        p.sourceIndex = this.sourceIndex(p);
        await this.attach(p, p.sources[p.sourceIndex], valid);
        if (!valid()) return;
        if (!p.hls) {
          p.ready = true;
          p.phase = "paused";
          p.state.textContent = this.restorePaused.has(p.id)
            ? "Gespeicherte Position · ▶ fortsetzen"
            : "Bereit";
        }
        this.applyPlayer(p);
        this.policy();
      } catch (e) {
        if (!valid() || e.name === "AbortError") return;
        this.failed(p, e.message);
      } finally {
        if (valid()) {
          p.controller = null;
          this.status();
        }
      }
    }
    sourceIndex(p) {
      const e = this.w().entries[p.id],
        cap = this.qualityCap(e),
        rows = p.sources
          .map((r, i) => ({
            i,
            h: Number((r.label || "").match(/\d{3,4}/)?.[0]) || 0,
          }))
          .sort((a, b) => a.h - b.h);
      return cap
        ? (rows.filter((r) => r.h && r.h <= cap).at(-1) || rows[0]).i
        : rows.at(-1).i;
    }
    qualityCap(e) {
      const w = this.w(),
        caps = [e.quality, w.settings.quality];
      if (w.settings.performance === "economy") caps.push(480);
      if (w.settings.performance === "balanced" && this.adaptiveCap)
        caps.push(this.adaptiveCap);
      return Math.min(...caps.filter((c) => c > 0), Infinity) === Infinity
        ? 0
        : Math.min(...caps.filter((c) => c > 0));
    }
    async attach(p, file, valid) {
      p.hls?.destroy();
      p.hls = null;
      p.ready = false;
      p.manifestReady = false;
      p.loadingStopped = false;
      const url = this.ctx.proxy(file.path, p.slot),
        isHls =
          /\.m3u8(?:[?&#]|$)/i.test(file.path) ||
          /mpegurl/i.test(p.resolved.mime || "");
      if (isHls && !root.Hls) {
        await Promise.race([
          this.ctx.ensureHls(),
          new Promise((resolve) => setTimeout(resolve, 10000)),
        ]);
        if (!valid()) return;
      }
      if (isHls && root.Hls?.isSupported()) {
        p.qualityChoice = null;
        const hls = new root.Hls({
          maxBufferLength: 18,
          maxMaxBufferLength: 35,
          backBufferLength: 6,
          manifestLoadingMaxRetry: 1,
          fragLoadingMaxRetry: 2,
        });
        p.hls = hls;
        hls.on(root.Hls.Events.MANIFEST_PARSED, () => {
          if (!valid() || p.hls !== hls) return;
          p.ready = true;
          p.manifestReady = true;
          p.phase = "paused";
          this.applyQuality(p);
          this.policy();
        });
        hls.on(root.Hls.Events.ERROR, (_, data) => {
          if (valid() && p.hls === hls && data.fatal)
            this.failed(
              p,
              "Die HLS-Quelle wurde unterbrochen. „Erneut laden“ erhält die Spielposition.",
            );
        });
        hls.loadSource(url);
        hls.attachMedia(p.video);
      } else {
        if (isHls && !p.video.canPlayType("application/vnd.apple.mpegurl"))
          throw Error(
            "HLS-Wiedergabe ist derzeit nicht verfügbar. Bitte die Verbindung prüfen und erneut laden.",
          );
        p.video.src = url;
        p.video.load();
      }
    }
    applyQuality(p) {
      if (!p.ready) return;
      if (p.hls) {
        const level = D.qualityIndex(
          p.hls.levels || [],
          this.qualityCap(this.w().entries[p.id]),
        );
        if (p.qualityChoice !== level) {
          p.qualityChoice = level;
          p.hls.loadLevel = level;
        }
        return;
      }
      if (!p.sources) return;
      const next = this.sourceIndex(p);
      if (next === p.sourceIndex) return;
      p.sourceIndex = next;
      p.restoreTime = p.video.currentTime || this.w().entries[p.id].time;
      p.video.src = this.ctx.proxy(p.sources[next].path, p.slot);
      p.video.load();
    }
    applyPlayer(p) {
      const e = this.w().entries[p.id];
      if (!e) return;
      const w = this.w(),
        im = p.draftImage || e.image;
      p.video.style.objectFit = w.fit;
      p.video.style.transform = `translate(${im.x}px,${im.y}px) rotate(${im.rotate}deg) scale(${(im.zoom / 100) * (im.flip ? -1 : 1)},${im.zoom / 100})`;
      p.video.style.filter = `brightness(${im.brightness}%) contrast(${im.contrast}%) saturate(${im.saturation}%)`;
      p.video.playbackRate = e.rate;
      p.video.volume = D.clamp(w.settings.master * e.volume, 0, 1);
      const focused = w.focus || w.slots.find(Boolean);
      p.video.muted =
        !this.userAudio ||
        w.settings.muteAll ||
        e.muted ||
        (w.settings.audio === "focus" && p.id !== focused) ||
        (w.settings.audio === "solo" && p.id !== w.settings.solo);
      this.applyQuality(p);
      p.play.textContent = p.video.paused ? "▶" : "Ⅱ";
    }
    policy() {
      if (!this.active) return;
      const w = this.w(),
        allowed = this.permitted();
      for (const p of this.players.values()) {
        const e = w.entries[p.id];
        if (!e) continue;
        const hidden =
            document.hidden &&
            (w.settings.background === "pause" ||
              (w.settings.background === "audio" && p.video.muted)),
          pause =
            !this.owner ||
            !allowed.has(p.id) ||
            p.cell.hidden ||
            e.paused ||
            e.ended ||
            this.restorePaused.has(p.id) ||
            hidden;
        p.policyPaused = pause;
        if (!pause && p.phase === "remote") p.phase = "queued";
        if (pause) {
          if (!p.video.paused) p.video.pause();
          if (p.hls && p.manifestReady && !p.loadingStopped) {
            p.hls.stopLoad();
            p.loadingStopped = true;
          }
          if (!this.owner) {
            p.state.textContent = "Wiedergabe im anderen Fenster";
            p.phase = "remote";
          }
        } else if (
          p.ready &&
          p.video.paused &&
          !["error", "ended", "blocked"].includes(p.phase)
        ) {
          if (p.loadingStopped) {
            p.hls?.startLoad(p.video.currentTime);
            p.loadingStopped = false;
          }
          if (!p.playPromise) {
            const generation=p.generation,attempt=p.video.play();
            p.playPromise = attempt;
            attempt
              ?.catch(() => {
                if (!p.closed && p.generation===generation) {
                  p.phase = "blocked";
                  p.state.textContent = "▶ zum Starten anklicken";
                }
              })
              .finally(() => {
                if(p.playPromise===attempt)p.playPromise = null;
              });
          }
        }
      }
      this.status();
    }
    failed(p, message) {
      if (p.closed) return;
      this.remember(p);
      p.generation++;p.controller?.abort();p.ready=false;p.waitingSince=null;
      p.phase = "error";
      p.state.textContent = message;
      p.retry.hidden = false;
      p.hls?.destroy();p.hls=null;
      p.video.pause();
      this.status();
    }
    async retry(id) {
      const p = this.players.get(id);
      if (!p) return;
      if (!this.owner)
        throw Error(
          "Die Wiedergabe läuft in einem anderen Fenster. Bitte zuerst übernehmen.",
        );
      this.remember(p);
      p.restoreTime = p.video.currentTime || this.w().entries[id].time;
      p.controller?.abort();
      p.generation++;
      p.hls?.destroy();
      p.hls = null;
      p.video.pause();
      p.ready = false;
      p.fresh = true;
      p.phase = "queued";
      this.restorePaused.delete(id);
      this.pump();
    }
    async patch(id, fn) {
      await this.change((s, w) => {
        if (w.entries[id]) fn(w.entries[id], w, s);
      });
    }
    async select(id, details = false) {
      await this.change((s, w) => {
        w.selected = id;
        if (details) w.details = true;
      });
    }
    async focus(id) {
      this.userAudio = true;
      await this.change((s, w) => {
        w.focus = id;
        w.selected = id;
        w.layout = w.layout === "compare" ? "compare" : "focus";
      });
    }
    async solo(id) {
      this.userAudio = true;
      await this.change((s, w) => {
        w.settings.audio = "solo";
        w.settings.solo = id;
        w.settings.muteAll = false;
        w.entries[id].muted = false;
      });
    }
    async toggle(id) {
      if (!this.owner)
        throw Error("Bitte „Wiedergabe hier übernehmen“ wählen.");
      const p = this.players.get(id);
      this.userAudio = true;
      const play = this.restorePaused.has(id) || p?.video.paused;
      if (p?.phase === "blocked") p.phase = "paused";
      this.restorePaused.delete(id);
      await this.patch(id, (e) => {
        e.paused = !play;
        if (play && e.ended) {
          e.time = 0;
          if (p?.ready) p.video.currentTime = 0;
        }
        e.ended = false;
      });
      if (play && p?.phase === "error") await this.retry(id);
      this.policy();
    }
    async playAll() {
      if (!this.owner) await this.takeOver();
      this.userAudio = true;
      this.restorePaused.clear();
      this.batchPaused = null;
      for (const p of this.players.values())
        if (p.phase === "blocked" || p.phase === "ended") p.phase = "paused";
      await this.change((s, w) => {
        for (const row of this.visible()) {
          const e = w.entries[row.id];
          if (e) {
            e.paused = false;
            if (e.ended) {
              e.time = 0;
              e.ended = false;
              const p = this.players.get(e.id);
              if (p?.ready) p.video.currentTime = 0;
            }
          }
        }
      });
      this.policy();
    }
    async pauseAll() {
      if (this.batchPaused) {
        const ids = this.batchPaused;
        this.batchPaused = null;
        for (const k of ids) this.restorePaused.delete(k);
        await this.change((s, w) => {
          for (const k of ids) if (w.entries[k]) w.entries[k].paused = false;
        });
      } else {
        const ids = [...this.players.values()]
          .filter((p) => !p.video.paused)
          .map((p) => p.id);
        this.batchPaused = ids;
        await this.change((s, w) => {
          for (const k of ids) if (w.entries[k]) w.entries[k].paused = true;
        });
      }
      this.policy();
    }
    seek(id, time, propagate = true) {
      const p = this.players.get(id);
      if (!p || !p.ready) return;
      const max = Number.isFinite(p.video.duration)
        ? Math.max(0, p.video.duration - 0.02)
        : 604800;
      p.video.currentTime = D.clamp(time, 0, max);
      this.remember(p);
      this.readout(p);
      if (propagate && this.w().settings.linked) {
        const offsets = this.w().settings.offsets || {},
          base = p.video.currentTime - (offsets[id] || 0);
        for (const other of this.players.values())
          if (other.id !== id && !other.cell.hidden)
            this.seek(other.id, base + (offsets[other.id] || 0), false);
      }
    }
    async ended(p) {
      if (p.closed || !this.owner || this.w().slots.indexOf(p.id) < 0) return;
      const w = this.w(),
        e = w.entries[p.id];
      if (e.loop.enabled) return;
      if (w.settings.end === "repeat") {
        p.video.currentTime = 0;
        p.video.play().catch(() => {});
        return;
      }
      p.phase = "ended";
      p.state.textContent = "Beendet";
      await this.patch(p.id, (x) => {
        x.ended = true;
        x.paused = true;
        x.time = p.video.duration || x.time;
      });
      if (w.settings.end === "next" && !e.pinned) await this.next(p.id, false);
    }
    async next(id, force = true) {
      await this.flushProgress();
      let result;
      await this.change((s, w) => {
        const slot = w.slots.indexOf(id);
        result = D.advance(w, slot, id, force);
      });
      if (!result)
        this.notice(
          "Kein nächstes Video verfügbar oder der Platz ist angeheftet.",
        );
    }
    remember(p) {
      if (!this.owner || !p.ready) return;
      this.progress.set(p.id, {
        time: p.video.currentTime || 0,
        duration: Number.isFinite(p.video.duration) ? p.video.duration : 0,
        updated: Date.now(),
      });
    }
    async flushProgress() {
      if (!this.progress.size || !this.store || !this.owner) return;
      const data = Object.fromEntries(this.progress);
      this.progress.clear();
      const workspace = this.workspaceId;
      try {
        await this.store.progress(workspace, owner, data);
      } catch (e) {
        for (const [k, v] of Object.entries(data))
          if (!this.progress.has(k)) this.progress.set(k, v);
        this.notice("Spielposition noch nicht gespeichert: " + e.message, true);
      }
    }
    readout(p) {
      const video = p.video,
        t = Number.isFinite(video.currentTime) ? video.currentTime : 0,
        d = Number.isFinite(video.duration)
          ? video.duration
          : this.w().entries[p.id]?.duration || 0;
      p.clock.textContent = D.clock(t) + " / " + (d ? D.clock(d) : "–");
      if (document.activeElement !== p.slider)
        p.slider.value = String(d ? (t / d) * 1000 : 0);
      p.slider.disabled = !p.ready || !this.owner;
      p.play.textContent = video.paused ? "▶" : "Ⅱ";
    }
    dispose(p, remember = true) {
      if (p.closed) return;
      p.measurement?.stop();
      if (remember) this.remember(p);
      p.closed = true;
      p.generation++;
      p.controller?.abort();
      if (p.requestId) this.ctx.cancel?.(p.requestId);
      clearTimeout(p.imageTimer);
      if (p.frameCallback != null)
        p.video.cancelVideoFrameCallback?.(p.frameCallback);
      for (const f of p.cleanup) f();
      p.hls?.destroy();
      p.hls = null;
      p.video.pause();
      p.video.removeAttribute("src");
      p.video.load();
      p.cell.remove();
      this.players.delete(p.id);
    }
    destroyAll() {
      for (const p of [...this.players.values()]) this.dispose(p, false);
      this.progress.clear();
    }
    async remove(id, toQueue = false) {
      const w = this.w(),
        old = D.clone(w.entries[id]),
        slot = w.slots.indexOf(id),
        queue = w.queue.indexOf(id);
      await this.flushProgress();
      await this.change((s, w) => D.remove(w, id, toQueue));
      if (!toQueue && old) {
        this.undoRemove = { workspace: w.id, entry: old, slot, queue };
        this.notice(
          "Video aus dem Arbeitsbereich entfernt. „Mehr → Entfernen rückgängig“ stellt es wieder her.",
        );
      }
    }
    async undo() {
      const undo = this.undoRemove;
      if (!undo || undo.workspace !== this.workspaceId)
        throw Error("Hier gibt es nichts rückgängig zu machen.");
      await this.change((s, w) => {
        if (w.entries[undo.entry.id]) return;
        w.entries[undo.entry.id] = undo.entry;
        if (undo.slot >= 0 && !w.slots[undo.slot])
          w.slots[undo.slot] = undo.entry.id;
        else w.queue.splice(Math.max(0, undo.queue), 0, undo.entry.id);
      });
      this.undoRemove = null;
    }
    status() {
      if (!this.footer || !this.data) return;
      const w = this.w(),
        counts = {
          playing: 0,
          paused: 0,
          loading: 0,
          error: 0,
          ended: 0,
          waiting: 0,
        };
      for (const p of this.players.values()) {
        if (p.cell.hidden) continue;
        if (p.phase === "playing" && !p.video.paused) counts.playing++;
        else if (p.phase === "loading") counts.loading++;
        else if (p.phase === "error") counts.error++;
        else if (p.phase === "ended") counts.ended++;
        else if (p.phase === "queued") counts.waiting++;
        else counts.paused++;
      }
      const visibleIds = new Set(this.visible().map((r) => r.id));
      const hidden = w.slots.filter((k) => k && !visibleIds.has(k)).length;
      if (!this.footerSummary?.isConnected) {
        this.footerSummary = el("span");
        this.takeoverButton = button(
          "Wiedergabe hier übernehmen",
          this.action(() => this.takeOver()),
        );
        this.performanceSummary = el("span");
        this.footer.replaceChildren(
          this.footerSummary,
          this.takeoverButton,
          this.performanceSummary,
        );
      }
      this.footerSummary.textContent = `${counts.playing} spielen · ${counts.paused} pausiert · ${counts.ended} beendet · ${counts.loading} laden · ${counts.waiting} warten · ${counts.error} Fehler · ${w.queue.length} vorgemerkt${hidden ? " · " + hidden + " Plätze auf weiteren Seiten / verborgen" : ""}`;
      this.takeoverButton.hidden = this.owner;
      this.performanceSummary.textContent =
        w.settings.performance === "balanced" && this.adaptiveCap
          ? "Automatische Entlastung: " + this.adaptiveCap + "p"
          : "";
    }
    scheduleLayout() {
      if (this.layoutFrame) return;
      this.layoutFrame = requestAnimationFrame(() => {
        this.layoutFrame = 0;
        this.layout();
      });
    }
    layout() {
      if (!this.active || !this.canvas) return;
      const host = this.panel.closest("#view-multi");
      if (host && !document.fullscreenElement) {
        const height = Math.max(
          300,
          innerHeight -
            Math.max(0, host.getBoundingClientRect().top + scrollY) -
            12,
        );
        if (host.style.height !== height + "px")
          host.style.height = height + "px";
      }
      const w = this.w(),
        rows = this.visible(),
        width = this.stage.clientWidth,
        height = this.stage.clientHeight;
      if (!width || !height || !rows.length) return;
      const ratios = rows.map((r) => {
        const p = this.players.get(r.id);
        return p?.video.videoWidth && p.video.videoHeight
          ? p.video.videoWidth / p.video.videoHeight
          : 16 / 9;
      });
      let boxes;
      if (w.layout === "focus" && rows.some((r) => r.id)) {
        const f = Math.max(
            0,
            rows.findIndex((r) => r.id === w.focus),
          ),
          ordered = [rows[f], ...rows.filter((r, i) => i !== f)],
          rr = [ratios[f], ...ratios.filter((r, i) => i !== f)],
          right = width > 780,
          mainWidth =
            ordered.length > 1 ? (right ? width * 0.77 : width) : width,
          mainHeight =
            ordered.length > 1 ? (right ? height : height * 0.7) : height;
        boxes = new Map([
          [
            ordered[0].id || "slot:" + ordered[0].slot,
            { x: 0, y: 0, width: mainWidth, height: mainHeight },
          ],
        ]);
        if (ordered.length > 1) {
          const sideW = right ? width - mainWidth - 8 : width,
            sideH = right ? height : height - mainHeight - 8;
          const grid = D.layout(ordered.length - 1, sideW, sideH, 16 / 9);
          ordered.slice(1).forEach((r, i) =>
            boxes.set(r.id || "slot:" + r.slot, {
              x:
                (right ? mainWidth + 8 : 0) +
                (i % grid.columns) * (sideW / grid.columns),
              y:
                (right ? 0 : mainHeight + 8) +
                Math.floor(i / grid.columns) * (sideH / grid.rows),
              width: sideW / grid.columns - 5,
              height: sideH / grid.rows - 5,
            }),
          );
        }
      } else {
        let packed = root.LiveCamDomain?.mosaicLayout?.(
          ratios,
          width,
          Math.max(100, height),
          8,
        );
        if (
          packed &&
          packed.rects.every(
            (r) =>
              r.y + r.height <= height + 1 &&
              r.width >= (w.settings.fitAll ? 90 : 190) &&
              r.height >= 100,
          )
        )
          boxes = new Map(
            rows.map((r, i) => [r.id || "slot:" + r.slot, packed.rects[i]]),
          );
        else {
          const g = D.layout(
            rows.length,
            width,
            height,
            ratios.reduce((a, b) => a + b, 0) / ratios.length,
          );
          boxes = new Map(
            rows.map((r, i) => [
              r.id || "slot:" + r.slot,
              {
                x: (i % g.columns) * (width / g.columns),
                y: Math.floor(i / g.columns) * (height / g.rows),
                width: width / g.columns - 5,
                height: height / g.rows - 5,
              },
            ]),
          );
        }
      }
      for (const row of rows) {
        const node = row.id
            ? this.players.get(row.id)?.cell
            : this.canvas.querySelector('[data-slot="' + row.slot + '"]'),
          b = boxes.get(row.id || "slot:" + row.slot);
        if (node && b)
          Object.assign(node.style, {
            left: b.x + "px",
            top: b.y + "px",
            width: Math.max(1, b.width) + "px",
            height: Math.max(1, b.height) + "px",
          });
      }
    }
    checkStall(p, now) {
      if(p.closed||p.policyPaused||["error","ended","blocked","queued","remote"].includes(p.phase)||p.video.paused&&p.phase!=="loading") {p.waitingSince=null;return;}
      const current=Number(p.video.currentTime)||0;
      if(p.waitingSince==null||current!==p.progressTime){p.waitingSince=now;p.progressTime=current;return;}
      if(now-p.waitingSince>=30000)this.failed(p,"Die Quelle liefert seit 30 Sekunden kein neues Bild. Erneut laden versucht eine frische Adresse; die Spielposition bleibt erhalten.");
    }
    tick() {
      if (!this.active) return;
      announce();
      this.ticks = (this.ticks || 0) + 1;
      for (const p of this.players.values()) {this.checkStall(p,performance.now());this.readout(p);}
      if (this.ticks % 3 === 0) {
        this.flushProgress();
        if (this.owner)
          this.store
            .claim(this.workspaceId, owner)
            .then((ok) => {
              if (this.owner && !ok) {
                this.owner = false;
                this.epoch++;
                this.destroyAll();
                this.notice(
                  "Wiedergabe wurde in einem anderen Fenster übernommen.",
                );
                this.render();
              } else if (this.owner) {
                this.policy();
              }
            })
            .catch((e) => this.notice(e.message, true));
      }
      if (this.ticks % 5 === 0) this.measure();
      this.status();
      if (this.w().details && this.ticks % 2 === 0) this.updateDiagnostics();
    }
    measure() {
      if (this.w().settings.performance !== "balanced") return;
      let high = false;
      for (const p of this.players.values()) {
        const q = p.video.getVideoPlaybackQuality?.();
        if (!q) continue;
        const total = q.totalVideoFrames - (p.sampleFrames || 0),
          dropped = q.droppedVideoFrames - (p.sampleDropped || 0);
        if (total > 20 && dropped / total > 0.12) high = true;
        p.sampleFrames = q.totalVideoFrames;
        p.sampleDropped = q.droppedVideoFrames;
      }
      this.pressure = high
        ? (this.pressure || 0) + 1
        : Math.max(0, (this.pressure || 0) - 1);
      if (this.pressure >= 2) {
        this.adaptiveCap = 480;
        this.adaptiveLimit = 4;
      } else if (this.pressure === 0) {
        this.adaptiveCap = 0;
        this.adaptiveLimit = 0;
      }
      for (const p of this.players.values()) this.applyQuality(p);
      this.policy();
    }
    async pickSlot(slot) {
      const { dialog, body } = this.dialog("Video für Platz " + (slot + 1)),
        search = el("input", {
          type: "search",
          "aria-label": "Video für Platz suchen",
          placeholder: "Titel, Anbieter oder Tags suchen …",
        }),
        list = el("div", { class: "mt-picker-list" });
      let limit = 100;
      const draw = () => {
        const q = search.value.trim().toLocaleLowerCase(),
          rows = this.libraryRows().filter((r) =>
            [r.title, r.site, ...(this.data.personal[r.key]?.tags || [])]
              .join(" ")
              .toLocaleLowerCase()
              .includes(q),
          );
        list.replaceChildren();
        for (const row of rows.slice(0, limit))
          list.append(
            button(
              row.title + " · " + row.site,
              this.action(async () => {
                await this.addRows([row], false, true, slot);
                dialog.close();
              }),
            ),
          );
        if (rows.length > limit)
          list.append(
            button("Weitere 100 anzeigen", () => {
              limit += 100;
              draw();
            }),
          );
        if (!rows.length)
          list.append(
            el("p", {
              text: "Keine passenden Videos. Videos zuerst über eine Seitenliste oder den Videolink hinzufügen.",
            }),
          );
      };
      search.oninput = () => {
        limit = 100;
        draw();
      };
      body.append(search, list);
      draw();
      search.focus();
    }
    dialog(title) {
      const body = el("div", { class: "mt-dialog-body" }),
        d = el(
          "dialog",
          { class: "mt-dialog" },
          el(
            "header",
            {},
            el("h2", { text: title }),
            button("Schließen", () => d.close()),
          ),
          body,
        );
      this.dialogs.add(d);
      document.body.append(d);
      d.addEventListener("close", () => {
        this.dialogs.delete(d);
        d.remove();
      });
      d.showModal();
      return { dialog: d, body };
    }
    async linkPanel() {
      const { dialog, body } = this.dialog("Videolink hinzufügen"),
        url = el("input", {
          type: "url",
          placeholder: "https://…/video/…",
          "aria-label": "Videoseiten-Adresse",
        }),
        note = el("p", { class: "mt-progress" });
      body.append(
        el("p", {
          text: "Die reguläre Videoseite einer unterstützten Tube-Site einfügen. Kurzlebige Streamadressen werden nicht als dauerhafte Links gespeichert.",
        }),
        url,
        button("Prüfen und hinzufügen", async () => {
          try {
            note.textContent = "Anbieter wird erkannt …";
            const row = await this.ctx.link(url.value.trim());
            await this.addRows([row]);
            dialog.close();
          } catch (e) {
            note.textContent = e.message;
            note.classList.add("mt-error");
          }
        }),
        note,
      );
      url.focus();
    }
    renderDetails() {
      if (!this.w().details) return;
      const w = this.w(),
        e = w.entries[w.selected || w.focus],
        v = e && this.data.videos[e.media];
      if (!e) {
        this.details.replaceChildren(
          el("p", {
            text: "Ein Video auswählen, um Zeitmarken und Werkzeuge zu öffnen.",
          }),
        );
        return;
      }
      const p = this.data.personal[v.key] || {};
      if (!this.pendingPersonal.has(v.key)) {
        try {
          const draft = JSON.parse(
            localStorage.getItem("ah-multitube-note:" + v.key) || "null",
          );
          if (draft && typeof draft.notes === "string")
            this.pendingPersonal.set(v.key, draft);
        } catch {}
      }
      const sig = JSON.stringify([
        e.id,
        e.pinned,
        e.rate,
        e.quality,
        e.volume,
        e.muted,
        e.loop,
        e.image,
        p,
        this.owner,
        this.players.get(e.id)?.sources?.map((s) => s.label),
        this.players.get(e.id)?.hls?.levels?.map((l) => l.height),
      ]);
      if (sig === this.detailsSignature) return;
      if (
        this.details.contains(document.activeElement) &&
        document.activeElement.matches("input,textarea,select")
      )
        return;
      this.detailsSignature = sig;
      this.details.replaceChildren(
        el("h3", { text: v.title ,"data-i18n-content":""}),
        el("p", {
          class: "mt-progress",
          text: v.site + (v.uploader ? " · " + v.uploader : ""),
        }),
        el(
          "div",
          { class: "mt-row" },
          button(
            "✕ Details",
            this.action(() =>
              this.change((s, w) => {
                w.details = false;
              }),
            ),
          ),
          button(
            e.pinned ? "◆ Angeheftet" : "◇ Anheften",
            this.action(() =>
              this.patch(e.id, (x) => {
                x.pinned = !x.pinned;
              }),
            ),
          ),
        ),
      );
      const playback = el(
        "details",
        { open: true },
        el("summary", { text: "Wiedergabe" }),
      );
      const speed = select(
        "Geschwindigkeit",
        [
          [0.25, "0,25×"],
          [0.5, "0,5×"],
          [0.75, "0,75×"],
          [1, "1×"],
          [1.25, "1,25×"],
          [1.5, "1,5×"],
          [2, "2×"],
          [3, "3×"],
          [4, "4×"],
        ],
        (value) =>
          this.action(() =>
            this.patch(e.id, (x) => {
              x.rate = Number(value);
            }),
          )(),
      );
      speed.value = String(e.rate);
      const quality = select(
        "Qualität",
        [
          [0, "Automatisch / Original"],
          ...[
            ...new Set([
              ...(this.players.get(e.id)?.hls?.levels || []).map(
                (l) => l.height,
              ),
              ...(this.players.get(e.id)?.sources || []).map((s) =>
                Number((s.label || "").match(/\d{3,4}/)?.[0]),
              ),
              e.quality,
            ]),
          ]
            .filter((h) => h > 0)
            .sort((a, b) => a - b)
            .map((h) => [h, h + "p"]),
        ],
        (value) =>
          this.action(() =>
            this.patch(e.id, (x) => {
              x.quality = Number(value);
            }),
          )(),
      );
      quality.value = String(e.quality);
      playback.append(
        el(
          "div",
          { class: "mt-row" },
          button("−10 s", () =>
            this.seek(
              e.id,
              (this.players.get(e.id)?.video.currentTime || e.time) - 10,
            ),
          ),
          button("+10 s", () =>
            this.seek(
              e.id,
              (this.players.get(e.id)?.video.currentTime || e.time) + 10,
            ),
          ),
          button("Von vorn", () => this.seek(e.id, 0)),
          button(
            "Nächstes",
            this.action(() => this.next(e.id)),
          ),
        ),
        field("Geschwindigkeit", speed),
        field("Qualität", quality),
        field(
          "Lautstärke",
          el("input", {
            type: "range",
            min: 0,
            max: 1,
            step: 0.05,
            value: e.volume,
            "aria-label": "Videolautstärke",
            oninput: (event) => {
              const value = Number(event.target.value);
              this.userAudio = true;
              this.action(() =>
                this.patch(e.id, (x) => {
                  x.volume = value;
                }),
              )();
            },
          }),
        ),
        button(
          e.muted ? "Ton freigeben" : "Video stummschalten",
          this.action(() => {
            this.userAudio = true;
            return this.patch(e.id, (x) => {
              x.muted = !x.muted;
            });
          }),
        ),
        button(
          "Solo-Ton",
          this.action(() => this.solo(e.id)),
        ),
      );
      this.details.append(playback);
      const loop = el(
        "details",
        { open: true },
        el("summary", { text: "A–B-Schleife" }),
      );
      loop.append(
        el("p", {
          class: "mt-progress",
          text:
            "A: " +
            (e.loop.a == null ? "–" : D.clock(e.loop.a)) +
            " · B: " +
            (e.loop.b == null ? "–" : D.clock(e.loop.b)),
        }),
        el(
          "div",
          { class: "mt-row" },
          button(
            "A setzen",
            this.action(() =>
              this.patch(e.id, (x) => {
                x.loop.a = this.players.get(e.id)?.video.currentTime || 0;
                x.loop.enabled = false;
              }),
            ),
          ),
          button(
            "B setzen",
            this.action(() =>
              this.patch(e.id, (x) => {
                x.loop.b = this.players.get(e.id)?.video.currentTime || 0;
                x.loop.enabled = false;
              }),
            ),
          ),
          button(
            e.loop.enabled ? "Schleife aus" : "Schleife an",
            this.action(() =>
              this.patch(e.id, (x) => {
                if (
                  !(
                    Number.isFinite(x.loop.a) &&
                    Number.isFinite(x.loop.b) &&
                    x.loop.b > x.loop.a
                  )
                )
                  throw Error(
                    "Zuerst A und danach eine spätere Stelle B setzen.",
                  );
                x.loop.enabled = !x.loop.enabled;
              }),
            ),
          ),
          button(
            "Löschen",
            this.action(() =>
              this.patch(e.id, (x) => {
                x.loop = { a: null, b: null, enabled: false };
              }),
            ),
          ),
        ),
      );
      this.details.append(loop);
      const markers = el(
        "details",
        { open: true },
        el("summary", { text: "Zeitmarken" }),
      );
      markers.append(
        button("+ Aktuelle Stelle merken", () => this.markerPanel(e.id)),
      );
      for (const marker of [...(p.markers || [])].sort(
        (a, b) => a.time - b.time,
      ))
        markers.append(
          el(
            "div",
            { class: "mt-marker" },
            button(D.clock(marker.time) + " · " + marker.label, () =>
              this.seek(e.id, marker.time),
            ),
            icon(
              "Zeitmarke löschen",
              "×",
              this.action(() =>
                this.personal(v.key, (p) => {
                  p.markers = (p.markers || []).filter(
                    (m) => m.id !== marker.id,
                  );
                }),
              ),
            ),
          ),
        );
      this.details.append(markers);
      const organize = el(
          "details",
          {},
          el("summary", { text: "Merken, Notizen und Tags" }),
        ),
        notes = el("textarea", {
          "aria-label": "Videonotizen",
          value: this.pendingPersonal.get(v.key)?.notes ?? p.notes ?? "",
          placeholder: "Eigene Notizen …",
        }),
        saveState = el("small", {
          class: "mt-progress",
          text: "Notizen werden nach kurzer Pause gespeichert.",
        });
      notes.addEventListener("input", () =>
        this.schedulePersonal(
          v.key,
          { notes: notes.value },
          saveState,
          this.pendingPersonal.get(v.key)?.base ?? p.revision ?? 0,
        ),
      );
      const tags = input("Eigene Tags", (p.tags || []).join(", "), (value) =>
        this.action(() =>
          this.personal(v.key, (p) => {
            p.tags = value
              .split(",")
              .map((v) => v.trim())
              .filter(Boolean);
          }),
        )(),
      );
      organize.append(
        button(
          p.favorite ? "★ Favorit" : "☆ Als Favorit",
          this.action(() =>
            this.personal(v.key, (p) => {
              p.favorite = !p.favorite;
            }),
          ),
        ),
        field("Notizen", notes),
        saveState,
        field("Tags, durch Komma getrennt", tags),
        field(
          "Eigene Bewertung",
          select(
            "Eigene Bewertung",
            [
              [0, "Ohne Bewertung"],
              ...[1, 2, 3, 4, 5].map((v) => [v, "★".repeat(v)]),
            ],
            (value) =>
              this.action(() =>
                this.personal(v.key, (p) => {
                  p.rating = Number(value);
                }),
              )(),
          ),
        ),
      );
      organize.querySelector("select").value = String(p.rating || 0);
      if (this.pendingPersonal.has(v.key)) {
        organize.open = true;
        organize.append(
          el("p", {
            class: "mt-progress",
            text:
              "Wiederherstellbarer Notizentwurf. Bestätigter Text: " +
              (p.notes || "(leer)"),
          }),
          button(
            "Entwurf ausdrücklich übernehmen",
            this.action(async () => {
              clearTimeout(this.personalTimers.get(v.key));
              const notes = this.pendingPersonal.get(v.key)?.notes || "";
              await this.personalSaves.get(v.key);
              await this.personal(v.key, (p) => {
                p.notes = notes;
              });
              this.pendingPersonal.delete(v.key);
              localStorage.removeItem("ah-multitube-note:" + v.key);
              this.detailsSignature = "";
              this.renderDetails();
            }),
          ),
          button(
            "Bestätigten Text verwenden",
            this.action(async () => {
              clearTimeout(this.personalTimers.get(v.key));
              await this.personalSaves.get(v.key);
              this.pendingPersonal.delete(v.key);
              localStorage.removeItem("ah-multitube-note:" + v.key);
              this.detailsSignature = "";
              notes.blur();
              this.renderDetails();
            }),
          ),
        );
      }
      this.details.append(organize);
      const image = el(
        "details",
        {},
        el("summary", { text: "Bild und Ausschnitt" }),
      );
      for (const [key, label, min, max] of [
        ["zoom", "Zoom", 50, 1000],
        ["brightness", "Helligkeit", 25, 250],
        ["contrast", "Kontrast", 25, 250],
        ["saturation", "Sättigung", 0, 300],
      ])
        image.append(
          field(
            label,
            el("input", {
              type: "range",
              min,
              max,
              value: e.image[key],
              "aria-label": label,
              oninput: (event) => {
                const value = Number(event.target.value);
                const player = this.players.get(e.id);
                if (player) {
                  player.draftImage = { ...e.image, [key]: value };
                  this.applyPlayer(player);
                }
                clearTimeout(this.imageSave);
                this.imageSave = setTimeout(
                  () =>
                    this.action(() =>
                      this.patch(e.id, (x) => {
                        x.image[key] = value;
                        const player = this.players.get(e.id);
                        if (player) player.draftImage = null;
                      }),
                    )(),
                  180,
                );
              },
            }),
          ),
        );
      image.append(
        el(
          "div",
          { class: "mt-row" },
          button(
            "Drehen",
            this.action(() =>
              this.patch(e.id, (x) => {
                x.image.rotate = (x.image.rotate + 90) % 360;
              }),
            ),
          ),
          button(
            "Spiegeln",
            this.action(() =>
              this.patch(e.id, (x) => {
                x.image.flip = !x.image.flip;
              }),
            ),
          ),
          button(
            "Bild zurücksetzen",
            this.action(() =>
              this.patch(e.id, (x) => {
                x.image = D.instance("").image;
                const player = this.players.get(e.id);
                if (player) player.draftImage = null;
              }),
            ),
          ),
        ),
      );
      this.details.append(image);
      this.details.append(
        el(
          "div",
          { class: "mt-row" },
          button(
            "Zweite Ansicht",
            this.action(() => this.duplicate(e.id)),
          ),
          button(
            "Screenshot",
            this.action(() => this.screenshot(e.id)),
          ),
          button(
            "Vollbild",
            this.action(() => this.players.get(e.id)?.cell.requestFullscreen()),
          ),
          button(
            "Bild-in-Bild",
            this.action(async () => {
              const video = this.players.get(e.id)?.video;
              if (
                !document.pictureInPictureEnabled ||
                !video?.requestPictureInPicture
              )
                throw Error(
                  "Bild-in-Bild ist für dieses Video nicht verfügbar.",
                );
              await video.requestPictureInPicture();
            }),
          ),
          button("Download", () => this.ctx.download(v)),
          button("Originalseite", () =>
            root.open(v.url, "_blank", "noopener,noreferrer"),
          ),
          button("Video auf Platz ersetzen", () =>
            this.pickSlot(this.w().slots.indexOf(e.id)),
          ),
          button(
            "In Warteschlange",
            this.action(() => this.remove(e.id, true)),
          ),
          button(
            "Aus Arbeitsbereich entfernen",
            this.action(() => this.remove(e.id)),
          ),
        ),
      );
      this.diagnostics = el("p", { class: "mt-progress" });
      this.details.append(this.diagnostics);
      if (v.plot)
        this.details.append(
          el(
            "details",
            {},
            el("summary", { text: "Beschreibung" }),
            el("p", { text: v.plot }),
          ),
        );
      this.updateDiagnostics();
    }
    updateDiagnostics() {
      const p = this.players.get(this.w().selected || this.w().focus);
      if (!p || !this.diagnostics) return;
      const v = p.video,
        q = v.getVideoPlaybackQuality?.(),
        buffer = v.buffered.length
          ? Math.max(0, v.buffered.end(v.buffered.length - 1) - v.currentTime)
          : 0;
      this.diagnostics.textContent = `${v.videoWidth || "–"} × ${v.videoHeight || "–"} · Puffer ${buffer.toFixed(1)} s · präsentierte Frames ${p.frames || "–"} · verworfen ${q?.droppedVideoFrames ?? "unbekannt"} · Unterbrechungen ${p.stalls}`;
    }
    async duplicate(id) {
      const w = this.w(),
        e = w.entries[id],
        v = this.data.videos[e.media],
        free = w.slots.indexOf(null);
      const use = async (slot) => {
        await this.change((s, w) => {
          const [copy] = D.add(s, w.id, [v], { duplicate: true, target: slot });
          w.capacity = Math.max(w.capacity, slot + 1);
          w.focus = id;
          w.selected = copy;
          w.layout = "compare";
        });
      };
      if (free >= 0) return use(free);
      const { dialog, body } = this.dialog("Platz für die Vergleichsansicht");
      body.append(
        el("p", {
          text: "Alle 20 Plätze sind belegt. Das ersetzte Video bleibt in der Warteschlange.",
        }),
      );
      w.slots.forEach((key, slot) =>
        body.append(
          button(
            "Platz " + (slot + 1) + " ersetzen",
            this.action(async () => {
              await use(slot);
              dialog.close();
            }),
          ),
        ),
      );
    }
    async personal(key, fn) {
      await this.change((s) => {
        const p = (s.personal[key] ||= {
          notes: "",
          tags: [],
          markers: [],
          favorite: false,
          rating: 0,
        });
        fn(p);
        p.revision = (p.revision || 0) + 1;
      });
    }
    loadFilter() {
      const f = this.w().filter || {};
      this.search = f.search || "";
      this.source = f.source || "all";
      this.sort = f.sort || "title";
      this.selection.clear();
      this.sidebarSignature = "";
      if (this.searchInput) this.searchInput.value = this.search;
      if (this.sourceSelect) this.sourceSelect.value = this.source;
      if (this.sortSelect) this.sortSelect.value = this.sort;
    }
    saveFilter() {
      clearTimeout(this.filterTimer);
      const workspace = this.workspaceId,
        filter = { search: this.search, source: this.source, sort: this.sort };
      this.filterTimer = setTimeout(
        () =>
          this.store
            .mutate((s) => {
              const w = s.workspaces.find((w) => w.id === workspace);
              if (w) w.filter = filter;
              return s;
            })
            .catch((e) => this.notice(e.message, true)),
        200,
      );
    }
    schedulePersonal(key, patch, node, shownRevision) {
      const previous = this.pendingPersonal.get(key),
        base = previous?.base ?? shownRevision;
      this.pendingPersonal.set(key, { ...previous, ...patch, base });
      try {
        localStorage.setItem(
          "ah-multitube-note:" + key,
          JSON.stringify(this.pendingPersonal.get(key)),
        );
      } catch {
        this.notice(
          "Der Notizentwurf kann derzeit nicht zusätzlich abgesichert werden.",
          true,
        );
      }
      clearTimeout(this.personalTimers.get(key));
      node.textContent = "Ungespeicherter Entwurf …";
      this.personalTimers.set(
        key,
        setTimeout(() => this.savePersonalDraft(key, node), 500),
      );
    }
    savePersonalDraft(key, node) {
      const prior = this.personalSaves.get(key) || Promise.resolve();
      const saving = prior.then(async () => {
        const draft = this.pendingPersonal.get(key);
        if (!draft) return;
        try {
          const committed = await this.change((s) => {
            const p = (s.personal[key] ||= {});
            if ((p.revision || 0) !== draft.base)
              throw Error(
                "Die Notizen wurden zwischenzeitlich verändert. Dein Entwurf bleibt hier erhalten.",
              );
            Object.assign(p, {
              notes: draft.notes,
              revision: (p.revision || 0) + 1,
            });
          });
          if (this.pendingPersonal.get(key) === draft) {
            this.pendingPersonal.delete(key);
            localStorage.removeItem("ah-multitube-note:" + key);
          } else {
            const next = this.pendingPersonal.get(key);
            if (next && next.base === draft.base) {
              next.base = committed.personal[key].revision;
              localStorage.setItem(
                "ah-multitube-note:" + key,
                JSON.stringify(next),
              );
            }
          }
          node.textContent = "Gespeichert";
          node.classList.remove("mt-error");
        } catch (e) {
          node.textContent = e.message;
          node.classList.add("mt-error");
        }
      });
      this.personalSaves.set(key, saving);
      return saving;
    }
    markerPanel(id) {
      const p = this.players.get(id),
        time = p?.video.currentTime || this.w().entries[id]?.time || 0,
        { dialog, body } = this.dialog("Zeitmarke bei " + D.clock(time)),
        name = el("input", {
          "aria-label": "Name der Zeitmarke",
          value: "Zeitmarke",
        });
      body.append(
        name,
        button(
          "Zeitmarke speichern",
          this.action(async () => {
            await this.personal(this.w().entries[id].media, (p) => {
              (p.markers ||= []).push({
                id: D.id(),
                time,
                label: name.value || "Zeitmarke",
              });
            });
            dialog.close();
          }),
        ),
      );
      name.focus();
      name.select();
    }
    async screenshot(id) {
      const p = this.players.get(id),
        video = p?.video;
      if (!video || video.readyState < 2 || !video.videoWidth)
        throw Error(
          "Für einen Screenshot muss ein tatsächliches Videobild bereit sein.",
        );
      const canvas = el("canvas", {
        width: video.videoWidth,
        height: video.videoHeight,
      });
      canvas.getContext("2d").drawImage(video, 0, 0);
      const blob = await new Promise((resolve, reject) => {
        try {
          canvas.toBlob(
            (b) =>
              b
                ? resolve(b)
                : reject(Error("Der Screenshot konnte nicht erstellt werden.")),
            "image/png",
          );
        } catch {
          reject(Error("Die Quelle erlaubt keinen Screenshot."));
        }
      });
      download(
        blob,
        "Multitube-" + D.clock(video.currentTime).replaceAll(":", "-") + ".png",
      );
      this.notice("Screenshot in Originalauflösung ausgegeben.");
    }
    workspacePanel() {
      const { dialog, body } = this.dialog("Arbeitsbereiche"),
        name = el("input", {
          "aria-label": "Neuer Arbeitsbereich",
          placeholder: "Name des neuen Arbeitsbereichs",
        });
      body.append(
        field("Neuer Arbeitsbereich", name),
        button(
          "Anlegen",
          this.action(async () => {
            let key = D.id();
            await this.change((s) => {
              if (s.workspaces.length >= 60)
                throw Error("Höchstens 60 Arbeitsbereiche.");
              s.workspaces.push(D.workspace(name.value, key));
            });
            dialog.close();
            await this.switchWorkspace(key);
          }),
        ),
      );
      for (const item of this.data.workspaces) {
        const row = el(
          "div",
          { class: "mt-entry" },
          el("strong", {
            text: item.name + (item.archived ? " · archiviert" : ""),
          }),
          el("small", { text: Object.keys(item.entries).length + " Videos" }),
        );
        const actions = el("div", { class: "mt-row" });
        if (!item.archived)
          actions.append(
            button(
              "Öffnen",
              this.action(async () => {
                dialog.close();
                await this.switchWorkspace(item.id);
              }),
            ),
            button("Eigenes Fenster", () => api.openWindow(item.id)),
          );
        actions.append(
          button("Umbenennen", () => this.renamePanel(item.id)),
          button(
            "Duplizieren",
            this.action(async () => {
              await this.change((s) => {
                if (s.workspaces.length >= 60)
                  throw Error("Höchstens 60 Arbeitsbereiche.");
                const copy = D.clone(
                  s.workspaces.find((w) => w.id === item.id),
                );
                copy.id = D.id();
                copy.name = (copy.name + " Kopie").slice(0, 80);
                copy.archived = false;
                s.workspaces.push(copy);
              });
              dialog.close();
              this.workspacePanel();
            }),
          ),
        );
        if (item.id !== "default")
          actions.append(
            button(
              item.archived ? "Wiederherstellen" : "Archivieren",
              this.action(async () => {
                await this.change((s) => {
                  const w = s.workspaces.find((w) => w.id === item.id);
                  w.archived = !w.archived;
                  if (w.archived && s.active === w.id) s.active = "default";
                });
                dialog.close();
                this.workspacePanel();
              }),
            ),
          );
        row.append(actions);
        body.append(row);
      }
    }
    renamePanel(key) {
      const w = this.data.workspaces.find((w) => w.id === key),
        { dialog, body } = this.dialog("Arbeitsbereich bearbeiten"),
        name = el("input", { "aria-label": "Name", value: w.name }),
        description = el("textarea", {
          "aria-label": "Beschreibung",
          value: w.description,
        });
      body.append(
        field("Name", name),
        field("Beschreibung", description),
        button(
          "Speichern",
          this.action(async () => {
            await this.change((s) => {
              const target = s.workspaces.find((w) => w.id === key);
              target.name = name.value.trim();
              target.description = description.value;
            });
            dialog.close();
          }),
        ),
      );
    }
    async scenePanel() {
      await this.flushProgress();
      const { dialog, body } = this.dialog("Sitzungen und Layoutvorlagen"),
        name = el("input", {
          "aria-label": "Sitzungsname",
          placeholder: "Name der Sitzung",
        }),
        positions = el("input", { type: "checkbox", checked: true });
      body.append(
        name,
        el(
          "label",
          { class: "mt-check" },
          positions,
          el("span", { text: "Spielpositionen mit speichern" }),
        ),
        button(
          "Aktuelle Sitzung speichern",
          this.action(async () => {
            await this.change((s, w) => {
              if (w.scenes.length >= 24)
                throw Error("Höchstens 24 Sitzungen pro Arbeitsbereich.");
              w.scenes.push(D.scene(w, name.value, positions.checked));
            });
            dialog.close();
            this.scenePanel();
          }),
        ),
      );
      for (const sc of this.w().scenes)
        body.append(
          el(
            "div",
            { class: "mt-entry" },
            el("strong", { text: sc.name ,"data-i18n-content":""}),
            el("small", { text: new Date(sc.created).toLocaleString((globalThis.AppI18n?.locale() || 'de-DE')) }),
            el(
              "div",
              { class: "mt-row" },
              button(
                "Wiederherstellen",
                this.action(async () => {
                  await this.flushProgress();
                  this.restorePaused = new Set(Object.keys(this.w().entries));
                  await this.change((s, w) => D.applyScene(w, sc));
                  for (const p of this.players.values()) {
                    const time = this.w().entries[p.id]?.time;
                    if (time != null && p.ready) p.video.currentTime = time;
                  }
                  dialog.close();
                }),
              ),
              button(
                "Als Layout verwenden",
                this.action(async () => {
                  await this.change((s, w) => {
                    w.capacity = sc.capacity;
                    w.layout = sc.layout;
                    w.fit = sc.fit;
                    w.settings = {
                      ...w.settings,
                      audio: sc.settings.audio,
                      quality: sc.settings.quality,
                    };
                  });
                  dialog.close();
                }),
              ),
              button(
                "Löschen",
                this.action(async () => {
                  await this.change((s, w) => {
                    w.scenes = w.scenes.filter((x) => x.id !== sc.id);
                  });
                  dialog.close();
                  this.scenePanel();
                }),
              ),
            ),
          ),
        );
    }
    morePanel() {
      const { dialog, body } = this.dialog("Multitube · Werkzeuge");
      const go = (fn) => () => {
        dialog.close();
        fn();
      };
      body.append(
        el(
          "div",
          { class: "mt-row" },
          button(
            "Sitzungen und Layoutvorlagen",
            go(() => this.scenePanel()),
          ),
          button(
            "Videolink hinzufügen",
            go(() => this.linkPanel()),
          ),
          button(
            "Arbeitsbereiche",
            go(() => this.workspacePanel()),
          ),
          button(
            "Entfernen rückgängig",
            this.action(async () => {
              await this.undo();
              dialog.close();
            }),
          ),
          button(
            "Clean-Modus",
            this.action(async () => {
              await this.change((s, w) => {
                w.clean = true;
              });
              dialog.close();
            }),
          ),
          button(
            "Fenster ausfüllen",
            this.action(() => this.root.requestFullscreen()),
          ),
          button(
            "Tastaturhilfe",
            go(() => this.helpPanel()),
          ),
        ),
      );
      const settings = this.w().settings;
      const setting = (key, label, rows) => {
        const control = select(label, rows, (value) =>
          this.action(() =>
            this.change((s, w) => {
              w.settings[key] = ["quality", "activeLimit", "master"].includes(
                key,
              )
                ? Number(value)
                : value;
            }),
          )(),
        );
        control.value = String(settings[key]);
        body.append(field(label, control));
      };
      setting("end", "Am Videoende", [
        ["stop", "Letztes Bild behalten"],
        ["repeat", "Video wiederholen"],
        ["next", "Nächstes aus Warteschlange"],
      ]);
      setting("activeLimit", "Aktive Videos", [
        [20, "Alle sichtbaren (bis 20)"],
        ...[1, 2, 4, 6, 8, 12, 16].map((n) => [n, String(n)]),
      ]);
      setting("performance", "Leistungssteuerung", [
        ["manual", "Manuell · gewählte Grenze gilt"],
        ["economy", "Sparsam · höchstens 4 / 480p"],
        ["balanced", "Automatisch bei gemessenen Bildverlusten entlasten"],
      ]);
      setting("quality", "Globale Qualitätsobergrenze", [
        [0, "Original / automatisch"],
        ...[240, 360, 480, 720, 1080, 1440, 2160].map((n) => [n, n + "p"]),
      ]);
      body.append(
        field(
          "Gesamtlautstärke",
          el("input", {
            type: "range",
            min: 0,
            max: 1,
            step: 0.05,
            value: settings.master,
            "aria-label": "Gesamtlautstärke",
            oninput: (e) => {
              this.userAudio = true;
              this.action(() =>
                this.change((s, w) => {
                  w.settings.master = Number(e.target.value);
                }),
              )();
            },
          }),
        ),
      );
      setting("background", "Bei verborgenem Fenster", [
        ["pause", "Videos pausieren, Positionen behalten"],
        ["audio", "Nur hörbare Videos weiterlaufen lassen"],
        ["continue", "Wiedergabe weiterlaufen lassen"],
      ]);
      const fit = select(
        "Bildanpassung",
        [
          ["contain", "Vollständiges Bild"],
          ["cover", "Fläche füllen (Bild wird beschnitten)"],
        ],
        (v) =>
          this.action(() =>
            this.change((s, w) => {
              w.fit = v;
            }),
          )(),
      );
      fit.value = this.w().fit;
      body.append(field("Bildanpassung", fit));
      const allFit = el("input", {
        type: "checkbox",
        checked: !!settings.fitAll,
        onchange: this.action((e) =>
          this.change((s, w) => {
            w.settings.fitAll = e.target.checked;
            w.page = 0;
          }),
        ),
      });
      body.append(
        el(
          "label",
          { class: "mt-check" },
          allFit,
          el("span", {
            text: "Alle Plätze gleichzeitig ins Fenster einpassen (auch sehr kleine Kacheln)",
          }),
        ),
      );
      const linked = el("input", {
        type: "checkbox",
        checked: settings.linked,
        onchange: this.action(async (e) => {
          await this.change((s, w) => {
            w.settings.linked = e.target.checked;
            w.settings.offsets = Object.fromEntries(
              [...this.players.values()].map((p) => [
                p.id,
                p.video.currentTime || 0,
              ]),
            );
          });
        }),
      });
      body.append(
        el(
          "label",
          { class: "mt-check" },
          linked,
          el("span", {
            text: "Vergleich koppeln: Zeitsprünge mit aktuellem Zeitversatz übertragen",
          }),
        ),
        el("small", {
          text: "Die Kopplung steuert Sprünge und erhält Zeitversätze. Unterschiedliche Quellen sind nicht garantiert bildgenau synchron.",
        }),
      );
      body.append(
        el(
          "div",
          { class: "mt-row" },
          button(
            "Sicherung exportieren",
            this.action(async () => {
              await this.flushProgress();
              download(
                new Blob([JSON.stringify(D.exportState(this.data), null, 2)], {
                  type: "application/json",
                }),
                "Multitube-Sicherung.json",
              );
            }),
          ),
          button(
            "Rückfallsicherung wiederherstellen",
            this.action(async () => {
              const old = await this.store.read("backups", "before-import");
              if (!old) throw Error("Keine Rückfallsicherung vorhanden.");
              this.previewImport(D.exportState(old));
            }),
          ),
        ),
      );
      const file = el("input", {
        type: "file",
        accept: ".json,application/json",
        "aria-label": "Multitube-Sicherung importieren",
        onchange: this.action(async (e) => {
          const f = e.target.files[0];
          if (!f) return;
          if (f.size > 12_000_000) throw Error("Die Sicherung ist zu groß.");
          this.previewImport(JSON.parse(await f.text()));
        }),
      });
      body.append(field("Sicherung importieren", file));
    }
    previewImport(payload) {
      const incoming = D.importState(payload),
        { dialog, body } = this.dialog("Sicherung prüfen");
      body.append(
        el("p", {
          text: `${incoming.workspaces.length} Arbeitsbereiche · ${Object.keys(incoming.videos).length} Videos · ${Object.values(incoming.personal).reduce((n, p) => n + (p.markers || []).length, 0)} Zeitmarken. Zugangsdaten und aufgelöste Medienadressen sind kein Bestandteil.`,
        }),
        button(
          "Als zusätzliche Arbeitsbereiche übernehmen",
          this.action(async () => {
            await this.change((s) => {
              if (s.workspaces.length + incoming.workspaces.length > 60)
                throw Error(
                  "Die Übernahme würde 60 Arbeitsbereiche überschreiten.",
                );
              Object.assign(s.videos, incoming.videos);
              for (const [k, p] of Object.entries(incoming.personal))
                if (!s.personal[k]) s.personal[k] = p;
              for (const original of incoming.workspaces) {
                const w = D.clone(original);
                w.id = D.id();
                w.name = (w.name + " · Import").slice(0, 80);
                s.workspaces.push(w);
              }
            }, true);
            dialog.close();
            this.notice(
              "Sicherung als zusätzliche Arbeitsbereiche übernommen. Vorheriger Stand ist gesichert.",
            );
          }),
        ),
        button(
          "Gesamten Multitube-Stand ersetzen",
          this.action(async () => {
            await this.flushProgress();
            this.importing = true;
            const oldWorkspace = this.workspaceId;
            try {
              await this.store.mutate(() => D.clone(incoming), true, true);
            } finally {
              this.importing = false;
            }
            if (this.owner) await this.store.release(oldWorkspace, owner);
            this.destroyAll();
            this.workspaceId = D.get(incoming).id;
            this.loadFilter();
            this.owner = await this.store.claim(this.workspaceId, owner);
            this.restorePaused = new Set(Object.keys(this.w().entries));
            dialog.close();
            this.notice(
              "Sicherung übernommen. Wiedergabe mit ▶ bewusst fortsetzen.",
            );
            this.render();
          }),
        ),
      );
    }
    helpPanel() {
      const { body } = this.dialog("Tastatur und Bedienung");
      body.append(
        el("p", {
          text: "Leertaste: ausgewähltes Video pausieren/fortsetzen\nPfeile links/rechts: −/+ 10 Sekunden\nF: ausgewähltes Video fokussieren\nG: Raster\nM: ausgewähltes Video mit Solo-Ton\nB: Zeitmarke setzen\nEscape: Clean-Modus verlassen\nStrg/Cmd + Mausrad: Bild zoomen\nVergrößertes Bild ziehen: Ausschnitt verschieben\nDoppelklick im Bild: Ausschnitt zurücksetzen\nVideos und Kachelüberschriften können auf andere Plätze gezogen werden.\nFilter der Videoauswahl verändern keine laufenden Videos.",
        }),
      );
    }
    onKey(e) {
      if (
        !this.active ||
        e.ctrlKey ||
        e.metaKey ||
        e.altKey ||
        e.target.closest("input,textarea,select,[contenteditable=true]") ||
        document.querySelector(".mt-dialog[open]")
      )
        return;
      const id = this.w().selected || this.w().focus,
        actions = {
          " ": () => this.toggle(id),
          ArrowLeft: () =>
            this.seek(id, (this.players.get(id)?.video.currentTime || 0) - 10),
          ArrowRight: () =>
            this.seek(id, (this.players.get(id)?.video.currentTime || 0) + 10),
          f: () => this.focus(id),
          g: () =>
            this.change((s, w) => {
              w.layout = "grid";
            }),
          m: () => this.solo(id),
          b: () => this.markerPanel(id),
          Escape: () =>
            this.change((s, w) => {
              w.clean = false;
              w.sidebar = true;
            }),
        };
      if (actions[e.key] && id) {
        e.preventDefault();
        e.stopImmediatePropagation();
        this.action(actions[e.key])();
      }
    }
  }
  const api = {
    configure(ctx) {
      context = ctx;
      bus.postMessage({ type: "ping", owner });
    },
    async open(panel, ctx) {
      instance ||= new Studio();
      try {
        await instance.open(panel, ctx || context);
      } catch (e) {
        panel.textContent =
          "Multitube konnte nicht geöffnet werden: " + e.message;
      }
    },
    leave() {
      instance?.leave();
    },
    openWindow(key) {
      root.open(
        "/?page=multi" + (key ? "&workspace=" + encodeURIComponent(key) : ""),
        key && key !== "default" ? "ah-multitube-" + key : "ah-multi",
      );
    },
    async enqueue(rows, options = {}) {
      if (!hasWindow() && !options.noWindow) api.openWindow();
      const s = await store();
      await s.mutate((data) => {
        D.add(data, data.active, rows, options);
        return data;
      });
      return s.value;
    },
    async seed(rows) {
      const s = await store();
      await s.mutate((data) => {
        const keys = [];
        for (const row of rows) {
          try {
            const v = D.video(row);
            data.videos[v.key] = { ...data.videos[v.key], ...v };
            keys.push(v.key);
          } catch {}
        }
        data.candidates = keys.slice(0, 1000);
        return data;
      });
    },
    get instance() {
      return instance;
    },
    Studio,
    store,
  };
  root.MultiTube = api;
})(globalThis);
