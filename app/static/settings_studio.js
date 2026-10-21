(function (root) {
  "use strict";
  const D = root.SettingsDomain,
    $ = (id) => document.getElementById(id);
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
  const button = (text, fn, props = {}) =>
    el("button", { type: "button", text, onclick: fn, ...props });
  const clone = D.copy,
    assetURL = (file) => "/api/design-asset?file=" + encodeURIComponent(file),
    roles = ["body", "headings", "navigation", "controls", "cards", "brand"];
  const categories = [
    ["look", "Farben & Schriften", "Farben, Schriftarten, Lesbarkeit"],
    ["brand", "Logo & Hintergrund", "Eigener Name, Logos, Bilder und Flächen"],
    ["menu", "Navigation & Start", "Menüpunkte, Reihenfolge und Startseite"],
    ["lists", "Medien & Wiedergabe", "Listen, Kacheln, Player und Angaben"],
    [
      "live",
      "Live & Arbeitsbereiche",
      "Live-Einstellungen und eigene Arbeitsbereiche",
    ],
    ["models", "Sprache & Models", "Texte und Profilpflege"],
    ["updates", "Updates & Modellbilder", "Programm, Datenpakete und Offline-Bilder"],
    ["tools", "Speicher & Extras", "Offline-Inhalte, Werkzeuge und Neustart"],
    [
      "profiles",
      "Designprofile",
      "Eigene Vorlagen, Sicherungen und Wiederherstellung",
    ],
    ["about", "Über Adult Client", "Projekt, Ersteller und Herkunft"],
    ["help", "Hilfe", "Anleitung für alle Bereiche und Einstellungen"],
  ];
  const names = {
    body: "Grundschrift",
    headings: "Überschriften",
    navigation: "Menüschrift",
    controls: "Schaltflächen und Eingaben",
    cards: "Kacheltitel",
    brand: "Namenszug",
  };
  const stateFields = {
    "set-pages": "pages",
    "set-per-page": "perPage",
    "set-tile": "tile",
    "set-view": "view",
    "set-auto": "autoplay",
    "set-previews": "previews",
    "set-download-folder": "downloadFolder",
    "menu-sort": "sort",
  };
  const fontLoads = new Map();
  let instance;
  function fontFamily(choice, d, legacy) {
    if (choice === "system-ui") return "system-ui,sans-serif";
    if (choice === "inherit" && d.typography.body !== "inherit")
      return fontFamily(d.typography.body, d, legacy);
    if (choice === "inherit")
      return JSON.stringify(legacy || "Segoe UI") + ",sans-serif";
    if (choice === "custom")
      return (
        JSON.stringify(d.typography.customFamily || legacy || "Segoe UI") +
        ",sans-serif"
      );
    if (choice.startsWith("asset:"))
      return '"AHDesign_' + choice.slice(6).split(".")[0] + '",sans-serif';
    return JSON.stringify(choice) + ",sans-serif";
  }
  function rgba(hex, opacity) {
    const p = hex.match(/[a-f0-9]{2}/gi).map((n) => parseInt(n, 16));
    return `rgba(${p.join(",")},${opacity / 100})`;
  }
  class Studio {
    constructor(ctx) {
      this.ctx = ctx;
      this.d = D.normalize(ctx.state.ui.theme?.design);
      this.category = "look";
      this.target = "all";
      this.controls = new Map();
      this.bgControls = new Map();
      this.history = [];
      this.rangePainters = [];
      this.originalLogos = new Map();
      this.savedRevision = ctx.state.ui.themeRevision || 0;
      this.lastEditor = "";
      this.lastEditAt = 0;
      this.loading = false;
      this.saving = false;
      this.lastWindowWidth = innerWidth;
      root.addEventListener("resize", () => {
        const crossed = this.lastWindowWidth > 760 && innerWidth <= 760;
        this.lastWindowWidth = innerWidth;
        if (crossed && this.ctx.state.view === "settings")
          requestAnimationFrame(() =>
            $("view-settings").scrollIntoView({ block: "start" }),
          );
      });
      this.channel = new BroadcastChannel("ah-settings");
      this.channel.onmessage = (e) => {
        if (e.data?.revision > this.savedRevision)
          this.notice(
            "In einem anderen Fenster wurde gespeichert. Dein Entwurf bleibt unverändert. „Gespeicherten Stand laden“ übernimmt den aktuellen Stand.",
          );
      };
    }
    async init() {
      this.build();
      this.sync();
      this.saved = this.capture();
      this.last = clone(this.saved);
      try {
        const draft = JSON.parse(
          sessionStorage.getItem("ah-settings-draft") || "null",
        );
        if (draft?.snapshot && !D.equal(draft.snapshot, this.saved)) {
          this.restore(draft.snapshot);
          this.savedRevision = draft.revision;
          this.notice(
            "Ungespeicherter Entwurf wiederhergestellt. Du kannst ihn speichern oder verwerfen.",
          );
        }
      } catch {}
      this.last = this.capture();
      this.update();
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
    notice(text, error = false) {
      if (!this.message) return;
      this.message.textContent = text;
      this.message.hidden = !text;
      this.message.classList.toggle("ds-error", error);
    }
    capture() {
      const settings = {};
      for (const [id, key] of Object.entries(stateFields)) {
        const n = $(id);
        settings[key] = n.type === "checkbox" ? n.checked : n.value;
      }
      return { theme: this.ctx.themeNow(), settings };
    }
    restore(snapshot) {
      this.loading = true;
      try {
        this.ctx.fillThemeForm(clone(snapshot.theme));
        for (const [id, key] of Object.entries(stateFields)) {
          const n = $(id);
          if (snapshot.settings?.[key] != null) {
            if (n.type === "checkbox") n.checked = !!snapshot.settings[key];
            else n.value = String(snapshot.settings[key]);
          }
        }
        this.d = D.normalize(snapshot.theme.design);
        this.sync();
        this.ctx.applyTheme(this.ctx.themeNow());
      } finally {
        this.loading = false;
      }
      this.last = this.capture();
      this.update();
    }
    record(editor = "action") {
      if (this.loading) return;
      const current = this.capture();
      if (D.equal(current, this.last)) return;
      if (editor !== this.lastEditor || Date.now() - this.lastEditAt > 600) {
        this.history.push(clone(this.last));
        if (this.history.length > 30) this.history.shift();
      }
      this.lastEditor = editor;
      this.lastEditAt = Date.now();
      this.last = clone(current);
      this.update();
      this.schedule();
    }
    schedule() {
      if (this.previewFrame) return;
      this.previewFrame = requestAnimationFrame(() => {
        this.previewFrame = 0;
        this.ctx.applyTheme(this.ctx.themeNow());
        this.preview();
      });
    }
    update() {
      if (!this.saved) return;
      this.dirty = !D.equal(this.capture(), this.saved);
      this.saveButton.textContent = this.saving
        ? "Speichert …"
        : "Änderungen speichern";
      this.saveButton.disabled = this.saving || !this.dirty;
      this.discard.disabled = !this.dirty || this.saving;
      this.undoButton.disabled = !this.history.length || this.saving;
      this.saveState.textContent = this.dirty
        ? "Ungespeicherte Vorschau"
        : "Alles gespeichert";
      $("view-settings").classList.toggle("ds-dirty", this.dirty);
      try {
        if (this.dirty)
          sessionStorage.setItem(
            "ah-settings-draft",
            JSON.stringify({
              snapshot: this.capture(),
              revision: this.savedRevision,
            }),
          );
        else sessionStorage.removeItem("ah-settings-draft");
      } catch {
        this.notice(
          "Der Entwurf konnte nicht zusätzlich im Browser gesichert werden.",
          true,
        );
      }
      this.preview();
    }
    async save() {
      if (this.saving || !this.dirty) return;
      const submitted = this.capture();
      this.saving = true;
      this.update();
      try {
        const previousSort = this.saved.settings.sort,
          ui = await this.ctx.save(submitted, this.savedRevision);
        this.savedRevision = ui.themeRevision || 0;
        this.saved = clone(submitted);
        this.saved.theme = clone(ui.theme);
        if (ui.settingsSortSaved === false)
          this.saved.settings.sort = previousSort;
        if (
          ui.settingsSortSaved !== false &&
          D.equal(this.capture(), submitted)
        )
          this.restore(this.saved);
        this.channel.postMessage({ revision: this.savedRevision });
        this.notice(
          ui.settingsSortSaved === false
            ? "Die Einstellungen sind gespeichert. Die Seitensortierung konnte noch nicht gespeichert werden und bleibt im Entwurf."
            : "Einstellungen gespeichert.",
          ui.settingsSortSaved === false,
        );
      } catch (e) {
        this.notice(
          e.message || "Speichern fehlgeschlagen. Der Entwurf bleibt erhalten.",
          true,
        );
      } finally {
        this.saving = false;
        this.update();
      }
    }
    async reloadSaved() {
      const ui = await fetch("/api/ui", { cache: "no-store" }).then((r) =>
        r.json(),
      );
      const prefs = await fetch("/api/prefs", { cache: "no-store" }).then((r) =>
        r.json(),
      );
      this.ctx.state.ui = ui;
      this.ctx.state.prefs = prefs;
      this.savedRevision = ui.themeRevision || 0;
      const settings = {};
      for (const [id, key] of Object.entries(stateFields))
        settings[key] = key === "sort" ? prefs.sort : ui[key];
      this.saved = { theme: ui.theme || {}, settings };
      this.restore(this.saved);
      this.saved = this.capture();
      this.history = [];
      this.update();
      this.notice("Aktuell gespeicherter Stand geladen.");
    }
    section(title, parent, key) {
      const n = el(
        "section",
        { class: "ds-section", "data-section": key || title },
        el("h3", { text: title }),
      );
      parent.append(n);
      return n;
    }
    advanced(title, parent) {
      const d = el(
        "details",
        { class: "ds-advanced" },
        el("summary", { text: title }),
      );
      parent.append(d);
      return d;
    }
    control(path, label, options = {}, parent) {
      const rule = options.rule || D.schema.fields[path],
        id = "ds-" + path.replaceAll(".", "-");
      let node;
      const handler = () => {
        let v = node.type === "checkbox" ? node.checked : node.value;
        const clean = D.value(v, rule);
        if (rule.type === "url" && node.value.trim() && !clean) {
          node.setAttribute("aria-invalid", "true");
          this.notice(
            "Bitte eine vollständige Bildadresse mit http:// oder https:// eingeben.",
            true,
          );
          return;
        }
        node.removeAttribute("aria-invalid");
        if (options.background) {
          this.bg()[path] = clean;
        } else D.set(this.d, path, clean);
        if (path === "brand.name" && this.d.brand.mode === "legacy") {
          this.d.brand.mode = "text";
          if (this.controls.get("brand.mode"))
            this.controls.get("brand.mode").node.value = "text";
        }
        if (options.background) {
          if (path === "url" && clean) {
            this.bg().image = "";
            this.bg().mode = "image";
            this.bgControls.get("mode").node.value = "image";
          }
          this.backgroundVisibility();
        }
        if (path === "layout.customCards")
          this.ctx.applyTheme(this.ctx.themeNow());
        options.after?.(clean);
        this.record(id);
        output.textContent = this.display(clean, rule, options.unit);
      };
      if (rule.type === "enum" || rule.type === "font" || options.values) {
        node = el("select", { id, "aria-label": label, onchange: handler });
        const values =
          options.values ||
          (rule.type === "font"
            ? this.fontOptions()
            : rule.values.map((v) => [v, v]));
        for (const [v, t] of values)
          node.append(el("option", { value: String(v), text: t }));
      } else if (rule.type === "boolean")
        node = el("input", {
          id,
          type: "checkbox",
          "aria-label": label,
          onchange: handler,
        });
      else {
        const type =
          rule.type === "color"
            ? "color"
            : rule.type === "number"
              ? "range"
              : rule.type === "url"
                ? "url"
                : "text";
        node = el("input", { id, type, "aria-label": label });
        if (type === "range") {
          node.min = rule.min;
          node.max = rule.max;
          node.step = options.step || (rule.max <= 2 ? 0.05 : 1);
        }
        if (rule.max && type === "text") node.maxLength = rule.max;
        node.addEventListener(type === "url" ? "change" : "input", handler);
      }
      const output = el("output", { htmlFor: id, class: "ds-value" }),
        wrap = el(
          "label",
          { class: rule.type === "boolean" ? "ds-field ds-check" : "ds-field" },
          el("span", { text: label }),
          node,
          output,
        );
      if (options.help) wrap.append(el("small", { text: options.help }));
      parent.append(wrap);
      const record = { path, node, output, rule, unit: options.unit };
      (options.background ? this.bgControls : this.controls).set(path, record);
      return node;
    }
    display(v, rule, unit) {
      if (rule.type === "number")
        return unit === "width" && Number(v) === 0
          ? "Volle Breite"
          : unit === "columns" && Number(v) === 0
            ? "Automatisch"
            : String(v).replace(".", ",") +
              (unit === "width" ? " px" : unit === "columns" ? "" : unit || "");
      if (rule.type === "color") return v;
      return "";
    }
    fontOptions() {
      return D.schema.fonts
        .map((v) => [
          v,
          v === "inherit"
            ? "Grundschrift übernehmen"
            : v === "custom"
              ? "Eigene installierte Schrift"
              : v === "system-ui"
                ? "Systemschrift"
                : v,
        ])
        .concat(
          this.d.fonts.map((f) => ["asset:" + f.file, f.name + " (Datei)"]),
        );
    }
    moveLegacy(key, parent, title) {
      const n = document.querySelector('[data-set-panel="' + key + '"]');
      if (!n) return;
      n.removeAttribute("data-set-panel");
      n.classList.remove("hidden");
      n.classList.add("ds-legacy");
      if (title) n.prepend(el("h3", { text: title }));
      parent.append(n);
      return n;
    }
    build() {
      const host = $("view-settings");
      host.classList.add("ds-settings");
      const header = el(
        "div",
        { class: "ds-header" },
        el(
          "div",
          {},
          el("h2", { text: "Einstellungen" }),
          el("p", {
            text: "Gestalte deine Oberfläche. Änderungen werden direkt als Vorschau angezeigt.",
          }),
        ),
      );
      host.querySelector("h2").remove();
      const search = el("input", {
        type: "search",
        placeholder: "Einstellungen finden …",
        "aria-label": "Einstellungen durchsuchen",
        oninput: () => this.search(search.value),
      });
      this.searchInput = search;
      header.append(
        el(
          "label",
          { class: "ds-search" },
          el("span", { text: "Suchen" }),
          search,
        ),
        button("Hilfe", () => this.openCategory("help"), { class: "ds-help-button", "aria-label": "Hilfe öffnen" }),
      );
      this.message = el("p", {
        class: "ds-message",
        role: "status",
        hidden: true,
      });
      this.results = el("p", { class: "ds-results", hidden: true });
      const tabs = $("set-tabs");
      tabs.replaceChildren();
      tabs.className = "ds-nav";
      tabs.setAttribute("role", "tablist");
      tabs.setAttribute("aria-label", "Einstellungsbereiche");
      const layout = el("div", { class: "ds-settings-layout" }),
        content = el("div", { class: "ds-content" });
      this.panels = {};
      for (const [key, title, help] of categories) {
        const old = document.querySelector('[data-set-panel="' + key + '"]'),
          panel = old || el("div", { "data-set-panel": key });
        panel.className = "ds-panel";
        this.panels[key] = panel;
        const tab = button(
          title,
          () => {
            this.category = key;
            this.searchInput.value = "";
            this.search("");
            this.ctx.category?.(key);
          },
          {
            id: "ds-tab-" + key,
            role: "tab",
            "aria-controls": "ds-panel-" + key,
          },
        );
        panel.id = "ds-panel-" + key;
        panel.setAttribute("role", "tabpanel");
        panel.setAttribute("aria-labelledby", tab.id);
        panel.dataset.description = help;
        tabs.append(tab);
        content.append(panel);
      }
      const left = el("div", { class: "ds-rail" }, tabs);
      this.previewBox = el("section", {
        class: "ds-preview",
        "aria-label": "Designvorschau",
      });
      left.append(this.previewBox);
      layout.append(left, content);
      host.prepend(header, this.message, this.results, layout);
      // Group the original controls without changing their IDs, actions or stored values.
      this.moveLegacy("home", this.panels.menu, "Startseite");
      this.moveLegacy("play", this.panels.lists, "Wiedergabe");
      this.moveLegacy("info", this.panels.lists, "Video-Infos");
      this.moveLegacy("lang", this.panels.models, "Sprache");
      const interfaceLanguage = el("section", { class: "ds-section" },
        el("h3", { text: "Sprache der Oberfläche" }),
        el("p", { text: "Deutsch und Englisch sofort wechseln. Laufende Wiedergabe und Eingaben bleiben erhalten. Die Sprache der Modelldaten wird davon unabhängig eingestellt." }),
        el("label", {}, el("span", { text: "Oberflächensprache" }),
          el("select", { "data-ui-language": "", "aria-label": "Oberflächensprache", value: globalThis.AppI18n?.language || "de" },
            el("option", { value: "de", text: "Deutsch", translate: "no" }),
            el("option", { value: "en", text: "English", translate: "no" }))));
      this.panels.models.prepend(interfaceLanguage);
      this.moveLegacy("offline", this.panels.tools, "Offline-Speicher");
      // Existing appearance rows become concise sections with advanced controls folded away.
      const look = this.panels.look,
        rows = [...look.children];
      const palette = this.section("Farben und Vorlagen", look, "colors");
      palette.append(rows[0], $("theme-presets"));
      const colorFields = rows.find((n) => n.querySelector("#th-bg"));
      palette.append(colorFields);
      const oldBrandRows = rows.filter((n) =>
        n.querySelector("#brand-logo,#th-wall-mode,#brand-note,#th-photo"),
      );
      const brandSection = this.section(
        "Name und Logo",
        this.panels.brand,
        "branding",
      );
      for (const n of oldBrandRows) {
        if (n.querySelector("#th-photo")) {
          const photo = $("th-photo").closest("label");
          photo.hidden = true;
          palette.append(photo);
          const grad = $("th-grad").closest("label");
          palette.append(grad);
          n.remove();
        } else if (n.id === "brand-note") {
          n.textContent =
            "Bilder bis 8 MB. Sie werden zunächst als Entwurf übernommen; erst „Änderungen speichern“ aktiviert sie dauerhaft.";
        } else brandSection.append(n);
      }
      const brandUpload = $("brand-logo")?.closest(".row");
      if (brandUpload && !brandSection.contains(brandUpload))
        brandSection.append(brandUpload);
      if ($("brand-note")) brandSection.append($("brand-note"));
      const bgOld = $("th-wall-mode").closest(".row");
      bgOld.hidden = true;
      this.panels.brand.append(bgOld);
      const basicFont = rows.find((n) => n.querySelector("#th-font")),
        oldLayout = rows.find((n) => n.querySelector("#th-layout")),
        oldCard = rows.find((n) => n.querySelector("#th-shadow"));
      const typography = this.section(
        "Schriften und Lesbarkeit",
        look,
        "typography",
      );
      typography.append(basicFont);
      const typographyGrid = el("div", { class: "ds-fields" });
      typography.append(typographyGrid);
      for (const role of roles)
        this.control("typography." + role, names[role], {}, typographyGrid);
      this.control(
        "typography.customFamily",
        "Name einer installierten Schrift",
        {
          help: "Zum Beispiel eine bereits auf deinem PC installierte Schrift. Oben „Eigene installierte Schrift“ auswählen.",
        },
        typographyGrid,
      );
      const fontTools = el(
        "div",
        { class: "row" },
        button("Schriftdatei hinzufügen", () => this.fontInput.click()),
      );
      this.fontInput = el("input", {
        type: "file",
        accept: ".woff2,.woff,.ttf,.otf",
        "aria-label": "Eigene Schriftdatei",
        hidden: true,
        onchange: this.action(async () => {
          const file = this.fontInput.files[0];
          this.fontInput.value = "";
          if (!file) return;
          if (this.d.fonts.length >= 12)
            throw Error("Höchstens zwölf Schriftdateien pro Design.");
          if (file.size > 4000000)
            throw Error("Die Schriftdatei ist größer als 4 MB.");
          const bytes = await file.arrayBuffer();
          const check = new FontFace("AHDesignValidation", bytes);
          await check.load().catch(() => {
            throw Error("Der Browser kann diese Schriftdatei nicht lesen.");
          });
          const result = await this.upload("font", new Blob([bytes]));
          if (!this.d.fonts.some((f) => f.file === result.file))
            this.d.fonts.push({
              file: result.file,
              name: file.name.replace(/\.[^.]+$/, ""),
            });
          this.d.typography.body = "asset:" + result.file;
          this.sync();
          this.record("font-upload");
          this.notice("Schrift als Vorschau übernommen.");
        }),
      });
      fontTools.append(this.fontInput);
      typography.append(
        fontTools,
        el("p", {
          class: "muted",
          text: "Eigene Schriftdateien bleiben auf diesem PC: WOFF2, WOFF, TTF oder OTF, höchstens 4 MB.",
        }),
      );
      this.fontList = el("div", { class: "ds-font-list" });
      typography.append(this.fontList);
      const perMenu = this.section("Schrift je Menü", look, "menufonts");
      perMenu.append(el("p", { class: "muted", text: "Camclient Script ist bereits mitgeliefert. Wähle die Grundschrift für die gesamte Oberfläche oder hier eine eigene Schrift für einzelne Menüs. Eine Menüschrift gilt für dessen Inhalt, Überschriften und Bedienelemente sowie seinen Eintrag in der Navigation. „Grundschrift übernehmen“ verwendet wieder das gemeinsame Design. Änderungen erscheinen sofort; dauerhaft übernehmen mit „Änderungen speichern“." }));
      const menuGrid = el("div", { class: "ds-fields" });
      perMenu.append(menuGrid);
      for (const [key, title] of this.ctx.walls)
        if (D.schema.fields["menuFonts." + key])
          this.control("menuFonts." + key, "Schrift: " + title, {}, menuGrid);
      perMenu.append(button("Alle Menüs auf gemeinsames Design zurücksetzen", () => {
        for (const key of Object.keys(this.d.menuFonts)) this.d.menuFonts[key] = "inherit";
        this.sync();
        this.record("menu-fonts-reset");
      }));
      const typeAdvanced = this.advanced(
        "Schriftgrößen und Feinabstimmung",
        typography,
      );
      for (const [path, label, unit, step] of [
        ["headingScale", "Überschriftengröße", " %"],
        ["navigationScale", "Menüschriftgröße", " %"],
        ["controlScale", "Schaltflächenschriftgröße", " %"],
        ["cardScale", "Kachelschriftgröße", " %"],
        ["lineHeight", "Zeilenhöhe", "", 0.05],
        ["letterSpacing", "Zeichenabstand", " px", 0.1],
      ])
        this.control("typography." + path, label, { unit, step }, typeAdvanced);
      this.control(
        "typography.weight",
        "Schriftgewicht",
        {
          values: [
            ["400", "Normal"],
            ["500", "Etwas kräftiger"],
            ["600", "Kräftig"],
          ],
        },
        typeAdvanced,
      );
      const surfaces = this.advanced("Weitere Farben und Flächen", palette);
      this.control("colors.input", "Eingabeflächen", {}, surfaces);
      this.control("colors.buttonText", "Text auf Akzentflächen", {}, surfaces);
      this.control(
        "colors.hover",
        "Menüauswahl und Darüberfahren",
        {},
        surfaces,
      );
      this.contrast = el("p", { class: "ds-contrast" });
      palette.append(this.contrast);
      const spacing = this.section("Layout und Abstände", look, "layout");
      spacing.append(oldLayout, oldCard);
      const legacyLayout = el("div", { class: "ds-fields" });
      for (const id of ["th-radius", "th-side"]) {
        const label = $(id).closest("label");
        label.classList.add("ds-field");
        legacyLayout.append(label);
      }
      spacing.append(legacyLayout);
      for (const [path, label, unit] of [
        ["contentWidth", "Maximale Inhaltsbreite", "width"],
        ["padding", "Innenabstand", " px"],
        ["controlHeight", "Höhe der Bedienelemente", " px"],
        ["maxColumns", "Höchstens Kacheln je Zeile", "columns"],
      ])
        this.control(
          "layout." + path,
          label,
          {
            unit,
            values:
              path === "contentWidth"
                ? [
                    [0, "Volle Breite"],
                    [960, "Schmal · 960 px"],
                    [1280, "Standard · 1280 px"],
                    [1600, "Breit · 1600 px"],
                    [1920, "Extra breit · 1920 px"],
                    [2560, "Sehr breit · 2560 px"],
                  ]
                : undefined,
          },
          spacing,
        );
      this.control(
        "layout.cardAlign",
        "Textausrichtung der Kacheln",
        {
          values: [
            ["left", "Links"],
            ["center", "Mittig"],
            ["right", "Rechts"],
          ],
        },
        spacing,
      );
      const access = this.section("Angenehm bedienen", look, "accessibility");
      this.control(
        "accessibility.motion",
        "Bewegungen der Oberfläche",
        {
          values: [
            ["system", "Systemeinstellung beachten"],
            ["off", "Animationen ausschalten"],
          ],
        },
        access,
      );
      this.control(
        "accessibility.highContrast",
        "Kontrastreiche Darstellung",
        {},
        access,
      );
      this.control(
        "accessibility.underlineLinks",
        "Links unterstreichen",
        {},
        access,
      );
      this.control(
        "accessibility.reduceTransparency",
        "Transparente Flächen vermeiden",
        {},
        access,
      );
      this.control(
        "accessibility.focusWidth",
        "Breite des Tastaturfokus",
        { unit: " px" },
        access,
      );
      this.buildBrand(brandSection);
      this.buildBackground();
      this.buildNavigation();
      this.buildProfiles();
      this.buildInformation();
      const listControls = this.section(
        "Eigene Kachelmaße",
        this.panels.lists,
        "customcards",
      );
      this.control(
        "layout.customCards",
        "Eigene Kachelmaße statt Größenstufen verwenden",
        {},
        listControls,
      );
      const customRow = $("th-card").closest(".row");
      listControls.append(customRow);
      $("th-card").max = "600";
      $("th-thumb").max = "500";
      $("th-card").title = "Wirkt bei aktivierten eigenen Kachelmaßen";
      $("th-thumb").title = $("th-card").title;
      const work = this.section(
        "Weitere Arbeitsbereiche",
        this.panels.live,
        "workspaces",
      );
      work.append(
        el("p", {
          text: "Multicam, Singlecam und Multitube besitzen eigene Wiedergabe- und Leistungsoptionen direkt am Arbeitsbereich.",
        }),
        button("Live-Bereich öffnen", () => this.ctx.open("live")),
        button("Multitube öffnen", () => this.ctx.openMulti()),
      );
      const restart = this.section(
        "Oberfläche neu starten",
        this.panels.tools,
        "restart",
      );
      restart.append($("restart-app").closest(".row"));
      $("restart-app").textContent = "Oberfläche neu starten";
      for (const panel of Object.values(this.panels)) {
        for (const child of [...panel.children])
          if (!child.classList.contains("ds-section")) {
            child.classList.add("ds-original-block");
          }
        panel.prepend(
          el("p", { class: "ds-description", text: panel.dataset.description }),
        );
      }
      for (const key of ["live", "models", "tools"])
        this.panels[key].insertBefore(
          el("p", {
            class: "ds-instant-note",
            text: "Die bestehenden Funktionen in diesem Bereich speichern ihre Änderungen direkt über ihre eigenen Schalter und Aktionen.",
          }),
          this.panels[key].children[1] || null,
        );
      this.saveButton = $("save-settings");
      this.saveButton.onclick = this.action(() => this.save());
      this.discard = button("Entwurf verwerfen", () => {
        this.history.push(this.capture());
        this.restore(this.saved);
        this.notice("Nicht gespeicherte Änderungen verworfen.");
      });
      this.undoButton = button("Letzte Änderung zurück", () => {
        const prev = this.history.pop();
        if (prev) this.restore(prev);
      });
      this.saveState = el("span", { class: "ds-save-state", role: "status" });
      const actions = el(
        "div",
        { class: "ds-savebar" },
        this.saveState,
        this.undoButton,
        this.discard,
        this.saveButton,
      );
      host.append(actions);
      const backups = this.section(
        "Zurücksetzen und gespeicherter Stand",
        this.panels.profiles,
        "reset",
      );
      $("reset-theme").onclick = () => this.resetPanel();
      backups.append(
        $("reset-theme"),
        button(
          "Gespeicherten Stand laden",
          this.action(() => this.reloadSaved()),
        ),
      );
      host.addEventListener("input", (e) => {
        if (
          e.target === this.searchInput ||
          e.target.closest(".ds-profile-name")
        )
          return;
        this.record(e.target.id || "legacy");
      });
      host.addEventListener("change", (e) => {
        if (
          e.target === this.searchInput ||
          e.target.closest(".ds-profile-name")
        )
          return;
        this.record(e.target.id || "legacy");
      });
      for (const range of host.querySelectorAll(
        'input[type=range]:not([id^="ds-"])',
      )) {
        const label = range.closest("label");
        if (!label) continue;
        const output = el("output", { class: "ds-value", htmlFor: range.id });
        const paint = () => {
          const units = {
            "th-scale": " px",
            "th-radius": " px",
            "th-side": " px",
            "th-gap": " px",
            "th-card": " px",
            "th-thumb": " px",
            "th-player": " vh",
          };
          output.textContent =
            range.id === "th-volume"
              ? Math.round(Number(range.value) * 100) + " %"
              : range.value + (units[range.id] || "");
        };
        range.addEventListener("input", paint);
        this.rangePainters.push(paint);
        label.append(output);
        paint();
      }
      this.search("");
    }
    buildBrand(parent) {
      const fields = el("div", { class: "ds-fields" });
      parent.append(fields);
      for (const [path, label] of [
        ["name", "Anzeigename"],
        ["tagline", "Unterzeile"],
        ["monogram", "Monogramm"],
        ["title", "Titel des Browserfensters"],
      ])
        this.control("brand." + path, label, {}, fields);
      this.control(
        "brand.mode",
        "Darstellung",
        {
          values: [
            ["legacy", "Bisheriges Logo / Standard"],
            ["text", "Nur eigener Name"],
            ["logo", "Nur Logo"],
            ["both", "Logo und Name"],
            ["monogram", "Monogramm und Name"],
          ],
        },
        fields,
      );
      const favicon = el("input", {
        type: "file",
        accept: "image/png,image/jpeg,image/webp,image/gif",
        "aria-label": "Eigenes Browser-Icon",
        hidden: true,
        onchange: this.action(async () => {
          const file = favicon.files[0];
          favicon.value = "";
          if (file) {
            const result = await this.upload("image", file);
            this.d.brand.favicon = result.file;
            this.record("favicon");
          }
        }),
      });
      parent.append(
        el(
          "div",
          { class: "row" },
          button("Browser-Icon vom PC", () => favicon.click()),
          button("Browser-Icon zurücksetzen", () => {
            this.d.brand.favicon = "";
            this.record("favicon");
          }),
          favicon,
        ),
      );
      const advanced = this.advanced("Logogröße und Ausschnitt", parent);
      for (const [path, label] of [
        ["width", "Logobreite"],
        ["height", "Logohöhe"],
        ["padding", "Logo-Innenabstand"],
        ["positionX", "Logo horizontal"],
        ["positionY", "Logo vertikal"],
      ])
        this.control(
          "brand." + path,
          label,
          { unit: path.startsWith("position") ? " %" : " px" },
          advanced,
        );
      this.control(
        "brand.fit",
        "Logo einpassen",
        {
          values: [
            ["contain", "Vollständig anzeigen"],
            ["cover", "Fläche ausfüllen"],
            ["fill", "Strecken"],
            ["scale-down", "Nur verkleinern"],
          ],
        },
        advanced,
      );
      this.control(
        "brand.shape",
        "Logoform",
        {
          values: [
            ["natural", "Originalform"],
            ["rounded", "Abgerundet"],
            ["circle", "Kreis / Oval"],
            ["square", "Eckig"],
          ],
        },
        advanced,
      );
      this.control(
        "brand.background",
        "Fläche hinter dem Logo",
        {
          values: [
            ["transparent", "Transparent"],
            ["panel", "Flächenfarbe"],
            ["accent", "Akzentfarbe"],
            ["white", "Weiß"],
            ["black", "Schwarz"],
          ],
        },
        advanced,
      );
      const sites = this.section(
        "Anbieterlogos ersetzen",
        this.panels.brand,
        "providerlogos",
      );
      const filter = el("input", {
          type: "search",
          placeholder: "Anbieter suchen …",
          "aria-label": "Anbieter für eigenes Logo suchen",
        }),
        picker = el("select", { "aria-label": "Anbieter für eigenes Logo" });
      this.sitePicker = picker;
      const draw = () => {
        const selected = picker.value,
          q = filter.value.toLowerCase();
        picker.replaceChildren(
          ...this.ctx.state.catalog.sites
            .filter((s) => [s.id, s.title].join(" ").toLowerCase().includes(q))
            .slice(0, 600)
            .map((s) => el("option", { value: s.id, text: s.title ,"data-i18n-content":""})),
        );
        if ([...picker.options].some((o) => o.value === selected))
          picker.value = selected;
        this.paintSitePreview();
      };
      filter.oninput = draw;
      picker.onchange = () => this.paintSitePreview();
      draw();
      this.siteLogoPreview = el("img", {
        class: "brand-preview",
        alt: "Logo des ausgewählten Anbieters",
      });
      this.siteLogoNote = el("small");
      const file = el("input", {
        type: "file",
        accept: "image/*",
        "aria-label": "Eigenes Anbieterlogo",
        hidden: true,
        onchange: this.action(async () => {
          const f = file.files[0],
            site = picker.value;
          file.value = "";
          if (!site || !f) return;
          const result = await this.upload("image", f);
          this.d.siteLogos[site] = result.file;
          this.record("site-logo");
        }),
      });
      sites.append(
        el("p", {
          text: "Ersetzt die Logos in der Anbieterübersicht. Die Anbieter und ihre Funktionen bleiben gleich.",
        }),
        filter,
        picker,
        el("div", { class: "row" }, this.siteLogoPreview, this.siteLogoNote),
        el(
          "div",
          { class: "row" },
          button("Logo für diesen Anbieter wählen", () => file.click()),
          button("Original dieses Anbieters verwenden", () => {
            delete this.d.siteLogos[picker.value];
            this.record("site-logo");
          }),
          file,
        ),
      );
    }
    buildBackground() {
      const parent = this.section(
        "Hintergrund gestalten",
        this.panels.brand,
        "background",
      );
      const selector = el("select", {
        "aria-label": "Hintergrund bearbeiten für",
        onchange: () => {
          this.target = selector.value;
          this.syncBackground();
          this.paintAssets();
        },
      });
      selector.append(
        el("option", {
          value: "all",
          text: "Alle Bereiche – gemeinsamer Hintergrund",
        }),
      );
      for (const [id, label] of this.ctx.walls)
        selector.append(el("option", { value: id, text: label }));
      parent.append(
        el(
          "label",
          { class: "ds-field" },
          el("span", { text: "Bearbeiten für" }),
          selector,
        ),
        el("p", {
          text: "Ein eigener Bereich kann den gemeinsamen Hintergrund übernehmen oder abweichend gestaltet werden.",
        }),
      );
      this.backgroundTarget = selector;
      const grid = el("div", { class: "ds-fields" });
      parent.append(grid);
      const bgControl = (key, label, options = {}, place = grid) =>
        this.control(
          key,
          label,
          { ...options, background: true, rule: D.schema.background[key] },
          place,
        );
      bgControl("mode", "Hintergrundart", {
        values: [
          ["legacy", "Bisheriger Hintergrund"],
          ["inherit", "Gemeinsamen Hintergrund übernehmen"],
          ["color", "Einfarbig"],
          ["gradient", "Farbverlauf"],
          ["image", "Eigenes Bild"],
        ],
      });
      bgControl("color", "Grundfarbe");
      bgControl("start", "Verlauf von");
      bgControl("end", "Verlauf bis");
      bgControl("angle", "Verlaufsrichtung", { unit: " °" });
      bgControl("url", "Bildadresse (optional)", {
        help: "Alternativ zum Bild vom PC. Leere Adresse entfernt nur den externen Link.",
      });
      const row = el(
        "div",
        { class: "row" },
        $("brand-wall"),
        $("brand-wall-clear"),
        $("brand-wall-preview"),
      );
      this.backgroundButtons = row;
      parent.append(row);
      const advanced = this.advanced("Bildanpassung und Lesbarkeit", parent);
      bgControl(
        "fit",
        "Bild einpassen",
        {
          values: [
            ["cover", "Fläche ausfüllen"],
            ["contain", "Vollständiges Bild"],
            ["stretch", "Strecken"],
            ["original", "Originalgröße"],
            ["tile", "Bild kacheln"],
          ],
        },
        advanced,
      );
      for (const [key, label, unit] of [
        ["x", "Horizontaler Bildausschnitt", " %"],
        ["y", "Vertikaler Bildausschnitt", " %"],
        ["zoom", "Bildzoom", " %"],
        ["opacity", "Bilddeckkraft", " %"],
        ["dim", "Abdunklung", " %"],
        ["blur", "Hintergrundunschärfe", " px"],
        ["panelOpacity", "Deckkraft der Bedienflächen", " %"],
      ])
        bgControl(key, label, { unit }, advanced);
      bgControl("fixed", "Hintergrund beim Scrollen festhalten", {}, advanced);
      this.backgroundNote = el("p", { class: "ds-asset-note" });
      parent.append(this.backgroundNote);
    }
    bg() {
      if (this.target === "all") return this.d.backgrounds.all;
      return (this.d.backgrounds.pages[this.target] ||= D.background({
        mode: "inherit",
      }));
    }
    syncBackground() {
      const bg =
        this.target === "all"
          ? this.d.backgrounds.all
          : this.d.backgrounds.pages[this.target] ||
            D.background({ mode: "inherit" });
      for (const c of this.bgControls.values()) {
        const v = bg[c.path];
        if (c.node.type === "checkbox") c.node.checked = !!v;
        else c.node.value = String(v);
        c.output.textContent = this.display(v, c.rule, c.unit);
      }
      this.backgroundVisibility();
      if (this.backgroundNote)
        this.backgroundNote.textContent =
          bg.mode === "image" && !bg.image && !bg.url
            ? "Noch kein Bild ausgewählt. Die Grundfarbe bleibt sichtbar."
            : this.target !== "all" && bg.mode === "inherit"
              ? "Dieser Bereich übernimmt den gemeinsamen Hintergrund."
              : "";
    }
    backgroundVisibility() {
      const b =
          this.target === "all"
            ? this.d.backgrounds.all
            : this.d.backgrounds.pages[this.target] ||
              D.background({ mode: "inherit" }),
        mode = b.mode;
      for (const c of this.bgControls.values()) {
        let show = true;
        if (["start", "end", "angle"].includes(c.path))
          show = mode === "gradient";
        if (
          [
            "url",
            "fit",
            "x",
            "y",
            "zoom",
            "opacity",
            "dim",
            "blur",
            "fixed",
          ].includes(c.path)
        )
          show = mode === "image";
        if (c.path === "color") show = mode === "color" || mode === "image";
        if (c.path === "panelOpacity") show = mode !== "inherit";
        c.node.closest(".ds-field").hidden = !show;
      }
      if (this.backgroundButtons)
        this.backgroundButtons.hidden = mode !== "image";
    }
    buildNavigation() {
      const parent = this.section(
        "Reihenfolge und Symbole",
        this.panels.menu,
        "navigation",
      );
      this.menuRows = el("div", { class: "ds-menu-rows" });
      parent.append(
        el("p", {
          text: "Mit den Pfeilen sortieren. Eigene Symbole oder kleine Bilder helfen beim Wiedererkennen. Einstellungen bleiben immer erreichbar.",
        }),
        this.menuRows,
      );
      this.renderMenuRows();
    }
    renderMenuRows() {
      if (!this.menuRows) return;
      for (const id of ["menu-toggles", "menu-labels"]) $(id).hidden = true;
      const order = [
        ...new Set([
          ...this.d.menuOrder,
          ...D.schema.menus.filter((k) => k !== "settings"),
        ]),
      ];
      this.menuRows.replaceChildren();
      for (const [id, label] of order
        .map((id) => this.ctx.menus.find((m) => m[0] === id))
        .filter(Boolean)) {
        const icon = this.d.menuIcons[id] || {},
          stockVisible = document.querySelector(
            '#menu-toggles input[value="' + id + '"]',
          ),
          stockName = document.querySelector(
            '#menu-labels input[data-id="' + id + '"]',
          );
        const visible = el("input", {
          type: "checkbox",
          checked: stockVisible.checked,
          "aria-label": label + " im Menü anzeigen",
          onchange: () => {
            stockVisible.checked = visible.checked;
            this.record("menu-visible-" + id);
          },
        });
        const name = el("input", {
          value: stockName.value,
          placeholder: label,
          maxLength: 40,
          "aria-label": "Menüname für " + label,
          oninput: () => {
            stockName.value = name.value;
            this.record("menu-name-" + id);
          },
        });
        const symbol = el("input", {
          value: icon.symbol || "",
          maxLength: 8,
          placeholder: "Symbol",
          "aria-label": "Symbol für " + label,
          oninput: () => {
            this.d.menuIcons[id] = {
              ...this.d.menuIcons[id],
              symbol: symbol.value,
              image: "",
            };
            this.record("menu-symbol-" + id);
          },
        });
        const file = el("input", {
          type: "file",
          accept: "image/*",
          hidden: true,
          "aria-label": "Menübild für " + label,
          onchange: this.action(async () => {
            const f = file.files[0];
            file.value = "";
            if (!f) return;
            const result = await this.upload("image", f);
            this.d.menuIcons[id] = {
              ...this.d.menuIcons[id],
              image: result.file,
            };
            this.record("menu-icon-" + id);
          }),
        });
        const move = (delta) => {
          const n = order.indexOf(id),
            at = Math.max(0, Math.min(order.length - 1, n + delta));
          [order[n], order[at]] = [order[at], order[n]];
          this.d.menuOrder = order;
          this.renderMenuRows();
          this.record("menu-order");
        };
        this.menuRows.append(
          el(
            "div",
            { class: "ds-menu-row" },
            el(
              "label",
              { class: "ds-menu-visible" },
              visible,
              el("span", { text: label }),
            ),
            name,
            symbol,
            button("↑", () => move(-1), {
              "aria-label": label + " nach oben",
              disabled: order.indexOf(id) === 0,
            }),
            button("↓", () => move(1), {
              "aria-label": label + " nach unten",
              disabled: order.indexOf(id) === order.length - 1,
            }),
            button("Bild", () => file.click(), {
              "aria-label": "Bild für " + label,
            }),
            button("Original", () => {
              delete this.d.menuIcons[id];
              stockName.value = "";
              stockVisible.checked = true;
              this.renderMenuRows();
              this.record("menu-original-" + id);
            }),
            file,
          ),
        );
      }
    }
    buildProfiles() {
      const parent = this.section(
        "Eigene Designprofile",
        this.panels.profiles,
        "profiles",
      );
      this.profileName = el("input", {
        class: "ds-profile-name",
        placeholder: "Zum Beispiel Kino, Hell oder Große Schrift",
        "aria-label": "Name des Designprofils",
        maxLength: 80,
      });
      this.profileList = el("div", { class: "ds-profile-list" });
      parent.append(
        el("p", {
          text: "Profile speichern Farben, Schriften, Logo, Hintergründe und Layout. Medien, Notizen, Konten und Schlüssel sind nicht enthalten.",
        }),
        this.profileName,
        button(
          "Aktuelle Vorschau als Profil vormerken",
          this.action(() => {
            const name = this.profileName.value.trim();
            if (!name) throw Error("Bitte dem Designprofil einen Namen geben.");
            if (this.d.profiles.length >= 24)
              throw Error("Höchstens 24 Designprofile.");
            this.d.profiles.push({
              id: crypto.randomUUID(),
              name,
              design: D.normalize(this.d, false),
              appearance: D.appearance(this.ctx.themeNow()),
            });
            this.profileName.value = "";
            this.renderProfiles();
            this.record("profile");
          }),
        ),
        this.profileList,
      );
      const backup = this.section(
        "Design sichern und übertragen",
        this.panels.profiles,
        "backup",
      );
      const file = el("input", {
        type: "file",
        accept: ".json,application/json",
        "aria-label": "Designsicherung importieren",
        onchange: this.action(async () => {
          const f = file.files[0];
          file.value = "";
          if (!f) return;
          if (f.size > 190000000)
            throw Error("Diese Sicherung ist größer als 190 MB.");
          this.importPreview(JSON.parse(await f.text()));
        }),
      });
      backup.append(
        el("p", {
          text: "Die Sicherung enthält eigene Bilder und Schriftdateien. Importierte Einstellungen erscheinen zunächst als Vorschau.",
        }),
        button(
          "Design mit Dateien exportieren",
          this.action(() => this.exportDesign()),
        ),
        el(
          "label",
          { class: "ds-field" },
          el("span", { text: "Designsicherung importieren" }),
          file,
        ),
      );
    }
    renderProfiles() {
      if (!this.profileList) return;
      this.profileList.replaceChildren();
      for (const p of this.d.profiles)
        this.profileList.append(
          el(
            "div",
            { class: "ds-profile-row" },
            el("strong", { text: p.name ,"data-i18n-content":""}),
            button("Vorschau", () => {
              const profiles = clone(this.d.profiles),
                theme = {
                  ...this.ctx.themeNow(),
                  ...p.appearance,
                  design: { ...clone(p.design), profiles },
                };
              this.ctx.fillThemeForm(theme);
              this.ctx.applyTheme(theme);
              this.record("profile-apply");
            }),
            button("Umbenennen", () => {
              const { dialog, body } = this.dialog("Profil umbenennen"),
                name = el("input", {
                  value: p.name,
                  "aria-label": "Neuer Profilname",
                  maxLength: 80,
                });
              body.append(
                name,
                button("Übernehmen", () => {
                  if (!name.value.trim()) return;
                  p.name = name.value.trim();
                  this.renderProfiles();
                  this.record("profile-rename");
                  dialog.close();
                }),
              );
            }),
            button("Entfernen", () => {
              this.d.profiles = this.d.profiles.filter((x) => x.id !== p.id);
              this.renderProfiles();
              this.record("profile-remove");
            }),
          ),
        );
      if (!this.d.profiles.length)
        this.profileList.append(
          el("p", { text: "Noch keine eigenen Profile vorgemerkt." }),
        );
    }
    sync() {
      for (const paint of this.rangePainters) paint();
      for (const c of this.controls.values()) {
        if (c.rule.type === "font") {
          const current = D.get(this.d, c.path);
          c.node.replaceChildren(
            ...this.fontOptions().map(([v, t]) =>
              el("option", { value: v, text: t }),
            ),
          );
          c.node.value = current;
        }
        const v = D.get(this.d, c.path);
        if (
          c.node.tagName === "SELECT" &&
          c.rule.type === "number" &&
          ![...c.node.options].some((o) => o.value === String(v))
        )
          c.node.append(
            el("option", { value: String(v), text: String(v) + " px" }),
          );
        if (c.node.type === "checkbox") c.node.checked = !!v;
        else c.node.value = String(v);
        c.output.textContent = this.display(v, c.rule, c.unit);
      }
      this.syncBackground();
      this.renderProfiles();
      this.renderMenuRows();
      if (this.fontList) {
        this.fontList.replaceChildren();
        for (const f of this.d.fonts)
          this.fontList.append(
            el(
              "div",
              { class: "ds-font-row" },
              el("span", { text: f.name ,"data-i18n-content":""}),
              button("Schrift entfernen", () => {
                this.d.fonts = this.d.fonts.filter((x) => x.file !== f.file);
                for (const role of roles)
                  if (this.d.typography[role] === "asset:" + f.file)
                    this.d.typography[role] = "inherit";
                for (const key of Object.keys(this.d.menuFonts))
                  if (this.d.menuFonts[key] === "asset:" + f.file)
                    this.d.menuFonts[key] = "inherit";
                this.sync();
                this.record("font-remove");
              }),
            ),
          );
      }
      this.paintAssets();
    }
    load(raw) {
      this.d = D.normalize(raw);
      this.sync();
    }
    async upload(kind, file, expected = "") {
      const data = await new Promise((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve(String(r.result).split(",")[1]);
        r.onerror = () =>
          reject(Error("Die Datei konnte nicht gelesen werden."));
        r.readAsDataURL(file);
      });
      const response = await fetch("/api/design-asset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, data, expected }),
      });
      const result = await response.json();
      if (!response.ok || !result.ok)
        throw Error(
          result.error || "Die Designdatei konnte nicht gespeichert werden.",
        );
      return result;
    }
    async uploadBrand(slot, file) {
      if (file.size > 8000000) throw Error("Das Bild ist größer als 8 MB.");
      const result = await this.upload("image", file);
      if (slot === "logo") {
        this.d.brand.logo = result.file;
        this.d.brand.mode = "both";
      } else {
        const bg = this.bg();
        bg.image = result.file;
        bg.mode = "image";
      }
      this.sync();
      this.record("image-upload");
      this.notice(
        "Bild als Vorschau übernommen. Zum Behalten die Änderungen speichern.",
      );
    }
    clearBrand(slot) {
      if (slot === "logo") {
        this.d.brand.logo = "";
        this.d.brand.mode = "text";
      } else {
        const bg = this.bg();
        bg.image = "";
        bg.url = "";
        bg.mode = "color";
      }
      this.sync();
      this.record("image-clear");
    }
    paintAssets() {
      const theme = this.ctx.themeNow(),
        logo = $("brand-logo-preview"),
        wall = $("brand-wall-preview");
      if (!logo || !wall) return;
      const logoURL = this.d.brand.logo
        ? assetURL(this.d.brand.logo)
        : theme.logo && this.d.brand.mode === "legacy"
          ? this.ctx.brandSrc(theme.logo, theme.logoStamp)
          : "";
      logo.hidden = !logoURL;
      logo.classList.toggle("hidden", !logoURL);
      if (logoURL && logo.getAttribute("src") !== logoURL) logo.src = logoURL;
      const b =
          this.target === "all"
            ? this.d.backgrounds.all
            : this.d.backgrounds.pages[this.target] ||
              D.background({ mode: "inherit" }),
        legacy = theme.walls?.[this.target],
        wallURL = b.image
          ? assetURL(b.image)
          : b.url ||
            (legacy &&
              this.ctx.brandSrc(legacy, theme.wallStamps?.[this.target])) ||
            "";
      wall.hidden = !wallURL;
      wall.classList.toggle("hidden", !wallURL);
      if (wallURL && wall.getAttribute("src") !== wallURL) wall.src = wallURL;
      const n = $("brand-note");
      if (n)
        n.textContent =
          "Bilder bis 8 MB. Änderungen bleiben eine Vorschau, bis du sie speicherst. Entfernen löscht keine Bilder aus anderen Designprofilen.";
    }
    search(q) {
      const query = q.trim().toLocaleLowerCase();
      let count = 0;
      for (const [key, panel] of Object.entries(this.panels)) {
        let matches = false;
        for (const child of [...panel.children]) {
          if (child.classList.contains("ds-description")) continue;
          const text = [
            child.textContent,
            ...[...child.querySelectorAll("input,select")].map(
              (n) => n.getAttribute("aria-label") || n.placeholder || "",
            ),
          ]
            .join(" ")
            .toLocaleLowerCase();
          const match = !query || text.includes(query);
          child.hidden = !!query && !match;
          if (query && match) {
            matches = true;
            count++;
            for (const d of child.querySelectorAll("details")) {
              if (!this.searchDetails) this.searchDetails = new Map();
              if (!this.searchDetails.has(d)) this.searchDetails.set(d, d.open);
              d.open = true;
            }
          }
        }
        panel.classList.toggle(
          "hidden",
          query ? !matches : key !== this.category,
        );
      }
      if (!query && this.searchDetails) {
        for (const [d, open] of this.searchDetails) d.open = open;
        this.searchDetails = null;
      }
      for (const tab of $("set-tabs").querySelectorAll("button")) {
        const active = tab.id === "ds-tab-" + this.category && !query;
        tab.classList.toggle("primary", active);
        tab.setAttribute("aria-selected", String(active));
        tab.tabIndex = active ? 0 : -1;
        tab.onkeydown = (e) => {
          const tabs = [...$("set-tabs").querySelectorAll("button")],
            index = tabs.indexOf(tab),
            next =
              e.key === "ArrowDown" || e.key === "ArrowRight"
                ? tabs[(index + 1) % tabs.length]
                : e.key === "ArrowUp" || e.key === "ArrowLeft"
                  ? tabs[(index - 1 + tabs.length) % tabs.length]
                  : null;
          if (next) {
            e.preventDefault();
            next.click();
            next.focus();
          }
        };
      }
      this.results.hidden = !query;
      this.results.textContent = query
        ? count
          ? count + " passende Einstellungsgruppen"
          : "Keine passende Einstellung gefunden. Bitte einen anderen Begriff versuchen."
        : " ";
    }
    preview() {
      if (!this.previewBox) return;
      const theme = this.ctx.themeNow(),
        b = this.d.brand,
        ratio = D.contrast(theme.text, theme.panel);
      this.previewBox.replaceChildren(
        el("small", { text: "Live-Vorschau" }),
        el("strong", {
          class: "ds-preview-heading",
          text: b.mode === "legacy" ? "Adult Client" : b.name || "Dein Name",
        }),
        el("p", { text: "So wirken Schrift und Farben." }),
        el(
          "div",
          { class: "ds-preview-card" },
          el("strong", { text: "Ein Beispiel für einen Videotitel" }),
          el("small", { text: "Anbieter · 12:34" }),
        ),
        button("Beispiel", () => {}, {
          class: "primary",
          tabIndex: -1,
          "aria-hidden": "true",
        }),
      );
      if (this.contrast)
        this.contrast.textContent =
          "Text auf Fläche: " +
          ratio.toLocaleString(globalThis.AppI18n?.locale() || "de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) +
          ":1 · " +
          (ratio >= 4.5 ? "gut lesbar" : "Kontrast erhöhen empfohlen");
      this.previewBox.style.fontFamily = fontFamily(
        this.d.typography.body,
        this.d,
        theme.font,
      );
    }
    dialog(title) {
      const dialog = el("dialog", { class: "ds-dialog" }),
        body = el("div", { class: "ds-dialog-body" });
      dialog.append(
        el(
          "header",
          {},
          el("h2", { text: title }),
          button("Schließen", () => dialog.close()),
        ),
        body,
      );
      document.body.append(dialog);
      dialog.onclose = () => dialog.remove();
      dialog.showModal();
      return { dialog, body };
    }
    resetPanel() {
      const { dialog, body } = this.dialog("Design als Vorschau zurücksetzen");
      body.append(
        el("p", {
          text: "Wähle den Teil, den du zurücksetzen möchtest. Erst Speichern übernimmt ihn dauerhaft. „Letzte Änderung zurück“ holt die Vorschau zurück.",
        }),
      );
      for (const [key, label] of [
        ["colors", "Farben"],
        ["typography", "Schriften"],
        ["brand", "Name und Logo"],
        ["backgrounds", "Hintergründe"],
        ["layout", "Layout"],
        ["accessibility", "Bedienhilfen"],
        ["all", "Gesamtes Design"],
      ])
        body.append(
          button(label, () => {
            const defaults = D.normalize({}),
              theme = this.ctx.themeNow();
            if (key === "all") {
              const profiles = this.d.profiles;
              this.d = defaults;
              this.d.profiles = profiles;
              this.d.brand.mode = "text";
              this.d.backgrounds.all.mode = "color";
              Object.assign(theme, D.appearance({}));
            } else {
              this.d[key] = clone(defaults[key]);
              if (key === "typography") this.d.menuFonts = clone(defaults.menuFonts);
              if (key === "brand") this.d.brand.mode = "text";
              if (key === "backgrounds") this.d.backgrounds.all.mode = "color";
              if (key === "layout")
                for (const name of [
                  "radius",
                  "side",
                  "card",
                  "thumb",
                  "layout",
                  "density",
                  "gap",
                  "lines",
                  "shadow",
                  "lift",
                ])
                  theme[name] = D.schema.appearance[name];
              if (key === "colors")
                for (const k of [
                  "bg",
                  "panel",
                  "aside",
                  "line",
                  "text",
                  "muted",
                  "accent",
                  "grad2",
                  "grad",
                  "cardbg",
                ])
                  theme[k] = D.schema.appearance[k];
              if (key === "typography") {
                theme.font = "Segoe UI";
                theme.scale = 16;
              }
            }
            theme.design = this.d;
            this.ctx.fillThemeForm(theme);
            this.ctx.applyTheme(theme);
            this.record("reset");
            dialog.close();
          }),
        );
    }
    async exportDesign() {
      this.notice(
        "Design und Dateien werden für die Sicherung zusammengestellt …",
      );
      const design = D.normalize(this.d),
        appearance = D.appearance(this.ctx.themeNow()),
        assets = {};
      const old = this.ctx.themeNow();
      const adopt = async (url, apply) => {
        const response = await fetch(url);
        if (!response.ok)
          throw Error(
            "Ein bisheriges Designbild fehlt. Bitte das Bild neu auswählen.",
          );
        const blob = await response.blob(),
          result = await this.upload("image", blob);
        apply(result.file);
      };
      if (design.brand.mode === "legacy" && old.logo)
        await adopt(this.ctx.brandSrc(old.logo, old.logoStamp), (file) => {
          design.brand.logo = file;
          design.brand.mode = "logo";
        });
      for (const [key, file] of Object.entries(old.walls || {})) {
        const bg =
          key === "all"
            ? design.backgrounds.all
            : (design.backgrounds.pages[key] ||= D.background({
                mode: "legacy",
              }));
        if (bg.mode === "legacy")
          await adopt(
            this.ctx.brandSrc(file, old.wallStamps?.[key]),
            (asset) => {
              bg.image = asset;
              bg.mode = "image";
            },
          );
      }
      for (const file of D.refs(design)) {
        const response = await fetch(assetURL(file));
        if (!response.ok) throw Error("Eine Designdatei fehlt: " + file);
        const blob = await response.blob();
        assets[file] = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(",")[1]);
          reader.onerror = reject;
          reader.readAsDataURL(blob);
        });
      }
      const payload = {
        kind: "adult-client-design",
        version: 1,
        appearance,
        design,
        assets,
      };
      const url = URL.createObjectURL(
          new Blob([JSON.stringify(payload, null, 2)], {
            type: "application/json",
          }),
        ),
        a = el("a", { href: url, download: "Adult Client-Design.json" });
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      this.notice("Design mit Bildern und Schriftdateien exportiert.");
    }
    importPreview(payload) {
      if (!["adult-client-design", "adulthideout-design"].includes(payload?.kind) || payload.version !== 1)
        throw Error("Keine unterstützte Designsicherung.");
      const design = D.normalize(payload.design),
        appearance = D.appearance(payload.appearance),
        refs = D.refs(design),
        assets = payload.assets || {};
      if (refs.size > 20000)
        throw Error("Die Sicherung enthält zu viele Dateien.");
      let total = 0;
      for (const file of refs) {
        const data = assets[file];
        if (data != null) {
          if (typeof data !== "string" || !/^[A-Za-z0-9+/]*={0,2}$/.test(data))
            throw Error("Eine Datei in der Sicherung ist beschädigt.");
          total += data.length;
          if (data.length > 11000000)
            throw Error("Eine Designdatei ist zu groß.");
        }
      }
      if (total > 180000000)
        throw Error("Die eingebetteten Designdateien sind zusammen zu groß.");
      const { dialog, body } = this.dialog("Designimport prüfen");
      body.append(
        el("p", {
          text: `${design.profiles.length} Designprofile · ${design.fonts.length} Schriftdateien · ${refs.size} Bild-/Schriftverweise. Der bisher gespeicherte Stand bleibt erhalten, bis du die Vorschau speicherst.`,
        }),
        button(
          "Als Entwurf übernehmen",
          this.action(async () => {
            for (const file of refs) {
              if (assets[file] != null) {
                const bytes = Uint8Array.from(atob(assets[file]), (c) =>
                  c.charCodeAt(0),
                );
                await this.upload(
                  D.font(file) ? "font" : "image",
                  new Blob([bytes]),
                  file,
                );
              } else {
                const result = await fetch(assetURL(file));
                if (!result.ok)
                  throw Error("In der Sicherung fehlt eine benötigte Datei.");
              }
            }
            const next = { ...this.ctx.themeNow(), ...appearance, design };
            this.ctx.fillThemeForm(next);
            this.ctx.applyTheme(next);
            this.record("import");
            dialog.close();
            this.notice(
              "Design als Vorschau übernommen. Zum Behalten die Änderungen speichern.",
            );
          }),
        ),
      );
    }
    openCategory(key) {
      this.category = key;
      this.searchInput.value = "";
      this.search("");
      this.ctx.category?.(key);
      this.panels[key].scrollIntoView({ block: "start", behavior: "auto" });
    }
    buildInformation() {
      const project = this.section("Adult Client", this.panels.about, "project");
      project.append(
        el("p", { class: "ds-project-credit", text: "Ein Projekt von emberhost" }),
        el("p", { text: "Adult Client ist deine lokale Medienoberfläche für Windows: Anbieter durchsuchen, Videos und Bilder ansehen, Models entdecken, Live-Räume organisieren und eigene Sammlungen verwalten." }),
        el("p", { text: "Entwicklungsstand: lokale Entwicklungsversion. Die Anwendung läuft auf deinem Computer; Inhalte und Verfügbarkeit stammen von den jeweiligen Anbietern." }),
        button("Bedienungsanleitung öffnen", () => this.openCategory("help")),
      );
      const storage = this.section("Deine Daten und Einstellungen", this.panels.about, "project-storage");
      storage.append(
        el("p", { text: "Favoriten, Sammlungen, Einstellungen, Modelinformationen und bestätigte Website-Sitzungen werden lokal gespeichert. Einige Arbeitsbereiche und Nutzungsdaten liegen im verwendeten Browserprofil. Hintergrundpflege benötigt für neue Informationen eine Internetverbindung." }),
        el("p", { text: "Ein Designexport sichert die Gestaltung mit eigenen Bildern und Schriften. Er ersetzt keine vollständige Sicherung deiner Medienbibliothek, Nutzungsdaten oder Kontoverbindungen. Die jeweiligen Bereiche bieten eigene Exporte." }),
      );
      const origins = this.section("Bestandteile und Herkunft", this.panels.about, "project-origins");
      origins.append(
        el("p", { text: "Projektname: Adult Client · Projektersteller: emberhost. Die Oberfläche verwendet bestehende Anbieteradapter des AdultHideout-Kodi-Addons sowie die Schrift Camclient Script und Originalsymbole der Cam-Anbieter aus der übergebenen Erweiterung." }),
        el("p", { text: "Die ursprünglichen Lizenz-, Urheber- und Herkunftsangaben der eingebundenen Bestandteile bleiben in deren Quelldateien erhalten. Technische Addonkennungen und ältere Sicherungsformate werden für vorhandene Daten weiterhin unterstützt." }),
      );
      const topics = [
        ["Schnellstart und Navigation", "Wähle links einen Bereich. Unter „Seiten“ suchst du nach Anbietern und öffnest deren Inhalte. Die globale Suche durchsucht mehrere Quellen. Favoriten und Sammlungen helfen dir, Inhalte wiederzufinden. Die Einstellungssuche oben findet Optionen und diese Anleitung über alle Einstellungsbereiche hinweg.", "menu"],
        ["Schrift für alle Menüs oder einzelne Bereiche", "Unter „Farben & Schriften“ wählst du bei „Grundschrift“ die gemeinsame Schrift, einschließlich Camclient Script. Überschriften, Menüschrift, Schaltflächen, Kacheltitel und Namenszug können davon abweichen. Unter „Schrift je Menü“ gibst du einzelnen Bereichen eine eigene Schrift. Die Auswahl gilt dort auch für Überschriften und Schaltflächen. „Grundschrift übernehmen“ entfernt die Menüausnahme. Über „Alle Menüs auf gemeinsames Design zurücksetzen“ entfernst du alle Ausnahmen. Eigene Schriftdateien lassen sich zusätzlich vom PC laden.", "look"],
        ["Vorschau, Speichern, Verwerfen und mehrere Fenster", "Designänderungen erscheinen sofort als Vorschau. „Änderungen speichern“ übernimmt sie dauerhaft. „Entwurf verwerfen“ stellt den zuletzt bestätigten Stand wieder her; „Letzte Änderung zurück“ nimmt einen Bearbeitungsschritt zurück. Ein offener Entwurf bleibt in diesem Browserfenster beim Neuladen erhalten. Bei einem Speicherkonflikt mit einem anderen Fenster sichere deinen Entwurf als Designexport oder lade bewusst den gespeicherten Stand.", "profiles"],
        ["Farben, Größen und Bedienhilfen", "Unter „Farben & Schriften“ findest du Paletten, freie Farben, Schriftgrößen, Zeilenhöhe, Abstände, Inhaltsbreite und Dichte. Bedienhilfen bieten kräftigen Tastaturfokus, höhere Kontraste, unterstrichene Links und weniger Animationen. Du kannst mit Tab durch Schaltflächen und Eingaben wechseln.", "look"],
        ["Name, Logos und Hintergründe", "Unter „Logo & Hintergrund“ passt du Namenszug, Unterzeile, Monogramm, Browser-Titel und Logo an. Bilder können lokal geladen werden. Hintergründe lassen sich für alle Bereiche oder getrennt je Menü festlegen. Ein Menü mit „Übernehmen“ folgt dem gemeinsamen Hintergrund. Lokale Dateien funktionieren unabhängig von externen Bildadressen.", "brand"],
        ["Menüpunkte und Startseite", "Unter „Navigation & Start“ wählst du sichtbare Menüs, Namen, Symbole, Reihenfolge und Startansicht. Einstellungen bleiben erreichbar. Ausgeblendete Menüs löschen keine Inhalte. Menüschriften werden getrennt unter „Farben & Schriften“ festgelegt.", "menu"],
        ["Anbieter, Sortierung und Filter", "Unter „Seiten“ filterst und sortierst du Anbieter. In Listen bestimmen die angebotenen Filter und Sortierungen die angezeigten Inhalte. Die verfügbaren Inhalte und Angaben hängen von der jeweiligen Quelle ab; ein Suchwort muss nicht bei jedem Anbieter dieselben Treffer liefern.", "lists"],
        ["Videos, Bilder und Galerien", "Öffne ein Video zur Wiedergabe oder eine Galerie zum Betrachten ihrer Bilder. Galerieansichten bieten Navigation zwischen Bildern. In „Medien & Wiedergabe“ steuerst du Kachelgröße, Angaben, Aktionen und Wiedergabe. Eigene Kachelmaße greifen erst, wenn die entsprechende Option aktiviert ist. Noch nicht unterstützte Inhalte oder gesperrte Quellen können nicht allein durch eine Designeinstellung verfügbar werden.", "lists"],
        ["Favoriten, Merkliste und Sammlungen", "Mit den jeweiligen Merken- und Favoritenaktionen speicherst du Einträge lokal. Gruppen und Sammlungen ordnen deine Einträge. Lokale Favoriten und Merkliste sind unabhängig davon, wem du auf einer Originalwebsite folgst. Nutze die Exportfunktionen der jeweiligen Bibliothek für eine Sicherung.", "menu"],
        ["Star Finder, Quellen und Abrufdatum", "Star Finder zeigt gespeicherte Modelprofile, Bilder und verfügbare Fakten. Die Quellen- und Datumsangaben im Profil zeigen die Herkunft und den letzten bekannten Abruf. Unbekannte Werte bleiben unbekannt. Filter nach Merkmalen oder Tags können nur gespeicherte Angaben berücksichtigen. Kategorien ohne zugeordnete Daten ergeben noch keine passenden Treffer.", "models"],
        ["Deutsche Übersetzungen und Hintergrundpflege", "Unter „Sprache & Models“ siehst du die Läufe für Beschreibungen, Übersetzungen, Bilder und neue Namen. Gespeicherte Ergebnisse bleiben erhalten. Wiederholungen, Wartezeiten und Quellenlimits können den nächsten Abruf verzögern. Englische Texte können stehen bleiben, solange keine erfolgreiche deutsche Übersetzung gespeichert ist. Ein Fortschrittsbalken beschreibt den jeweiligen Durchlauf und bedeutet nicht, dass jedes Profil vollständig ist.", "models"],
        ["Live-Räume und Anbieterlogos", "Im Live-Bereich wählst du oben einen Hoster oder „Alle Anbieter“. Logo und Markierung zeigen die Auswahl. Die Filter darunter begrenzen Räume nach den verfügbaren Eigenschaften. Vorschauen verbrauchen Netzwerk und Rechenleistung: reduziere bei Bedarf Bildrate, Anzahl oder Qualität. Private Shows werden nicht geöffnet.", "live"],
        ["Live-Konten und Anmeldung", "Unter „Live → Mein Nutzer → Konten & Anmeldung“ meldest du dich pro Anbieter an. „Anzeigen“ und „Verbergen“ schalten die Passwortsichtbarkeit um. Die Anwendung speichert die bestätigte Website-Sitzung, nicht dein eingegebenes Passwort. Verlangt der Anbieter eine Browserprüfung, melde dich auf der Originalwebsite an und übernimm den vorgesehenen Sitzungscookie. In das Cookiefeld gehört kein Passwort. „Lokale Kontoverbindung trennen“ entfernt die lokale Verbindung.", "live"],
        ["Nur offiziell gefolgte Models sehen", "Unter „Live → Mein Nutzer → Gefolgte Models“ wählst du Anbieter und aktualisierst das Following. Suche und Statusfilter helfen bei der Auswahl. „Nur als live gemeldet“ verwendet den bekannten Abrufstand. Chaturbate und Stripchat unterstützen den Abruf; CamSoda und BongaCams können Teilbestände liefern. Bei CAM4 und XloveCam ist eine Anmeldung möglich, der Following-Abruf steht noch nicht bereit.", "live"],
        ["Multicam, Gruppen und Multitube", "Multicam kombiniert Live-Räume in Arbeitsbereichen. Das symmetrische Raster zeigt vier Plätze als 2×2 und zwölf Plätze bei ausreichender Breite als 6×2; schmale Fenster verwenden gleichmäßig gefüllte Reihen. Das ☰-Symbol klappt das Hauptmenü ein. „Mehr Streamfläche“ blendet Hauptmenü, Live-Menüs, Modellliste und große Leisten aus. Die kleinen Leistenschalter öffnen Arbeitsbereich, Anbieter, Filter und Ton sowie Werkzeuge einzeln. „Bedienung“ klappt auch diese Schalter ein; „Bedienung einblenden“ holt sie zurück. Die Modellliste bietet Suche, farbige Statusfilter und eine Vorschau über die ganze Zeile. Grün bedeutet aktuell live gemeldet, Rot offline, Orange privat und Grau unbekannt; alte Statusmeldungen laufen ab. Beim Einsetzen wird der öffentliche Stream neu geprüft. Live-Gruppen organisieren Models. Multitube zeigt mehrere Tube-Videos in einem eigenen Arbeitsbereich. Belegung, Layout und angebotene Wiedergabeoptionen werden dort eingestellt. Viele gleichzeitig laufende Videos benötigen entsprechend mehr Bandbreite und Leistung.", "live"],
        ["Downloads und Offline-Inhalte", "In „Downloads“ wählst du einen Speicherort und verfolgst Aufträge. „Offline“ zeigt verfügbare lokale Inhalte. Downloadfortschritt und Model-Hintergrundpflege sind getrennte Vorgänge. Unter „Speicher & Extras“ findest du die zugehörigen Einstellungen und Werkzeuge. Ein Designexport enthält keine heruntergeladenen Medien.", "tools"],
        ["Profil und Statistik", "Profil und Statistik stellen die lokal erfasste Nutzung dar. Live-Nutzung und offizielle Kontostatistiken haben getrennte Ansichten. Die lokal erfasste Sehzeit ist keine vollständige Statistik deines Originalkontos. Fehlende Messungen können nicht rückwirkend zuverlässig ergänzt werden.", "menu"],
        ["Designprofile, Sicherung und Wiederherstellung", "Unter „Designprofile“ kannst du Gestaltungen benennen und wiederverwenden. Export und Import übertragen Design einschließlich eigener Bilder und Schriften. Vor einem Import erscheint eine Vorschau. Ältere Designsicherungen bleiben unterstützt. Ein Designreset betrifft die Gestaltung und löscht keine Favoriten oder Konten.", "profiles"],
        ["Wenn etwas hängt oder fehlt", "Lade zunächst das Fenster neu; bei veralteter Darstellung nutze Strg + F5. Unter „Speicher & Extras“ startet „Oberfläche neu starten“ den lokalen Server neu. Dabei werden keine Favoriten oder Einstellungen absichtlich gelöscht; laufende Übertragungen können unterbrochen werden. Prüfe bei Quellenfehlern die Originalwebsite und bei Schriften, ob die Datei erfolgreich geladen wurde. Verfügbare Funktionen und Daten hängen auch vom Anbieter ab.", "tools"],
      ];
      for (const [title, body, category] of topics) {
        const topic = this.section(title, this.panels.help, "help-" + title);
        topic.append(el("p", { text: body }), button("Passende Einstellungen öffnen", () => this.openCategory(category)));
      }
    }
    applyMenuFonts(theme, d = D.normalize(theme.design, false)) {
      for (const panel of document.querySelectorAll('main > [id^="view-"]')) {
        const key = panel.id.slice(5);
        let choice = d.menuFonts[key];
        if ((!choice || choice === "inherit") && key === this.ctx.state.view)
          choice = d.menuFonts[this.ctx.state.menu];
        for (const role of ["body", "headings", "controls", "cards"])
          if (choice && choice !== "inherit")
            panel.style.setProperty("--ds-font-" + role, fontFamily(choice, d, theme.font));
          else panel.style.removeProperty("--ds-font-" + role);
      }
      for (const nav of document.querySelectorAll('nav button[data-id]')) {
        const choice = d.menuFonts[nav.dataset.id];
        if (choice && choice !== "inherit") nav.style.setProperty("--ds-font-menu", fontFamily(choice, d, theme.font));
        else nav.style.removeProperty("--ds-font-menu");
      }
      const choice = d.menuFonts[this.ctx.state.view] !== "inherit" && d.menuFonts[this.ctx.state.view] || d.menuFonts[this.ctx.state.menu];
      if (choice && choice !== "inherit") document.documentElement.style.setProperty("--ds-active-font", fontFamily(choice, d, theme.font));
      else document.documentElement.style.removeProperty("--ds-active-font");
    }
    apply(theme) {
      const d = D.normalize(theme.design, false),
        style = document.documentElement.style;
      document.documentElement.style.colorScheme = d.accessibility.highContrast
        ? "dark"
        : D.contrast("#000000", theme.bg) > D.contrast("#ffffff", theme.bg)
          ? "light"
          : "dark";
      document.body.classList.toggle("ds-light-surfaces", document.documentElement.style.colorScheme === "light");
      for (const role of roles)
        style.setProperty(
          "--ds-font-" + role,
          fontFamily(d.typography[role], d, theme.font),
        );
      for (const f of d.fonts) {
        if (!fontLoads.has(f.file)) {
          fontLoads.set(f.file, true);
          const face = new FontFace(
            "AHDesign_" + f.file.split(".")[0],
            'url("' + assetURL(f.file) + '")',
          );
          face
            .load()
            .then((font) => document.fonts.add(font))
            .catch(() =>
              this.notice(
                "Die Schrift „" +
                  f.name +
                  "“ konnte nicht geladen werden. Eine Ersatzschrift bleibt lesbar.",
                true,
              ),
            );
        }
      }
      style.setProperty("--ds-input", d.colors.input);
      style.setProperty("--ds-button-text", d.colors.buttonText);
      style.setProperty("--ds-hover", d.colors.hover);
      style.setProperty("--ds-heading-scale", d.typography.headingScale / 100);
      style.setProperty(
        "--ds-nav-size",
        (theme.scale * d.typography.navigationScale) / 100 + "px",
      );
      style.setProperty(
        "--ds-control-size",
        (theme.scale * d.typography.controlScale) / 100 + "px",
      );
      style.setProperty(
        "--ds-card-size",
        (((13 * theme.scale) / 16) * d.typography.cardScale) / 100 + "px",
      );
      style.setProperty("--ds-line-height", d.typography.lineHeight);
      style.setProperty(
        "--ds-letter-spacing",
        d.typography.letterSpacing + "px",
      );
      style.setProperty("--ds-weight", d.typography.weight);
      style.setProperty("--ds-padding", d.layout.padding + "px");
      style.setProperty("--ds-control-height", d.layout.controlHeight + "px");
      style.setProperty("--ds-card-align", d.layout.cardAlign);
      style.setProperty("--ds-focus", d.accessibility.focusWidth + "px");
      document.body.classList.toggle(
        "ds-motion-off",
        d.accessibility.motion === "off",
      );
      document.body.classList.toggle(
        "ds-underlines",
        d.accessibility.underlineLinks,
      );
      document.body.classList.toggle(
        "ds-high-contrast",
        d.accessibility.highContrast,
      );
      document.body.classList.toggle(
        "ds-width-limit",
        d.layout.contentWidth > 0,
      );
      style.setProperty("--ds-max-width", d.layout.contentWidth + "px");
      if (d.layout.customCards) {
        style.setProperty("--card", theme.card + "px");
        style.setProperty("--thumb", theme.thumb + "px");
      }
      document.body.classList.toggle(
        "ds-column-limit",
        d.layout.maxColumns > 0,
      );
      document.body.classList.toggle("ds-custom-cards", d.layout.customCards);
      style.setProperty("--ds-columns", Math.max(1, d.layout.maxColumns));
      this.applyBrand(d, theme);
      this.applyMenuFonts(theme, d);
      this.applyBackground(theme, d);
      this.applyMenu(d);
      this.applySiteLogos(d);
      if (this.previewBox) this.preview();
    }
    applyBrand(d, theme) {
      const n = $("brand"),
        b = d.brand;
      if (b.mode !== "legacy") {
        n.classList.add("ds-brand");
        const signature = JSON.stringify(b);
        if (n.dataset.designBrand !== signature) {
          n.dataset.designBrand = signature;
          n.replaceChildren();
          if (["logo", "both"].includes(b.mode)) {
            const source = b.logo
              ? assetURL(b.logo)
              : theme.logo
                ? this.ctx.brandSrc(theme.logo, theme.logoStamp)
                : "";
            if (source) {
              const img = el("img", {
                src: source,
                alt: b.name,
                style: `width:${b.width}px;height:${b.height}px;object-fit:${b.fit};object-position:${b.positionX}% ${b.positionY}%;padding:${b.padding}px;border-radius:${b.shape === "circle" ? "50%" : b.shape === "rounded" ? "12px" : "0"};background:${{ panel: theme.panel, accent: theme.accent, white: "#fff", black: "#000" }[b.background] || "transparent"}`,
              });
              img.onerror = () => {
                img.hidden = true;
                if (!n.querySelector(".ds-brand-name"))
                  n.append(
                    el("span", { class: "ds-brand-name", text: b.name ,"data-i18n-content":""}),
                  );
              };
              n.append(img);
            }
          }
          if (b.mode === "monogram")
            n.append(
              el("span", { class: "ds-monogram", text: b.monogram || "AC" }),
            );
          if (b.mode !== "logo" || !n.childNodes.length)
            n.append(
              el("span", {
                class: "ds-brand-name",
                text: b.name || "Adult Client",
              "data-i18n-content":""}),
            );
          if (b.tagline) n.append(el("small", { text: b.tagline }));
        }
      } else {
        n.classList.remove("ds-brand");
        delete n.dataset.designBrand;
      }
      document.title =
        b.title ||
        (b.mode === "legacy" ? "Adult Client" : b.name || "Adult Client");
      let favicon = $("ds-favicon");
      if (b.favicon) {
        if (!favicon) {
          favicon = el("link", { id: "ds-favicon", rel: "icon" });
          document.head.append(favicon);
        }
        favicon.href = assetURL(b.favicon);
      } else favicon?.remove();
    }
    applyBackground(theme, d = D.normalize(theme.design, false)) {
      const page =
        this.ctx.state.view === "watch"
          ? "watch"
          : this.ctx.state.view === "browse"
            ? "browse"
            : this.ctx.state.menu || this.ctx.state.view || "home";
      let b = d.backgrounds.pages[page];
      if (!b || b.mode === "inherit") b = d.backgrounds.all;
      if (b.mode === "inherit") b = D.background({ mode: "legacy" });
      let layer = $("ds-wall");
      const use = b.mode !== "legacy";
      document.body.classList.toggle("ds-own-wall", use);
      if (use) {
        if (!layer) {
          layer = el(
            "div",
            { id: "ds-wall", "aria-hidden": "true" },
            el("div", { class: "ds-wall-picture" }),
            el("div", { class: "ds-wall-dim" }),
          );
          document.body.prepend(layer);
        }
        layer.hidden = false;
        layer.style.position = b.fixed ? "fixed" : "absolute";
        layer.style.background =
          b.mode === "gradient"
            ? `linear-gradient(${b.angle}deg,${b.start},${b.end})`
            : b.color;
        const p = layer.firstElementChild,
          source = b.image ? assetURL(b.image) : b.url;
        p.style.backgroundImage =
          b.mode === "image" && source
            ? "url(" + JSON.stringify(source) + ")"
            : "none";
        p.style.backgroundSize = {
          cover: "cover",
          contain: "contain",
          stretch: "100% 100%",
          original: "auto",
          tile: "auto",
        }[b.fit];
        p.style.backgroundRepeat = b.fit === "tile" ? "repeat" : "no-repeat";
        p.style.backgroundPosition = b.x + "% " + b.y + "%";
        p.style.transform = `scale(${b.zoom / 100})`;
        p.style.transformOrigin = b.x + "% " + b.y + "%";
        p.style.filter = `blur(${b.blur}px)`;
        p.style.opacity = b.opacity / 100;
        layer.lastElementChild.style.background =
          "rgba(0,0,0," + b.dim / 100 + ")";
      } else if (layer) layer.hidden = true;
      const opacity = d.accessibility.reduceTransparency ? 100 : b.panelOpacity;
      const style = document.documentElement.style;
      style.setProperty(
        "--panel",
        opacity < 100 ? rgba(theme.panel, opacity) : theme.panel,
      );
      style.setProperty(
        "--aside",
        opacity < 100 ? rgba(theme.aside, opacity) : theme.aside,
      );
      if (d.accessibility.highContrast) {
        style.setProperty("--bg", "#05070a");
        style.setProperty("--ds-input", "#10151d");
        style.setProperty("--ds-hover", "#28374d");
        style.setProperty("--panel", "#080b10");
        style.setProperty("--aside", "#080b10");
        style.setProperty("--text", "#ffffff");
        style.setProperty("--muted", "#e4e8ef");
        style.setProperty("--line", "#c1cada");
      }
    }
    applyMenu(d) {
      const nav = document.querySelector(".shell>aside nav");
      if (!nav) return;
      const buttons = [...nav.querySelectorAll(":scope>button[data-id]")],
        order = [
          ...new Set([
            ...d.menuOrder,
            ...buttons.map((b) => b.dataset.id).filter((k) => k !== "settings"),
            "settings",
          ]),
        ];
      const signature = JSON.stringify(order);
      if (nav.dataset.dsOrder !== signature) {
        nav.dataset.dsOrder = signature;
        for (const id of order) {
          const n = buttons.find((b) => b.dataset.id === id);
          if (n) {
            nav.append(n);
            if (id === "bookmarks" && $("fav-nav")) nav.append($("fav-nav"));
          }
        }
      }
      for (const n of buttons) {
        n.querySelector(".ds-nav-icon")?.remove();
        const icon = d.menuIcons[n.dataset.id];
        if (icon?.image)
          n.prepend(
            el("img", {
              class: "ds-nav-icon",
              src: assetURL(icon.image),
              alt: "",
            }),
          );
        else if (icon?.symbol)
          n.prepend(
            el("span", {
              class: "ds-nav-icon",
              text: icon.symbol,
              "aria-hidden": "true",
            }),
          );
      }
    }
    applySiteLogos(d) {
      for (const site of this.ctx.state.catalog.sites) {
        if (!this.originalLogos.has(site.id))
          this.originalLogos.set(site.id, site.logo);
        const old = site.logo,
          next = d.siteLogos[site.id]
            ? assetURL(d.siteLogos[site.id])
            : this.originalLogos.get(site.id);
        if (old === next) continue;
        site.logo = next;
        for (const provider of document.querySelectorAll(
          "#site-list [data-provider]",
        ))
          if (provider.dataset.provider === site.id)
            for (const img of provider.querySelectorAll("img")) {
              if (next) img.src = next;
              else img.removeAttribute("src");
              img.hidden = !next;
            }
      }
      this.paintSitePreview();
    }
    paintSitePreview() {
      if (!this.siteLogoPreview || !this.sitePicker) return;
      const id = this.sitePicker.value,
        site = this.ctx.state.catalog.sites.find((s) => s.id === id),
        own = this.d.siteLogos[id],
        source = own
          ? assetURL(own)
          : this.originalLogos.get(id) || site?.logo || "";
      this.siteLogoPreview.hidden = !source;
      if (source && this.siteLogoPreview.getAttribute("src") !== source)
        this.siteLogoPreview.src = source;
      this.siteLogoPreview.onerror = () => {
        this.siteLogoPreview.hidden = true;
      };
      this.siteLogoNote.textContent = own
        ? "Eigenes Logo als Vorschau"
        : "Original des Anbieters";
    }
  }
  root.SettingsStudio = {
    get ready() {
      return !!instance;
    },
    get instance() {
      return instance;
    },
    async init(ctx) {
      const response = await fetch("/static/settings_schema.json");
      if (!response.ok)
        throw Error(
          "Die Designeinstellungen konnten nicht geladen werden. Bitte den Server aktualisieren und neu laden.",
        );
      D.configure(await response.json());
      instance = new Studio(ctx);
      await instance.init();
      root.addEventListener("ui-language-change", () => instance?.preview());
    },
    design() {
      return clone(instance.d);
    },
    load(raw) {
      instance?.load(raw);
    },
    apply(theme) {
      instance?.apply(theme);
    },
    background(theme) {
      instance?.applyBackground(theme);
      instance?.applyMenuFonts(theme);
    },
    assets() {
      instance?.paintAssets();
    },
    uploadBrand(slot, file) {
      return instance.action(() => instance.uploadBrand(slot, file))();
    },
    clearBrand(slot) {
      return instance.clearBrand(slot);
    },
  };
})(globalThis);
