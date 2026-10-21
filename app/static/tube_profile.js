(function (root) {
  "use strict";
  let D = root.TubeProfileDomain;
  const fmt = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 });
  const date = (d) =>
    d
      ? d.toLocaleDateString((globalThis.AppI18n?.locale() || 'de-DE'), {
          day: "2-digit",
          month: "2-digit",
          year: "numeric",
        })
      : "Ohne Datum";
  const time = (d) =>
    d
      ? d.toLocaleString((globalThis.AppI18n?.locale() || 'de-DE'), {
          day: "2-digit",
          month: "2-digit",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        })
      : "Ohne Zeitstempel";
  const sourceName = (s) =>
    ({
      player: "Einzelplayer",
      multitube: "Multitube",
      legacy: "Bisheriger Verlauf",
    })[s] || s;
  const el = (tag, props = {}, ...children) => {
    const n = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (key === "text") n.textContent = value;
      else if (key === "class") n.className = value;
      else if (key.startsWith("on")) n.addEventListener(key.slice(2), value);
      else if (key in n) n[key] = value;
      else n.setAttribute(key, value);
    }
    n.append(...children.filter((v) => v != null));
    return n;
  };
  const btn = (label, action, props = {}) =>
    el("button", { type: "button", text: label, onclick: action, ...props });
  const muted = (text) => el("p", { class: "tp-muted", text });
  const box = (title, ...children) =>
    el("section", { class: "tp-box" }, el("h3", { text: title }), ...children);
  function select(label, rows, value, action) {
    const input = el("select", {
      "aria-label": label,
      onchange: (e) => action(e.target.value),
    });
    for (const [id, name] of rows)
      input.append(el("option", { value: id, text: name }));
    input.value = value;
    return el(
      "label",
      { class: "tp-field" },
      el("span", { text: label }),
      input,
    );
  }
  function save(blob, name) {
    const url = URL.createObjectURL(blob),
      a = el("a", { href: url, download: name });
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
  let instance;
  class Profile {
    constructor(ctx) {
      this.ctx = ctx;
      this.filter = { days: "30", site: "", source: "" };
      this.tab = "overview";
      this.sequence = 0;
      this.mount = document.getElementById("tube-profile");
      this.mount.className = "tp";
      root.addEventListener("tube-measurement-status", (e) => {
        const node = this.mount.querySelector(".tp-measurement-save-status");
        if (node)
          node.textContent = e.detail.error
            ? "Einige Messungen sind noch nicht gesichert. Die Speicherung wird erneut versucht."
            : "";
      });
      let narrow = innerWidth <= 760;
      root.addEventListener("resize", () => {
        const next = innerWidth <= 760;
        if (next && !narrow && this.ctx.state.view === "profile")
          requestAnimationFrame(() =>
            this.mount.scrollIntoView({ block: "start" }),
          );
        narrow = next;
      });
      const heading = el(
        "div",
        { class: "tp-heading" },
        el(
          "div",
          {},
          el("span", { class: "tp-eyebrow", text: "DEIN TUBE-PROFIL" }),
          el("h2", { text: "Deine Videos. Dein Überblick." }),
          muted(
            "Videoaufrufe, Entdeckungen und deine Bibliothek an einem Ort. Live-Cams führen eine eigene Statistik.",
          ),
        ),
      );
      this.refresh = btn("Aktualisieren", () => this.load());
      heading.append(this.refresh);
      this.status = el("p", {
        class: "tp-status",
        role: "status",
        "aria-live": "polite",
      });
      this.controls = el("div", { class: "tp-controls" });
      this.tabs = el("div", {
        class: "tp-tabs",
        role: "tablist",
        "aria-label": "Profilbereiche",
      });
      for (const [id, label] of [
        ["overview", "Überblick"],
        ["preferences", "Deine Vorlieben"],
        ["watching", "Wiedergabe & Fokus"],
        ["activity", "Aktivität"],
        ["library", "Bibliothek"],
      ]) {
        const b = btn(
          label,
          () => {
            this.tab = id;
            this.render();
          },
          {
            id: "tp-tab-" + id,
            role: "tab",
            "aria-controls": "tp-panel-" + id,
          },
        );
        b.addEventListener("keydown", (e) => {
          if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
            e.preventDefault();
            const tabs = [...this.tabs.children];
            let i = tabs.indexOf(b);
            i =
              e.key === "Home"
                ? 0
                : e.key === "End"
                  ? tabs.length - 1
                  : (i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) %
                    tabs.length;
            tabs[i].click();
            tabs[i].focus();
          }
        });
        this.tabs.append(b);
      }
      this.body = el("div", {});
      this.coverage = el("details", { class: "tp-box tp-method" });
      this.coverage.append(
        el("summary", { text: "Was bedeuten diese Zahlen?" }),
        muted(
          "Videoaufrufe zählen erfolgreich aufgelöste Videoquellen, auch wenn die Wiedergabe anschließend pausiert oder scheitert. Sie belegen weder vollständiges Ansehen noch eine bestimmte Sehdauer. Erneutes Öffnen zählt erneut; Pausieren, Fortsetzen und Schleifen erzeugen keine zusätzlichen Aufrufe. Geöffnete Bereiche (etwa Kategorien, Models oder Kanäle) werden getrennt von Videoaufrufen ausgewertet.",
        ),
        muted(
          "Der lokale Verlauf enthält höchstens 2.000 Aktionen. Er ist keine vollständige lebenslange Statistik. Zeitfilter verwenden die Ortszeit dieses Geräts; Aktionen ohne gültiges Datum erscheinen nur unter „Gesamter Verlauf“. Frühere Aufrufe besitzen keine Unterscheidung zwischen Einzelplayer und Multitube. Andere Geräte, Kodi-Nutzung und Live-Cams sind nicht enthalten. Bei Live-Aufrufen werden bekannte Live-Anbieter und Live-Kennzeichnungen ausgeschlossen.",
        ),
      );
      this.mount.replaceChildren(
        heading,
        this.status,
        this.controls,
        this.tabs,
        this.body,
        this.coverage,
      );
    }
    site(id) {
      return (this.ctx.state.catalog.sites || []).find((s) => s.id === id);
    }
    name(id) {
      return this.site(id)?.title || id || "Ohne Seitenangabe";
    }
    async load() {
      const seq = ++this.sequence;
      this.refresh.disabled = true;
      this.status.textContent = "Profil wird aktualisiert …";
      try {
        const response = await fetch("/api/ui", { cache: "no-store" });
        if (!response.ok) throw Error("HTTP " + response.status);
        const ui = await response.json();
        try {
          await root.TubeConsumption?.flush();
          const extra = await fetch("/api/tube-profile", { cache: "no-store" });
          if (!extra.ok) throw Error();
          this.consumption = await extra.json();
          this.extraError = false;
        } catch {
          this.extraError = true;
        }
        if (seq !== this.sequence) return;
        this.ctx.state.ui = ui;
        this.status.textContent =
          "Aktualisiert um " +
          new Date().toLocaleTimeString((globalThis.AppI18n?.locale() || 'de-DE'), {
            hour: "2-digit",
            minute: "2-digit",
          }) +
          ".";
        this.render();
      } catch {
        if (seq === this.sequence)
          this.status.textContent =
            "Aktualisieren fehlgeschlagen. Die zuletzt geladenen Daten bleiben sichtbar. Bitte erneut versuchen.";
      } finally {
        if (seq === this.sequence) this.refresh.disabled = false;
      }
    }
    render() {
      this.data = D.analyze(
        this.ctx.state.ui,
        this.ctx.state.catalog,
        this.filter,
      );
      const data = this.data;
      this.insights = root.TubeInsights.analyze(
        data,
        this.consumption || {},
        this.filter,
      );
      this.controls.replaceChildren(
        select(
          "Zeitraum",
          [
            ["7", "Letzte 7 Tage"],
            ["30", "Letzte 30 Tage"],
            ["90", "Letzte 90 Tage"],
            ["0", "Gesamter Verlauf"],
          ],
          this.filter.days,
          (v) => {
            this.filter.days = v;
            this.render();
          },
        ),
      );
      const ids = [...new Set(data.all.map((r) => r.site))].sort((a, b) =>
        this.name(a).localeCompare(this.name(b), "de"),
      );
      this.controls.append(
        select(
          "Tube-Seite",
          [
            ["", "Alle Seiten"],
            ...ids.filter(Boolean).map((id) => [id, this.name(id)]),
          ],
          this.filter.site,
          (v) => {
            this.filter.site = v;
            this.render();
          },
        ),
        select(
          "Aufrufquelle",
          [
            ["", "Alle Quellen"],
            ["player", "Einzelplayer"],
            ["multitube", "Multitube"],
            ["legacy", "Bisheriger Verlauf"],
          ],
          this.filter.source,
          (v) => {
            this.filter.source = v;
            this.render();
          },
        ),
        btn(
          "Filter zurücksetzen",
          () => {
            this.filter = { days: "30", site: "", source: "" };
            this.render();
          },
          { class: "tp-quiet" },
        ),
      );
      const exportMenu = el(
        "details",
        { class: "tp-export" },
        el("summary", { text: "Daten exportieren" }),
      );
      exportMenu.append(
        btn("CSV herunterladen", () =>
          save(
            new Blob([D.csv(data.events)], { type: "text/csv;charset=utf-8" }),
            "tube-profil-" + D.dayKey(new Date()) + ".csv",
          ),
        ),
        btn("JSON herunterladen", () => this.exportJSON()),
        muted(
          "Tube-Daten des gewählten Filters. JSON enthält auch Zeitmessungen und zugeordnete Modeldaten. Enthält persönliche Titel und Video-URLs.",
        ),
      );
      this.controls.append(exportMenu);
      for (const b of this.tabs.children) {
        const on = b.id === "tp-tab-" + this.tab;
        b.setAttribute("aria-selected", String(on));
        b.tabIndex = on ? 0 : -1;
      }
      const panel = el("div", {
        id: "tp-panel-" + this.tab,
        role: "tabpanel",
        "aria-labelledby": "tp-tab-" + this.tab,
        tabIndex: 0,
      });
      this.body.replaceChildren(panel);
      if (this.tab === "overview") this.overview(panel);
      else if (this.tab === "activity") this.activity(panel);
      else if (this.tab === "preferences") this.preferences(panel);
      else if (this.tab === "watching") this.watching(panel);
      else this.library(panel);
    }
    exportJSON() {
      const d = this.data;
      const modelIds=new Set(this.insights.groups.models.filter(r=>r.profile).map(r=>r.profile.id||r.profile.name));
      const filteredModels=Object.fromEntries(Object.entries(this.consumption?.models||{}).filter(([key,p])=>modelIds.has(p.id||p.name)));
      save(
        new Blob(
          [
            JSON.stringify(
              {
                version: 1,
                scope: "tube",
                exportedAt: new Date().toISOString(),
                filter: this.filter,
                metrics: {
                  calls: d.plays.length,
                  uniqueVideos: d.unique,
                  repeatedCalls: d.repeats,
                  categoryOpens: d.opens.length,
                  activeDays: d.activeDays,
                },
                events: d.events.map(({ date, index, key, ...r }) => r),
                consumption: {
                  recording: this.consumption?.recording,
                  sessions: this.insights.sessions,
                  videos: this.insights.videos,
                  models: filteredModels,
                },
              },
              null,
              2,
            ),
          ],
          { type: "application/json" },
        ),
        "tube-profil-" + D.dayKey(new Date()) + ".json",
      );
    }
    metric(label, value, hint, id) {
      return el(
        "article",
        { class: "tp-metric", ...(id ? { "data-metric": id } : {}) },
        el("span", { text: label }),
        el("strong", { text: fmt.format(value) }),
        el("small", { text: hint }),
      );
    }
    overview(panel) {
      const d = this.data;
      const trend =
        d.previous == null
          ? "Gesamter gespeicherter Verlauf"
          : d.previous === 0
            ? d.plays.length
              ? "Im Vergleichszeitraum: 0"
              : "Auch im Vergleichszeitraum: 0"
            : (d.plays.length >= d.previous ? "+" : "") +
              fmt.format(((d.plays.length - d.previous) / d.previous) * 100) +
              " % zu den vorigen " +
              d.days +
              " Tagen";
      panel.append(
        el(
          "div",
          { class: "tp-metrics" },
          this.metric("Videoaufrufe", d.plays.length, trend, "calls"),
          this.metric(
            "Unterschiedliche Videos",
            d.unique,
            fmt.format(d.repeats) + " weitere Aufrufe bekannter Videos",
            "unique",
          ),
          this.metric(
            "Aktive Tage",
            d.activeDays,
            fmt.format(d.average) + " Aufrufe je aktivem Tag",
            "days",
          ),
          this.metric(
            "Bereiche geöffnet",
            d.opens.length,
            "Getrennt von den Videoaufrufen",
            "opens",
          ),
        ),
      );
      if (!d.events.length)
        panel.append(
          box(
            "Hier wächst dein Überblick",
            muted(
              "Für diese Auswahl gibt es noch keine Tube-Aktionen. Wähle einen anderen Zeitraum oder öffne ein Video. Dein bisheriger Verlauf bleibt erhalten.",
            ),
            btn("Tube-Seiten entdecken", () => this.ctx.navigate("sites")),
          ),
        );
      const chart = box(
        "Deine Aktivität im Zeitverlauf",
        muted(
          "Videoaufrufe und geöffnete Bereiche pro Kalendertag. Tage ohne Aktivität bleiben sichtbar.",
        ),
      );
      chart.append(this.timeline());
      if (!d.days && d.timeline.length === 90)
        chart.append(
          muted(
            "Das Diagramm zeigt die letzten 90 Tage; die Kennzahlen beziehen sich auf den gesamten gespeicherten Verlauf.",
          ),
        );
      const grid = el(
        "div",
        { class: "tp-grid" },
        chart,
        this.ranking("Deine Tube-Seiten", d.sites, d.plays.length, "site"),
      );
      panel.append(grid);
      const facts = el(
        "div",
        { class: "tp-facts" },
        el(
          "p",
          {},
          el("strong", { text: fmt.format(d.sites.length) }),
          " genutzte Seiten",
        ),
        el(
          "p",
          {},
          el("strong", { text: fmt.format(d.longest) }),
          " Tage längste Aktivitätsserie",
        ),
        el(
          "p",
          {},
          el("strong", { text: date(d.last) }),
          " letzter Videoaufruf",
        ),
      );
      panel.append(facts);
      const names = [
        "Sonntag",
        "Montag",
        "Dienstag",
        "Mittwoch",
        "Donnerstag",
        "Freitag",
        "Samstag",
      ];
      panel.append(
        el(
          "div",
          { class: "tp-grid" },
          this.topVideos(),
          this.ranking(
            "Videoaufrufe nach Wochentag",
            [1, 2, 3, 4, 5, 6, 0]
              .map((w) => ({ label: names[w], count: d.weekdays[w] }))
              .filter((r) => r.count),
            d.plays.length,
          ),
        ),
      );
      const interests = el(
        "details",
        { class: "tp-box" },
        el("summary", {
          text: "Interessen im Detail · Kategorien, Models & Kanäle",
        }),
      );
      interests.append(
        el(
          "div",
          { class: "tp-grid" },
          this.ranking(
            "Kategorien & Bereiche deiner Videoaufrufe",
            d.categories,
            d.plays.length,
          ),
          this.ranking("Geöffnete Bereiche", d.opened, d.opens.length),
        ),
        this.ranking(
          "Models & Kanäle im Aufrufkontext",
          d.performers,
          d.plays.length,
        ),
      );
      const rhythm = el(
        "details",
        { class: "tp-box" },
        el("summary", {
          text: "Nutzungszeiten im Detail · Wochentage & Stunden",
        }),
      );
      rhythm.append(this.heatmap());
      panel.append(interests, rhythm);
      if (d.undated)
        panel.append(
          muted(
            fmt.format(d.undated) +
              " ältere Aktionen ohne gültiges Datum sind nur unter „Gesamter Verlauf“ enthalten.",
          ),
        );
    }
    timeline() {
      const rows = this.data.timeline,
        ns = "http://www.w3.org/2000/svg",
        svg = document.createElementNS(ns, "svg");
      const w = 560,
        h = 210,
        p = 34,
        max = Math.max(1, ...rows.map((r) => Math.max(r.play, r.open))),
        step = (w - 2 * p) / rows.length;
      svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
      svg.setAttribute("role", "img");
      svg.setAttribute(
        "aria-label",
        "Tägliche Tube-Aktivität. Genaue Werte stehen in der aufklappbaren Tabelle.",
      );
      svg.classList.add("tp-chart");
      const node = (tag, attrs, txt) => {
        const n = document.createElementNS(ns, tag);
        for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
        if (txt) n.textContent = txt;
        svg.append(n);
        return n;
      };
      for (const fraction of [0, 0.5, 1]) {
        const y = h - p - fraction * (h - 2 * p);
        node("line", { x1: p, y1: y, x2: w - p, y2: y, class: "tp-gridline" });
        node(
          "text",
          { x: p - 7, y: y + 4, "text-anchor": "end" },
          fmt.format(max * fraction),
        );
      }
      rows.forEach((r, i) => {
        const bar = node("rect", {
          x: p + i * step + step * 0.16,
          y: h - p - (r.play / max) * (h - 2 * p),
          width: step * 0.68,
          height: (r.play / max) * (h - 2 * p),
          class: "tp-chart-bar",
        });
        const title = document.createElementNS(ns, "title");
        title.textContent =
          date(new Date(r.day + "T00:00:00")) +
          ": " +
          r.play +
          " Videoaufrufe, " +
          r.open +
          " Bereiche";
        bar.append(title);
      });
      node("polyline", {
        points: rows
          .map(
            (r, i) =>
              `${p + (i + 0.5) * step},${h - p - (r.open / max) * (h - 2 * p)}`,
          )
          .join(" "),
        class: "tp-chart-open",
      });
      for (const i of [
        ...new Set([0, Math.floor((rows.length - 1) / 2), rows.length - 1]),
      ])
        node(
          "text",
          {
            x: p + (i + 0.5) * step,
            y: h - 8,
            "text-anchor":
              i === 0 ? "start" : i === rows.length - 1 ? "end" : "middle",
          },
          new Date(rows[i].day + "T00:00:00").toLocaleDateString((globalThis.AppI18n?.locale() || 'de-DE'), {
            day: "2-digit",
            month: "2-digit",
          }),
        );
      const details = el(
        "details",
        { class: "tp-data" },
        el("summary", { text: "Tageswerte als Tabelle" }),
      );
      details.append(
        this.table(
          ["Tag", "Videoaufrufe", "Bereiche"],
          rows
            .slice()
            .reverse()
            .map((r) => [date(new Date(r.day + "T00:00:00")), r.play, r.open]),
        ),
      );
      return el(
        "div",
        {},
        el(
          "p",
          { class: "tp-legend" },
          el("span", { text: "▰ Videoaufrufe" }),
          el("span", { class: "tp-secondary", text: "━ Bereiche" }),
        ),
        svg,
        details,
      );
    }
    ranking(title, rows, total, kind) {
      const section = box(title);
      if (!rows.length) {
        section.append(
          muted(
            "Für diese Auswahl noch keine Angaben. Kategorien und Models werden nur gezählt, wenn der Aufrufkontext sie mitliefert.",
          ),
        );
        return section;
      }
      const more = el(
        "details",
        {},
        el("summary", {
          text:
            "Weitere " +
            fmt.format(Math.max(0, rows.length - 8)) +
            " Einträge anzeigen",
        }),
      );
      for (const [index, r] of rows.entries()) {
        const share = total ? (r.count / total) * 100 : 0,
          label = kind === "site" ? this.name(r.label) : r.label;
        const name =
          kind === "site" && this.site(r.label)
            ? btn(label, () => this.ctx.openSite(r.label), {
                class: "tp-text-button",
                title: label + " öffnen",
              })
            : el("span", { text: label });
        const row = el(
          "div",
          { class: "tp-rank" },
          el(
            "div",
            { class: "tp-rank-label" },
            name,
            el("strong", {
              text: fmt.format(r.count) + " · " + fmt.format(share) + " %",
            }),
          ),
          el(
            "div",
            { class: "tp-track", "aria-hidden": "true" },
            el("i", { style: "width:" + share + "%" }),
          ),
        );
        (index < 8 ? section : more).append(row);
      }
      if (rows.length > 8) section.append(more);
      return section;
    }
    topVideos() {
      const section = box("Häufig aufgerufene Videos");
      if (!this.data.videos.length)
        section.append(muted("Deine Videoaufrufe erscheinen hier."));
      for (const r of this.data.videos.slice(0, 5))
        section.append(
          el(
            "div",
            { class: "tp-video-row" },
            this.visual(r),
            el(
              "div",
              {},
              this.openButton(r),
              el("small", {
                text: fmt.format(r.count) + " Aufrufe · " + this.name(r.site),
              }),
            ),
          ),
        );
      section.append(
        btn("Alle Aufrufe ansehen", () => {
          this.tab = "activity";
          this.render();
        }),
      );
      return section;
    }
    visual(row) {
      if (!row.thumb)
        return el("span", {
          class: "tp-placeholder",
          "aria-hidden": "true",
          text: row.model ? row.model.slice(0, 1).toUpperCase() : "▷",
        });
      const img = el("img", {
        class: "tp-thumb",
        alt: "",
        loading: "lazy",
        decoding: "async",
        src: this.ctx.image(row.thumb),
      });
      img.onerror = () =>
        img.replaceWith(
          el("span", {
            class: "tp-placeholder",
            "aria-hidden": "true",
            text: row.model ? row.model.slice(0, 1).toUpperCase() : "▷",
          }),
        );
      return img;
    }
    openButton(row) {
      const url = D.playable(row);
      if (!url) return el("span", { text: row.title || "Ohne Titel" ,"data-i18n-content":""});
      return btn(
        row.title || "Video öffnen",
        () => this.ctx.open({ ...row, url }, "video"),
        { class: "tp-text-button", title: "Video öffnen: " + row.title },
      );
    }
    table(head, rows) {
      const table = el(
        "table",
        {},
        el(
          "thead",
          {},
          el("tr", {}, ...head.map((t) => el("th", { scope: "col", text: t }))),
        ),
      );
      const body = el("tbody", {});
      for (const row of rows)
        body.append(
          el(
            "tr",
            {},
            ...row.map((v) => el("td", {}, v instanceof Node ? v : String(v))),
          ),
        );
      table.append(body);
      return el(
        "div",
        {
          class: "tp-table-wrap",
          tabIndex: 0,
          "aria-label": "Tabelle, bei Bedarf seitlich scrollen",
        },
        table,
      );
    }
    heatmap() {
      const d = this.data,
        max = Math.max(1, ...d.heat.flat()),
        names = [
          "Sonntag",
          "Montag",
          "Dienstag",
          "Mittwoch",
          "Donnerstag",
          "Freitag",
          "Samstag",
        ];
      const table = el(
        "table",
        { class: "tp-heat" },
        el("caption", {
          text: "Videoaufrufe nach Wochentag und Ortszeit. Dunkel bedeutet wenig, kräftig bedeutet viel Aktivität.",
        }),
      );
      table.append(
        el(
          "thead",
          {},
          el(
            "tr",
            {},
            el("th", { scope: "col", text: "Tag / Uhr" }),
            ...Array.from({ length: 24 }, (_, h) =>
              el("th", { scope: "col", text: String(h).padStart(2, "0") }),
            ),
          ),
        ),
      );
      const body = el("tbody", {});
      for (const w of [1, 2, 3, 4, 5, 6, 0])
        body.append(
          el(
            "tr",
            {},
            el("th", { scope: "row", text: names[w].slice(0, 2) }),
            ...d.heat[w].map((v, h) =>
              el("td", {
                style: "--heat:" + (v ? 0.18 + (v / max) * 0.82 : 0),
                title: names[w] + ", " + h + " Uhr: " + v + " Aufrufe",
                "aria-label": names[w] + ", " + h + " Uhr: " + v + " Aufrufe",
                text: v ? String(v) : "·",
              }),
            ),
          ),
        );
      table.append(body);
      const peak = d.hours.indexOf(Math.max(...d.hours)),
        day = d.weekdays.indexOf(Math.max(...d.weekdays));
      return box(
        "Wann du Videos aufrufst",
        muted(
          d.hours.some(Boolean) || d.weekdays.some(Boolean)
            ? "Häufigste Stunde: " +
                (d.hours.some(Boolean)
                  ? String(peak).padStart(2, "0") + " Uhr"
                  : "keine Angabe") +
                " · Häufigster Wochentag: " +
                (d.weekdays.some(Boolean) ? names[day] : "keine Angabe") +
                ". Gleichstände zeigen den ersten Wert."
            : "Noch keine Zeitangaben in dieser Auswahl.",
        ),
        el(
          "div",
          {
            class: "tp-table-wrap",
            tabIndex: 0,
            "aria-label": "Nutzungszeiten, seitlich scrollbare Tabelle",
          },
          table,
        ),
      );
    }
    activity(panel) {
      panel.append(
        el("h3", { text: "Deine Tube-Aktivität" }),
        muted(
          "Die Auswahl oben gilt für diese Liste. Erneute Videoaufrufe bleiben einzeln sichtbar. Über einen Videotitel startest du das Video erneut.",
        ),
      );
      const controls = el("div", { class: "tp-list-tools" }),
        result = el("div", {}),
        count = el("p", { "aria-live": "polite", class: "tp-muted" });
      let term = "",
        kind = "",
        sort = "new",
        page = 1;
      const search = el("input", {
        type: "search",
        placeholder: "Titel, Seite, Kategorie oder Model suchen",
        "aria-label": "Aktivität durchsuchen",
        oninput: (e) => {
          term = e.target.value.toLocaleLowerCase("de");
          page = 1;
          paint();
        },
      });
      controls.append(
        search,
        select(
          "Aktion",
          [
            ["", "Alle Aktionen"],
            ["play", "Videoaufrufe"],
            ["open", "Bereiche"],
          ],
          kind,
          (v) => {
            kind = v;
            page = 1;
            paint();
          },
        ),
        select(
          "Sortierung",
          [
            ["new", "Neueste zuerst"],
            ["old", "Älteste zuerst"],
            ["title", "Titel A–Z"],
          ],
          sort,
          (v) => {
            sort = v;
            page = 1;
            paint();
          },
        ),
      );
      panel.append(controls, count, result);
      const paint = () => {
        const rows = this.data.events
          .filter(
            (r) =>
              (!kind || r.kind === kind) &&
              (!term ||
                [r.title, this.name(r.site), r.category, r.performer]
                  .join(" ")
                  .toLocaleLowerCase("de")
                  .includes(term)),
          )
          .slice()
          .sort((a, b) =>
            sort === "title"
              ? a.title.localeCompare(b.title, "de")
              : sort === "old"
                ? (a.date || Infinity) - (b.date || Infinity)
                : (b.date || 0) - (a.date || 0),
          );
        count.textContent = fmt.format(rows.length) + " passende Aktionen";
        result.replaceChildren();
        if (!rows.length) {
          result.append(
            box(
              "Keine passenden Aktionen",
              muted("Passe den Zeitraum, die Quelle oder die Suche an."),
            ),
          );
          return;
        }
        result.append(
          this.table(
            ["Zeitpunkt", "Aktion / Titel", "Tube-Seite", "Kontext", "Quelle"],
            rows.slice((page - 1) * 15, page * 15).map((r) => [
              time(r.date),
              el(
                "div",
                {},
                el("small", {
                  text: r.kind === "open" ? "Bereich geöffnet" : "Videoaufruf",
                }),
                r.kind === "play"
                  ? this.openButton(r)
                  : el("span", { text: r.title ,"data-i18n-content":""}),
              ),
              this.name(r.site),
              [r.category, r.performer].filter(Boolean).join(" · ") || "–",
              sourceName(r.source),
            ]),
          ),
        );
        result.append(
          this.pager(page, Math.ceil(rows.length / 15), (v) => {
            page = v;
            paint();
          }),
        );
      };
      paint();
    }
    pager(page, pages, action) {
      return el(
        "div",
        { class: "tp-pager" },
        btn("Zurück", () => action(page - 1), { disabled: page <= 1 }),
        el("span", { text: "Seite " + page + " von " + pages }),
        btn("Weiter", () => action(page + 1), { disabled: page >= pages }),
      );
    }
    preferences(panel) {
      this.renderPreferences(panel);
    }
    watching(panel) {
      this.renderWatching(panel);
    }
    library(panel) {
      const lib = this.data.library;
      panel.append(
        el("h3", { text: "Deine Tube-Bibliothek" }),
        muted(
          "Bestand über alle Zeiträume und Seiten. Die Filter oben gelten für die Aktivität, nicht für deine gespeicherte Bibliothek. Videos in Gruppen sind enthalten und werden nur einmal gezählt.",
        ),
        el(
          "div",
          { class: "tp-metrics" },
          this.metric(
            "Gespeicherte Videos",
            lib.videos.length,
            "Einschließlich aller Gruppen",
            "saved",
          ),
          this.metric(
            "Videogruppen",
            lib.groups.length,
            "Gruppen mit Tube-Videos",
          ),
          this.metric("Abos", lib.follows.length, "Models und Kanäle"),
          this.metric(
            "Model-Favoriten",
            lib.stars.length,
            "In deiner Model-Bibliothek",
          ),
        ),
      );
      panel.append(
        el(
          "div",
          { class: "tp-shortcuts" },
          btn("Lesezeichen & Gruppen verwalten", () =>
            this.ctx.navigate("bookmarks"),
          ),
          btn("Model-Bibliothek öffnen", () => this.ctx.navigate("stars")),
        ),
      );
      const grid = el("div", { class: "tp-grid" }),
        favorites = box("Deine Lieblingsseiten");
      if (!lib.favorites.length)
        favorites.append(
          muted("Favorisiere Tube-Seiten, um sie hier schnell zu erreichen."),
        );
      for (const id of lib.favorites)
        favorites.append(
          btn(this.name(id), () => this.ctx.openSite(id), { class: "tp-chip" }),
        );
      const groups = box("Deine Videogruppen");
      if (!lib.groups.length)
        groups.append(muted("Noch keine Tube-Videos in Gruppen."));
      for (const group of lib.groups)
        groups.append(
          el("p", {
            class: "tp-group",
            text: group.name + " · " + fmt.format(group.count) + " Videos",
          }),
        );
      grid.append(favorites, groups);
      panel.append(grid);
      const search = el("input", {
          type: "search",
          "aria-label": "Bibliothek durchsuchen",
          placeholder: "Gespeichertes Video oder Gruppe suchen",
        }),
        rows = el("div", {});
      let page = 1;
      search.oninput = () => {
        page = 1;
        paint();
      };
      panel.append(el("h3", { text: "Gespeicherte Videos" }), search, rows);
      const paint = () => {
        const term = search.value.toLocaleLowerCase("de"),
          list = lib.videos.filter((r) =>
            [r.title, ...r.groups, this.name(D.siteOf(r))]
              .join(" ")
              .toLocaleLowerCase("de")
              .includes(term),
          );
        rows.replaceChildren();
        rows.append(muted(fmt.format(list.length) + " Videos"));
        const cards = el("div", { class: "tp-library" });
        for (const r of list.slice((page - 1) * 12, page * 12))
          cards.append(
            el(
              "article",
              { class: "tp-library-card" },
              this.visual(r),
              el(
                "div",
                {},
                this.openButton(r),
                el("small", { text: this.name(D.siteOf(r)) }),
                el("small", { text: r.groups.join(" · ") || "Ohne Gruppe" }),
              ),
              btn(
                "Zu Multitube",
                () => this.ctx.queue({ ...r, url: D.playable(r) || r.url }),
                { disabled: !D.playable(r) },
              ),
            ),
          );
        rows.append(cards);
        if (list.length)
          rows.append(
            this.pager(page, Math.ceil(list.length / 12), (v) => {
              page = v;
              paint();
            }),
          );
      };
      paint();
      const follows = box("Abonnierte Models & Kanäle");
      if (!lib.follows.length)
        follows.append(muted("Deine Abos erscheinen hier."));
      for (const r of lib.follows)
        follows.append(
          btn(r.title, () => this.ctx.open(r, "follow"), { class: "tp-chip" }),
        );
      panel.append(follows);
      const offline = el(
          "details",
          { class: "tp-box" },
          el("summary", { text: "Offline-Porträts deiner Model-Bibliothek" }),
        ),
        status = muted("Details öffnen, um den aktuellen Stand zu laden.");
      offline.append(status);
      offline.addEventListener("toggle", async () => {
        if (!offline.open) return;
        status.textContent = "Stand wird geladen …";
        try {
          const res = await fetch("/api/models", { cache: "no-store" });
          if (!res.ok) throw Error();
          const s = await res.json();
          status.textContent =
            (s.running ? "Wird geladen: " : "Offline gespeichert: ") +
            fmt.format(s.done || 0) +
            " von " +
            fmt.format(s.total || 0) +
            " Porträts · " +
            fmt.format(s.failed || 0) +
            " fehlgeschlagen.";
        } catch {
          status.textContent =
            "Der Offline-Stand ist gerade nicht erreichbar. Erneut öffnen, um es noch einmal zu versuchen.";
        }
      });
      panel.append(offline);
    }
  }
  const durationText = (seconds) => {
    const n = Math.max(0, Math.round(seconds || 0));
    return n >= 3600
      ? Math.floor(n / 3600) + " Std. " + Math.floor((n % 3600) / 60) + " Min."
      : n >= 60
        ? Math.floor(n / 60) + " Min. " + (n % 60) + " Sek."
        : n + " Sek.";
  };
  Profile.prototype.extraNotice = function (panel) {
    if (this.extraError)
      panel.append(
        box(
          "Zusatzdaten gerade nicht erreichbar",
          muted(
            "Vorhandene Auswertungen bleiben sichtbar. Bitte mit „Aktualisieren“ erneut laden.",
          ),
        ),
      );
  };
  Profile.prototype.insightRanking = function (title, rows) {
    const section = box(title),
      score = (r) => (this.filter.weight === "focus" ? r.focus : r.calls),
      max = Math.max(1, ...rows.map(score));
    if (!rows.length) {
      section.append(
        muted(
          "Hier fehlen noch zugeordnete Videofakten. Neue Wiedergaben ergänzen die Auswertung automatisch.",
        ),
      );
      return section;
    }
    const more = el(
      "details",
      {},
      el("summary", {
        text: "Weitere " + Math.max(0, rows.length - 8) + " Einträge",
      }),
    );
    for (const [index, r] of rows.entries()) {
      const line = el(
        "div",
        { class: "tp-rank" },
        el(
          "div",
          { class: "tp-rank-label" },
          btn(r.label, () => this.evidence(r), {
            class: "tp-text-button",
            title: "Zugeordnete Videos anzeigen",
          }),
          el("strong", {
            text:
              this.filter.weight === "focus"
                ? durationText(r.focus)
                : fmt.format(r.calls) + " Aufrufe",
          }),
        ),
        el(
          "div",
          { class: "tp-track", "aria-hidden": "true" },
          el("i", { style: "width:" + (score(r) / max) * 100 + "%" }),
        ),
        el("small", {
          text:
            r.unique +
            " unterschiedliche Videos · " +
            (this.filter.weight === "focus"
              ? r.calls + " Aufrufe"
              : durationText(r.focus) + " aktive Videozeit"),
        }),
      );
      (index < 8 ? section : more).append(line);
    }
    if (rows.length > 8) section.append(more);
    return section;
  };
  Profile.prototype.evidence = function (row) {
    const dialog = el("dialog", {
        class: "tp tp-dialog",
        "aria-label": "Videobelege zu " + row.label,
      }),
      body = el("div", {});
    dialog.append(
      el(
        "div",
        { class: "tp-dialog-head" },
        el("h3", { text: row.label }),
        btn("Schließen", () => dialog.close()),
      ),
      muted(
        "Diese Videos bilden die Grundlage der Auswertung. Besetzungs- und Profilangaben stammen aus Videofakten und dem lokalen Modelkatalog.",
      ),
      body,
    );
    if (row.profile && this.ctx.model)
      body.append(
        btn("Modelprofil öffnen", () => {
          dialog.close();
          this.ctx.model(row.profile);
        }),
      );
    const records = this.insights.videos.filter((v) =>
      row.videos.includes(v.key),
    );
    for (const v of records.slice(0, 100))
      body.append(
        el(
          "div",
          { class: "tp-video-row" },
          this.visual(v),
          el(
            "div",
            {},
            this.openButton(v),
            el("small", {
              text:
                v.calls +
                " Aufrufe · " +
                durationText(v.focus) +
                " aktive Videozeit",
            }),
          ),
        ),
      );
    if (records.length > 100)
      body.append(
        muted(
          "Die ersten 100 Videos. Alle zugeordneten Daten stehen im JSON-Export.",
        ),
      );
    dialog.addEventListener("close", () => dialog.remove());
    document.body.append(dialog);
    dialog.showModal();
  };
  Profile.prototype.renderPreferences = function (panel) {
    const a = this.insights,
      g = a.groups,
      total = a.knownCalls;
    this.extraNotice(panel);
    panel.append(
      el("h3", { text: "Was du besonders häufig auswählst" }),
      muted(
        "Die Auswertung verbindet deine Videoaufrufe mit bekannten Videofakten. Mehrere Models und Tags können zu einem Video gehören. Ihre Summen dürfen sich deshalb überschneiden.",
      ),
      select(
        "Vorlieben sortieren nach",
        [
          ["calls", "Häufigkeit der Aufrufe"],
          ["focus", "Aktiver Videozeit"],
        ],
        this.filter.weight || "calls",
        (v) => {
          this.filter.weight = v;
          this.render();
        },
      ),
    );
    if (this.filter.weight === "focus" && !a.focus)
      panel.append(
        muted(
          "Im gewählten Zeitraum fehlt noch aktive Vordergrundzeit. Eine zeitbasierte Lieblingsauswahl lässt sich daraus noch nicht bestimmen.",
        ),
      );
    const leading = [
      ["Model", g.models[0]],
      ["Kategorie", g.categories[0]],
      ["Tag", g.tags[0]],
    ];
    const hero = el("div", { class: "tp-insight-hero" });
    for (const [label, candidate] of leading) {
      const r =
        this.filter.weight === "focus" && !candidate?.focus ? null : candidate;
      hero.append(
        el(
          "article",
          {},
          el("span", { class: "tp-eyebrow", text: label }),
          el("strong", { text: r?.label || "Noch offen" }),
          el("small", {
            text: r
              ? r.calls +
                " Aufrufe · " +
                durationText(r.focus) +
                " aktive Videozeit"
              : "Noch keine passenden Videofakten",
          }),
        ),
      );
    }
    panel.append(
      hero,
      el("p", {
        class: "tp-coverage",
        text:
          "Datenbasis: " +
          a.coverage.models +
          " von " +
          total +
          " Aufrufen mit Modelzuordnung · " +
          a.coverage.categories +
          " mit Videokategorien · " +
          a.coverage.tags +
          " mit Tags.",
      }),
    );
    const models = box(
        this.filter.weight === "focus"
          ? "Models nach aktiver Videozeit"
          : "Deine häufigsten Models",
      ),
      cards = el("div", { class: "tp-models" });
    for (const r of g.models.slice(0, 6)) {
      const p = r.profile,
        age = p ? root.TubeInsights.age(p, new Date()) : null;
      const details = [
        p?.hair ? "Haar: " + p.hair : "",
        p?.build ? "Statur: " + p.build : "",
        age ? (age.approximate ? "ca. " : "") + age.value + " Jahre heute" : "",
      ].filter(Boolean);
      const row = el(
        "article",
        { class: "tp-model-card" },
        this.visual({ thumb: p?.thumb, model: r.label }),
        el(
          "div",
          {},
          el("strong", { text: r.label }),
          el("small", { text: r.calls + " Aufrufe · " + r.unique + " Videos" }),
          el("small", { text: durationText(r.focus) + " aktive Videozeit" }),
          el("small", {
            text: details.join(" · ") || "Weitere Profilangaben fehlen",
          }),
        ),
        btn("Videos dazu", () => this.evidence(r)),
      );
      if (p && this.ctx.model)
        row.append(btn("Profil", () => this.ctx.model(p)));
      cards.append(row);
    }
    models.append(cards);
    if (!g.models.length)
      models.append(
        muted(
          "Sobald ein Video Models nennt oder ein früherer Modelkontext eindeutig im lokalen Katalog zugeordnet werden kann, erscheinen sie hier. Ein Kanalname wird nicht automatisch als Model gewertet.",
        ),
      );
    if (g.models.length > 6) {
      const all = el(
        "details",
        {},
        el("summary", { text: "Alle Models im Vergleich" }),
      );
      all.append(this.insightRanking("Alle zugeordneten Models", g.models));
      models.append(all);
    }
    panel.append(models);
    const tags = box("Deine Tags auf einen Blick"),
      cloud = el("div", { class: "tp-tag-cloud" }),
      value = (r) => (this.filter.weight === "focus" ? r.focus : r.calls),
      max = Math.max(1, ...g.tags.map(value));
    for (const r of g.tags.slice(0, 30))
      cloud.append(
        btn(
          r.label +
            " · " +
            (this.filter.weight === "focus" ? durationText(r.focus) : r.calls),
          () => this.evidence(r),
          {
            style: "--tag-scale:" + (1 + Math.sqrt(value(r) / max) * 0.55),
            title: r.unique + " Videos · " + r.calls + " Aufrufe",
          },
        ),
      );
    tags.append(cloud);
    if (!g.tags.length)
      tags.append(
        muted("Tags erscheinen, sobald die Videoseite sie übermittelt."),
      );
    if (g.tags.length > 30) {
      const all = el(
        "details",
        {},
        el("summary", { text: "Alle Tags vergleichen" }),
      );
      all.append(this.insightRanking("Alle Tags", g.tags));
      tags.append(all);
    }
    panel.append(
      el(
        "div",
        { class: "tp-grid" },
        this.insightRanking("Deine Videokategorien", g.categories),
        tags,
      ),
    );
    panel.append(
      el("h3", { text: "Welche Modelmerkmale in deinen Videos vorkommen" }),
      muted(
        "Aus veröffentlichten Profilangaben zu deinen aufgerufenen Videos. Alter bedeutet heutiges Alter; bei bloßem Geburtsjahr ist es ungefähr. Das Alter beim Dreh ist nicht bekannt.",
      ),
      el("p", {
        class: "tp-coverage",
        text:
          a.coverage.appearance +
          " von " +
          total +
          " Aufrufen mit bekannten Erscheinungsmerkmalen · " +
          a.coverage.age +
          " mit nutzbarer Altersangabe.",
      }),
      el(
        "div",
        { class: "tp-grid" },
        this.insightRanking("Haarfarben", g.hair),
        this.insightRanking("Altersgruppen heute", g.age),
      ),
    );
    const appearance = el(
      "details",
      { class: "tp-box" },
      el("summary", {
        text: "Weitere Merkmale · Augen, Statur, Größe und Körbchengröße",
      }),
    );
    appearance.append(
      el(
        "div",
        { class: "tp-grid" },
        this.insightRanking("Augenfarben", g.eyes),
        this.insightRanking("Statur", g.build),
        this.insightRanking("Körpergröße", g.height),
        this.insightRanking("Körbchengröße laut Profil", g.cup),
      ),
    );
    panel.append(appearance);
    const context = el(
      "details",
      { class: "tp-box" },
      el("summary", {
        text: "Filme im Detail · Studios, Veröffentlichungsjahre und Videolängen",
      }),
    );
    context.append(
      el(
        "div",
        { class: "tp-grid" },
        this.insightRanking("Studios", g.studios),
        this.insightRanking("Veröffentlichungsjahre", g.years),
        this.insightRanking("Videolängen", g.length),
      ),
    );
    panel.append(context);
  };
  Profile.prototype.renderWatching = function (panel) {
    const a = this.insights;
    this.extraNotice(panel);
    panel.append(
      el("p", {
        class: "tp-muted tp-measurement-save-status",
        role: "status",
        text: root.TubeConsumption?.error
          ? "Einige Messungen sind noch nicht gesichert. Die Speicherung wird erneut versucht."
          : "",
      }),
    );
    const toggle = btn(
      a.recording ? "Zeitmessung pausieren" : "Zeitmessung fortsetzen",
      async () => {
        toggle.disabled = true;
        try {
          this.consumption.recording = await root.TubeConsumption.setRecording(
            !a.recording,
          );
          this.render();
        } catch {
          toggle.disabled = false;
          toggle.textContent = "Ändern fehlgeschlagen · erneut versuchen";
        }
      },
    );
    panel.append(
      el("h3", { text: "Wie du Videos tatsächlich abspielst" }),
      muted(
        "Gemessen wird laufendes Video im sichtbaren, fokussierten Fenster. Das liefert einen Hinweis auf aktive Nutzung; tatsächliche Aufmerksamkeit ist nicht messbar. Parallele Videos zählen bei der aktiven Gesamtzeit einmal.",
      ),
      el(
        "div",
        { class: "tp-recording" },
        el("span", {
          text: a.recording
            ? "● Zeitmessung läuft lokal ab jetzt"
            : "○ Neue Zeitmessungen sind pausiert",
        }),
        toggle,
      ),
    );
    const timed = (label, value, hint) => {
      const card = this.metric(label, 0, hint);
      card.querySelector("strong").textContent = a.sessions.length
        ? durationText(value)
        : "–";
      return card;
    };
    panel.append(
      el(
        "div",
        { class: "tp-metrics" },
        timed(
          "Aktive Zeit im Vordergrund",
          a.focus,
          "Gleichzeitige Videos einmal gezählt",
        ),
        timed(
          "Sichtbare Wiedergabe",
          a.visible,
          "Player sichtbar, auch ohne Fensterfokus",
        ),
        timed(
          "Abgespielte Videozeit",
          a.playerTime,
          "Parallele Videos addieren sich hier",
        ),
        timed(
          "Typische aktive Phase",
          a.medianPhase,
          "Median zusammenhängender Vordergrundphasen",
        ),
      ),
    );
    if (!a.sessions.length)
      panel.append(
        box(
          "Die Zeitmessung beginnt mit neuen Wiedergaben",
          muted(
            "Ältere Aufrufe besitzen keine gemessene Laufzeit. Spiele ein Tube-Video ab und aktualisiere anschließend das Profil. Pausen, stillstehende Bilder, Puffern und reine Positionssprünge erzeugen keine abgespielte Zeit.",
          ),
        ),
      );
    panel.append(
      el(
        "div",
        { class: "tp-facts" },
        el(
          "p",
          {},
          el("strong", { text: String(a.measuredVideos) }),
          " Videos mit Zeitmessung",
        ),
        el(
          "p",
          {},
          el("strong", {
            text: a.sessions.length ? durationText(a.medianSession) : "–",
          }),
          " Median je aktiver Wiedergabe",
        ),
        el(
          "p",
          {},
          el("strong", { text: a.completion + " / " + a.completionKnown }),
          " Videos mit mindestens 90 % belegter Abdeckung",
        ),
      ),
    );
    const habits = box("Dein Wiedergabeverhalten");
    habits.append(
      el(
        "div",
        { class: "tp-behavior" },
        this.metric(
          "Positionssprünge",
          a.seeks,
          "Auch technische Wiederherstellungen möglich",
        ),
        this.metric(
          "Pause-Ereignisse",
          a.pauses,
          "Unterbrechungen ohne Sehdauer",
        ),
        this.metric(
          "Puffer-Ereignisse",
          a.stalls,
          "Kein Zeichen mangelnden Interesses",
        ),
        this.metric(
          "Kurze Besuche",
          a.early,
          "Beendete Messung: unter 30 Sek. aktiv bei Videos ab 2 Min.",
        ),
      ),
    );
    panel.append(habits);
    const rows = a.videos
      .filter((v) => v.playing > 0)
      .sort((x, y) => y.focus - x.focus);
    const details = box("Welche Videos dich länger im Vordergrund begleiten");
    if (rows.length)
      details.append(
        this.table(
          [
            "Video",
            "Aktive Videozeit",
            "Abgespielte Videozeit",
            "Belegte Videoabschnitte",
          ],
          rows.slice(0, 50).map((v) => [
            this.openButton(v),
            durationText(v.focus),
            durationText(v.playing),
            el(
              "div",
              {},
              el("span", {
                text:
                  v.percent == null
                    ? v.duration
                      ? "Abdeckung im Zeitraum unbekannt"
                      : "Länge unbekannt"
                    : fmt.format(v.percent) + " %",
              }),
              el(
                "div",
                { class: "tp-track", "aria-hidden": "true" },
                el("i", { style: "width:" + (v.percent || 0) + "%" }),
              ),
              el("small", {
                text:
                  durationText(v.covered) + " unterschiedliche Videoabschnitte",
              }),
            ),
          ]),
        ),
      );
    else details.append(muted("Noch keine gemessenen Videoabschnitte."));
    panel.append(
      details,
      muted(
        "Abdeckung zählt verschiedene tatsächlich abgespielte Videoabschnitte, statt einen Sprung zum Ende als vollständiges Ansehen zu werten. Wiedergabegeschwindigkeit und Schleifen verlängern die Abdeckung nicht künstlich. Sichtbarkeit und Fokus werden ungefähr einmal pro Sekunde geprüft. Daten werden gebündelt lokal gesichert; ältere Nutzung wird nicht nachträglich geschätzt.",
      ),
    );
    const list = el(
      "details",
      { class: "tp-box" },
      el("summary", { text: "Einzelne Wiedergaben als Tabelle" }),
    );
    list.append(
      this.table(
        ["Beginn", "Video", "Quelle", "Aktive Zeit", "Videozeit", "Sprünge"],
        a.sessions
          .slice(0, 100)
          .map((s) => [
            time(new Date(s.started * 1000)),
            this.openButton(s.video),
            sourceName(s.source),
            durationText(s.focusSeconds),
            durationText(s.playSeconds),
            s.seeks || 0,
          ]),
      ),
    );
    panel.append(list);
  };
  root.TubeProfile = {
    open(ctx) {
      D = root.TubeProfileDomain;
      if (!instance) instance = new Profile(ctx);
      else instance.ctx = ctx;
      instance.render();
      return instance.load();
    },
    get instance() {
      return instance;
    },
  };
})(window);
