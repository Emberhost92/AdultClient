/* Local, bilingual help. Opening this guide never reads or changes credentials. */
(() => {
  'use strict';
  const trigger = document.getElementById('chaturbate-tutorial-open');
  if (!trigger) return;
  const t = (de, en) => window.AppI18n?.language === 'en' ? en : de;
  const notice = document.getElementById('chaturbate-setup-notice');
  let returnFocus = trigger, hasKey = null, statusFailed = false, pending = null, revision = 0;
  function open(source = trigger) {
    returnFocus = source;
    render();
    if (!dialog.open) dialog.showModal();
    dialog.returnValue = '';
    dialog.scrollTop = 0;
  }
  function enterCode() {
    show('settings', 'settings');
    document.getElementById('ds-tab-live')?.click();
    const input = document.getElementById('set-cam-key');
    input?.scrollIntoView({block:'center'});
    input?.focus({preventScroll:true});
  }
  function renderNotice() {
    if (!notice) return;
    notice.hidden = hasKey !== false && !statusFailed;
    if (notice.hidden) return;
    notice.innerHTML = `<h3>${statusFailed ? t('Chaturbate-Zugang konnte nicht geprüft werden', 'Could not check Chaturbate setup') : t('Chaturbate fehlt? Zuerst den Affiliate-Code einrichten', 'Missing Chaturbate? Set up your affiliate code first')}</h3><p>${statusFailed ? t('Bitte prüfe den Zugangsstatus erneut. Die Anleitung und das Eingabefeld kannst du direkt hier öffnen.', 'Please check the setup status again. You can open the guide and code field directly here.') : t('Ohne deinen eigenen Chaturbate-Affiliate-Code (wm) kann Adult Client keine aktuelle Chaturbate-Raumliste abrufen. Deshalb fehlen neue Chaturbate-Ergebnisse. Andere Cam-Anbieter kannst du unabhängig davon nutzen.', 'Without your own Chaturbate affiliate code (wm), Adult Client cannot retrieve the current Chaturbate room list. This is why new Chaturbate results are missing. Other cam providers work independently of this setup.')}</p><div><button type="button" data-guide>${t('Chaturbate jetzt einrichten · Anleitung', 'Set up Chaturbate now · Guide')}</button><button type="button" data-code>${t('Ich habe einen Code · Jetzt eingeben', 'I have a code · Enter it now')}</button>${statusFailed ? `<button type="button" data-retry>${t('Status erneut prüfen', 'Check status again')}</button>` : ''}</div>`;
    notice.querySelector('[data-guide]').onclick = e => open(e.currentTarget);
    notice.querySelector('[data-code]').onclick = enterCode;
    notice.querySelector('[data-retry]')?.addEventListener('click', refresh);
  }
  function setStatus(data) {
    if (typeof data?.has_key !== 'boolean') return;
    revision++;
    hasKey = data.has_key;
    statusFailed = false;
    renderNotice();
  }
  function refresh() {
    if (pending) return pending;
    const requestRevision = revision;
    pending = (async () => {
      try {
        const response = await fetch('/api/cam-key', {cache:'no-store',signal:AbortSignal.timeout(8000)});
        const data = await response.json();
        if (!response.ok || !data.ok || typeof data.has_key !== 'boolean') throw Error('status');
        if (revision === requestRevision) setStatus(data);
      } catch {
        if (revision === requestRevision) { statusFailed = true; renderNotice(); }
      } finally { pending = null; }
    })();
    return pending;
  }
  const dialog = document.createElement('dialog');
  dialog.id = 'chaturbate-tutorial';
  dialog.setAttribute('data-i18n-content', '');
  dialog.setAttribute('aria-labelledby', 'cb-guide-title');
  const style = document.createElement('style');
  style.textContent = `#chaturbate-tutorial{box-sizing:border-box;width:min(900px,94vw);max-height:90dvh;overflow:auto;background:var(--panel,#37332c);color:var(--text,#f7efe0);border:1px solid #a18a59;border-radius:16px;padding:24px}#chaturbate-tutorial::backdrop{background:#000a}#chaturbate-tutorial header{display:flex;align-items:center;justify-content:space-between;gap:16px}#chaturbate-tutorial h2{margin:0}#chaturbate-tutorial section{border-top:1px solid #8b795c66;margin-top:20px;padding-top:16px}#chaturbate-tutorial p{line-height:1.6}#chaturbate-tutorial a{color:#f5ce78;text-decoration:underline}#chaturbate-tutorial img{display:block;max-width:100%;height:auto;border-radius:8px;margin:12px 0;background:white}#chaturbate-tutorial code{overflow-wrap:anywhere;background:#0004;padding:4px}#chaturbate-tutorial figcaption{font-size:.9em}#chaturbate-tutorial figure{margin:12px 0}`;
  document.head.append(style);
  style.textContent += `#chaturbate-setup-notice[hidden]{display:none!important}#chaturbate-setup-notice{margin:16px 0 22px;padding:18px 20px;border:1px solid var(--accent,#d8b56a);border-left-width:5px;border-radius:12px;background:color-mix(in srgb,var(--accent,#d8b56a) 12%,var(--panel,#37332c));color:var(--text)}#chaturbate-setup-notice h3{margin:0 0 8px;font-size:1.1rem}#chaturbate-setup-notice p{margin:0 0 14px;line-height:1.6;max-width:1000px}#chaturbate-setup-notice>div{display:flex;flex-wrap:wrap;gap:10px}#chaturbate-setup-notice [data-guide]{font-weight:700}@media(max-width:600px){#chaturbate-setup-notice{padding:14px}#chaturbate-setup-notice button{width:100%}}`;
  document.body.append(dialog);
  function render() {
    const top = dialog.scrollTop;
    trigger.textContent = t('Chaturbate einrichten · Anleitung', 'Set up Chaturbate · Tutorial');
    dialog.innerHTML = `<header><h2 id="cb-guide-title">${t('Chaturbate Schritt für Schritt einrichten', 'Set up Chaturbate step by step')}</h2><button type="button" data-close>${t('Schließen', 'Close')}</button></header>
      <p>${t('Du brauchst deinen eigenen Affiliate-Kampagnencode (wm). Damit lädt Adult Client die öffentliche Raumliste. Das ist kein Login in dein Chaturbate-Konto.', 'You need your own affiliate campaign code (wm). It lets Adult Client load the public room list. This does not sign you in to your Chaturbate account.')}</p>
      <section><h3>1 · ${t('Affiliate-Bereich öffnen', 'Open the affiliate area')}</h3><p>${t('Melde dich auf der offiziellen Website mit deinem Chaturbate-Konto an. Falls erforderlich, tritt dort selbst dem Affiliate-Programm bei und lies die Bedingungen. Adult Client benötigt weder dein Passwort noch Zahlungsdaten.', 'Sign in to your Chaturbate account on the official website. If required, join the affiliate program there yourself and review its terms. Adult Client needs neither your password nor payment details.')}</p><a href="https://chaturbate.com/affiliates/" target="_blank" rel="noopener noreferrer">${t('Offizielles Affiliate-Programm öffnen ↗', 'Open the official affiliate program ↗')}</a></section>
      <section><h3>2 · ${t('„API - Users Online v2“ wählen', 'Choose “API - Users Online v2”')}</h3><p>${t('Öffne „Promo Tools“ und danach „API - Users Online v2“. Über den direkten Link gelangst du ebenfalls dorthin; ohne Anmeldung erscheint zunächst die Login-Seite.', 'Open “Promo Tools”, then “API - Users Online v2”. You can also use the direct link below; if you are signed out, the login page appears first.')}</p><p><a href="https://chaturbate.com/affiliates/promotools/" target="_blank" rel="noopener noreferrer">Promo Tools ↗</a> · <a href="https://chaturbate.com/affiliates/promotools/api_usersonline/" target="_blank" rel="noopener noreferrer">API - Users Online v2 ↗</a></p><figure><img src="/static/tutorials/chaturbate-tools.png" alt="Promo Tools: API - Users Online v2" width="850" height="160"><figcaption>${t('Screenshot der offiziellen Werkzeugseite, Stand 21.10.2026. Die Website kann später anders aussehen.', 'Screenshot of the official tools page, captured October 21, 2026. The website may change.')}</figcaption></figure></section>
      <section><h3>3 · ${t('Nur den Wert hinter „wm=“ kopieren', 'Copy only the value after “wm=”')}</h3><p>${t('Auf der API-Seite steht unter „API URL“ dein persönlicher Link. Der benötigte Code steht auch in der Tabelle bei „wm“ (campaign slug). Kopiere den gesamten Code mit exakt derselben Groß- und Kleinschreibung, bis zum nächsten &. Nicht die vollständige URL und nicht „wm=“ einfügen. Die Länge kann variieren.', 'Your personal link appears under “API URL”. The code is also listed in the table next to “wm” (campaign slug). Copy the entire code with its original capitalization, stopping at the next &. Do not paste the full URL or “wm=”. The length can vary.')}</p><p><code>…/onlinerooms/?wm=<strong>AbC12</strong>&amp;client_ip=request_ip</code></p><p>${t('Beispiel: Hier wäre nur AbC12 einzutragen. Das ist ein erfundener Beispielcode und funktioniert nicht.', 'Example: enter only AbC12 here. This is a made-up example code and will not work.')}</p></section>
      <section><h3>4 · ${t('In Adult Client speichern', 'Save in Adult Client')}</h3><p>${t('Füge deinen Code hier in den Einstellungen bei „Chaturbate Affiliate-Schlüssel“ ein und drücke den direkt danebenstehenden Button „Speichern“. Ein bereits gespeicherter Code wird nicht erneut angezeigt. Ein leeres Feld löscht ihn nicht.', 'Paste your code into “Chaturbate affiliate key” in these settings and click the adjacent “Save” button. A previously saved code is not displayed again. Leaving the field empty does not delete it.')}</p><figure><img src="/static/tutorials/chaturbate-settings.png" alt="${t('Eingabefeld und Speichern in Adult Client', 'Input field and Save in Adult Client')}" loading="lazy"><figcaption>${t('Eingabefeld in Adult Client; ohne persönliche Zugangsdaten.', 'The input field in Adult Client, without personal credentials.')}</figcaption></figure><button type="button" data-input>${t('Anleitung schließen und Code eingeben', 'Close tutorial and enter code')}</button><p>${t('Öffne anschließend Live → Chaturbate beziehungsweise wähle Chaturbate in der Anbieter-Auswahl und aktualisiere die Liste. Die gespeicherte Bestätigung allein prüft den Code noch nicht beim Anbieter. Werden keine Räume geladen, prüfe Code, Internetverbindung und eventuelle Fehlermeldungen. Regionale Sperren oder gerade nicht öffentliche Räume können die Auswahl einschränken.', 'Then open Live → Chaturbate, or select Chaturbate in the provider list, and refresh the list. The save confirmation alone does not validate the code with the provider. If no rooms load, check the code, internet connection and any error message. Regional restrictions or rooms that are not currently public can limit the results.')}</p></section>
      <section><h3>${t('Persönliche Favoriten und anderer PC', 'Personal following and another PC')}</h3><p>${t('Für persönliche Following-Listen gibt es eine getrennte Anmeldung im Live-Bereich unter „Konten & Anmeldung“. Der wm-Code ersetzt diese Anmeldung und den separaten Statistikschlüssel nicht. Zugangsdaten bleiben auf deinem PC und werden nicht mit GitHub oder Modelldaten geteilt. Auf einem neuen PC richtest du deinen eigenen Code erneut ein; Programmupdates erhalten deinen vorhandenen Code.', 'Personal following lists use a separate connection under “Accounts & sign-in” in the Live area. The wm code does not replace that sign-in or the separate statistics token. Credentials stay on your PC and are not shared through GitHub or model data. Set up your own code on a new PC; program updates preserve your existing code.')}</p></section>`;
    dialog.querySelector('[data-close]').onclick = () => dialog.close();
    dialog.querySelector('[data-input]').onclick = () => { dialog.returnValue = 'input'; dialog.close('input'); };
    dialog.scrollTop = top;
  }
  trigger.addEventListener('click', () => open(trigger));
  dialog.addEventListener('close', () => { if (dialog.returnValue === 'input') enterCode(); else returnFocus?.focus(); });
  window.addEventListener('ui-language-change', () => { render(); renderNotice(); });
  window.addEventListener('focus', () => { if (!document.getElementById('view-live')?.classList.contains('hidden')) refresh(); });
  window.ChaturbateHelp = {open, refresh, setStatus};
  render();
  trigger.disabled = false;
})();
