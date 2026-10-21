/* Separate transactional storage; Live-Cam databases and legacy keys are untouched. */
(function (root) {
  "use strict";
  const D = root.MultiTubeDomain;
  class Store {
    constructor(name = "adulthideout.multitube") {
      this.name = name;
      this.listeners = new Set();
      this.db = null;
      this.value = null;
      this.channel =
        typeof BroadcastChannel === "function"
          ? new BroadcastChannel(name)
          : null;
      if (this.channel)
        this.channel.onmessage = (e) => {
          if (e.data?.revision)
            this.refresh().catch((error) => this.onError?.(error));
          this.onMessage?.(e.data);
        };
    }
    async open(seed) {
      this.db = await new Promise((resolve, reject) => {
        const r = indexedDB.open(this.name, 1);
        r.onupgradeneeded = () => {
          r.result.createObjectStore("state");
          r.result.createObjectStore("leases");
          r.result.createObjectStore("backups");
        };
        r.onsuccess = () => resolve(r.result);
        r.onerror = () => reject(r.error);
        r.onblocked = () =>
          reject(
            Error(
              "Ein älteres Multitube-Fenster hält den Speicher offen. Bitte schließen.",
            ),
          );
      });
      this.db.onversionchange = () => {
        this.db.close();
        this.db = null;
        this.onError?.(Error("Multitube wurde aktualisiert. Bitte neu laden."));
      };
      await this.mutate((s) => s || seed, false);
      return this.value;
    }
    mutate(action, increment = true, backup = false) {
      return new Promise((resolve, reject) => {
        if (!this.db) {
          reject(Error("Der Multitube-Speicher ist nicht bereit."));
          return;
        }
        const tx = this.db.transaction(
            backup ? ["state", "backups"] : "state",
            "readwrite",
          ),
          s = tx.objectStore("state"),
          r = s.get("current");
        let next, error;
        r.onsuccess = () => {
          try {
            const current = r.result;
            if (current) D.validate(current);
            next = action(current ? D.clone(current) : null);
            D.validate(next);
            next.revision = (current?.revision || 0) + (increment ? 1 : 0);
            if (backup && current)
              tx.objectStore("backups").put(current, "before-import");
            s.put(next, "current");
          } catch (e) {
            error = e;
            tx.abort();
          }
        };
        tx.oncomplete = () => {
          this.publish(next);
          this.channel?.postMessage({ revision: next.revision });
          resolve(next);
        };
        tx.onerror = tx.onabort = () =>
          reject(
            error ||
              tx.error ||
              Error("Multitube konnte nicht gespeichert werden."),
          );
      });
    }
    publish(v) {
      if (!this.value || v.revision >= this.value.revision) {
        this.value = v;
        for (const f of this.listeners) {
          try {
            f(v);
          } catch (e) {
            this.onError?.(e);
          }
        }
      }
    }
    async refresh() {
      const v = await this.read("state", "current");
      if (v && (!this.value || v.revision > this.value.revision))
        this.publish(D.validate(v));
      return this.value;
    }
    read(name, key) {
      return new Promise((resolve, reject) => {
        const r = this.db.transaction(name).objectStore(name).get(key);
        r.onsuccess = () => resolve(r.result);
        r.onerror = () => reject(r.error);
      });
    }
    put(name, key, value) {
      return new Promise((resolve, reject) => {
        const tx = this.db.transaction(name, "readwrite");
        tx.objectStore(name).put(value, key);
        tx.oncomplete = () => resolve();
        tx.onerror = tx.onabort = () =>
          reject(tx.error || Error("Sicherung fehlgeschlagen."));
      });
    }
    async backup() {
      await this.put("backups", "before-import", D.clone(this.value));
    }
    progress(workspace, owner, records) {
      return new Promise((resolve, reject) => {
        const tx = this.db.transaction(["state", "leases"], "readwrite"),
          leases = tx.objectStore("leases"),
          state = tx.objectStore("state"),
          lease = leases.get(workspace);
        let next, error;
        lease.onsuccess = () => {
          if (lease.result?.owner !== owner) return;
          const read = state.get("current");
          read.onsuccess = () => {
            try {
              next = read.result;
              if (!next) return;
              const w = next.workspaces.find((w) => w.id === workspace);
              if (!w) return;
              for (const [id, p] of Object.entries(records))
                if (w.entries[id] && p.updated >= (w.entries[id].updated || 0))
                  Object.assign(w.entries[id], p);
              D.validate(next);
              next.revision++;
              state.put(next, "current");
            } catch (e) {
              error = e;
              tx.abort();
            }
          };
        };
        tx.oncomplete = () => {
          if (next) {
            this.publish(next);
            this.channel?.postMessage({ revision: next.revision });
          }
          resolve(!!next);
        };
        tx.onerror = tx.onabort = () =>
          reject(
            error ||
              tx.error ||
              Error("Spielpositionen konnten nicht gespeichert werden."),
          );
      });
    }
    subscribe(f) {
      this.listeners.add(f);
      return () => this.listeners.delete(f);
    }
    async claim(workspace, owner, force = false) {
      return new Promise((resolve, reject) => {
        const tx = this.db.transaction("leases", "readwrite"),
          s = tx.objectStore("leases"),
          r = s.get(workspace);
        let ok = false,
          changed = false;
        r.onsuccess = () => {
          const old = r.result;
          ok = force || !old || old.owner === owner || old.until < Date.now();
          changed = ok && old?.owner !== owner;
          if (ok) s.put({ owner, until: Date.now() + 9000 }, workspace);
        };
        tx.oncomplete = () => {
          if (changed) this.channel?.postMessage({ lease: workspace, owner });
          resolve(ok);
        };
        tx.onerror = tx.onabort = () => reject(tx.error);
      });
    }
    async release(workspace, owner) {
      return new Promise((resolve, reject) => {
        const tx = this.db.transaction("leases", "readwrite"),
          s = tx.objectStore("leases"),
          r = s.get(workspace);
        r.onsuccess = () => {
          if (r.result?.owner === owner) s.delete(workspace);
        };
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      });
    }
  }
  root.MultiTubeStore = Store;
  if (typeof module === "object" && module.exports) module.exports = Store;
})(globalThis);
