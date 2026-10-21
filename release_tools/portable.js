(() => {
  'use strict';
  let section, content, notice, busy=false, state, lastRead=0, actionError='';
  const en=()=>window.AppI18n?.language==='en';
  const t=(de,english)=>en()?english:de;
  const el=(tag,text)=>{const n=document.createElement(tag);if(text)n.textContent=text;return n;};
  const size=n=>new Intl.NumberFormat(en()?'en-GB':'de-DE',{maximumFractionDigits:1}).format((n||0)/1024**2)+' MB';
  const date=n=>n?new Date(n*1000).toLocaleString(en()?'en-GB':'de-DE'):t('Noch nicht geprüft','Not checked yet');
  const errorText=value=>{
    if(!en())return value;
    const pairs=[
      ['Ungültige Programmversion: ','Invalid program version: '],
      ['Updateadresse gehört nicht zum gewählten GitHub-Projekt.','The update URL does not belong to the configured GitHub project.'],
      ['Updatebeschreibung ist zu groß.','The update description is too large.'],
      ['Dieses Updateformat wird noch nicht unterstützt.','This update format is not supported yet.'],
      ['Prüfsumme fehlt im Updatepaket.','The update package has no valid checksum.'],
      ['Ungültige Paketgröße: ','Invalid package size: '],
      ['Ungültiges öffentliches Modelldatenpaket.','Invalid public model data package.'],
      ['Download ist größer als angekündigt.','The download is larger than advertised.'],
      ['Unsicherer Pfad im Programmupdate.','The program update contains an unsafe file path.'],
      ['Verknüpfungen im Programmupdate sind nicht erlaubt.','Links are not allowed in program updates.'],
      ['Nicht erlaubte Datei im Programmupdate.','The program update contains a prohibited file.'],
      ['Doppelter Dateiname im Programmupdate.','The program update contains a duplicate file name.'],
      ['Entpacktes Programm ist größer als angekündigt.','The extracted program is larger than advertised.'],
      ['Unvollständige Programmbeschreibung.','The program update description is incomplete.'],
      ['Im Programmupdate fehlen notwendige Dateien.','Required files are missing from the program update.'],
      ['Programmversion und Updatebeschreibung stimmen nicht überein.','The program version does not match its update description.'],
      ['Die veröffentlichte Paketdatei fehlt: ','The published package file is missing: '],
      ['Veröffentlichte Paketgröße stimmt nicht überein.','The published package size does not match.'],
      ['GitHub-Prüfsumme stimmt nicht mit dem Paket überein.','The GitHub checksum does not match the package.'],
      ['Das Update würde die Veröffentlichungsquelle ändern.','The update would change the publishing source.'],
      ['Datenpaket ist zu groß.','The model data package is too large.'],
      ['Unvollständiges Datenpaket.','The model data package is incomplete.'],
      ['Datenpaket beschädigt.','The model data package is damaged.'],
      ['Bitte den laufenden Download zuerst abschließen lassen.','Please wait for the current download to finish.'],
      ['Zuerst das Programmupdate herunterladen.','Please download the program update first.'],
      ['Ein Update wird bereits vorbereitet.','An update is already being prepared.'],
      ['Ungültiges vorbereitetes Programmupdate.','The staged program update is invalid.'],
      ['Eine frühere Installation muss zuerst wiederhergestellt werden.','A previous installation must be recovered first.'],
      ['Vorbereitetes Programmupdate fehlt oder ist beschädigt.','The staged program update is missing or damaged.'],
      ['Noch kein Veröffentlichungs-Repository eingerichtet. Es wurde nichts hochgeladen.','No publishing repository is configured yet. Nothing has been uploaded.'],
      ['Ungültiges Repository.','Invalid repository.'],
      ['Ungültige Updateeinstellung.','Invalid update setting.'],
      ['Datenupdate nicht übernommen; bisherige Daten bleiben erhalten.\n','Model data update was not applied; existing data is preserved.\n'],
      ['Unpassendes Datenpaket: ','Incompatible model data package: '],
      ['Noch keine öffentliche Veröffentlichung erreichbar.','No public release is available yet.'],
      ['GitHub ist vorübergehend nicht erreichbar. Bitte später erneut versuchen.','GitHub is temporarily unavailable. Please try again later.'],
      ['Die neue Version konnte nicht erfolgreich gestartet werden.','The new version could not start successfully.'],
      ['Die unterbrochene Installation wurde wiederhergestellt.','The interrupted installation has been rolled back.'],
      ['Bitte zuerst den laufenden Download abschließen lassen.','Please wait for the current download to finish.'],
      ['Download unvollständig oder Prüfsumme falsch.','Download incomplete or checksum mismatch.'],
      ['Nicht genügend freier Speicher für Download und Entpacken.','Not enough free space to download and extract the update.'],
      ['Für diesen Bereich ist kein neueres Update verfügbar.','No newer update is available for this component.'],
      ['Das laufende Programm wurde nicht rechtzeitig beendet. Es wurden keine Dateien ersetzt.','The running program did not exit in time. No files were replaced.']
    ];
    const match=pairs.find(([de])=>de===value||((de.endsWith(': ')||de.endsWith('\n'))&&value?.startsWith(de)));
    return match?match[1]+errorText(value.slice(match[0].length)):window.AppI18n?.t(value)||value;
  };
  function button(de,english,op,disabled=false){
    const b=el('button',t(de,english));b.type='button';b.dataset.op=op;b.disabled=disabled;
    b.onclick=()=>request(op);return b;
  }
  function openUpdates(){
    document.querySelector('[data-view="settings"]')?.click();
    const deadline=Date.now()+15000;
    const open=()=>{
      if(document.getElementById('view-settings')?.classList.contains('hidden'))return;
      const tab=document.getElementById('ds-tab-updates');
      // On first launch the settings schema may still be loading.
      if(!tab||!window.SettingsStudio?.ready){if(Date.now()<deadline)setTimeout(open,100);return;}
      tab.click();section?.scrollIntoView({behavior:'smooth',block:'start'});
    };
    open();
  }
  function renderNotice(){
    if(!state)return;
    const kinds=['program','data'].filter(kind=>state.available?.[kind]?.available);
    const pending=state.program_pending||state.pending;
    const failed=state.install_result?.ok===false;
    notice.hidden=!(kinds.length||pending||failed);
    const title=failed?t('Update fehlgeschlagen','Update failed'):pending?t('Update bereit','Update ready'):t('Update verfügbar','Update available');
    const detail=kinds.map(kind=>kind==='program'?t('Programm','Program'):t('Modelldaten','Model data')).join(' + ');
    const text=title+(detail?' · '+detail:'');
    // Status polling must not repeatedly mutate the live region or observer tree.
    if(notice.textContent!==text)notice.textContent=text;
    notice.title=text+' – '+t('Updates öffnen','Open updates');
  }
  function checkbox(de,english,key){
    const label=el('label');label.style.cssText='display:flex;gap:.6rem;align-items:center;margin:.7rem 0';
    const input=el('input');input.type='checkbox';input.checked=!!state.preferences[key];input.dataset.preference=key;
    input.onchange=()=>request('update-settings',{[key]:input.checked});
    label.append(input,el('span',t(de,english)));return label;
  }
  function render(){
    renderNotice();if(!content||!state)return;
    content.replaceChildren();
    content.append(el('h2',t('Updates & Modellbilder','Updates & model images')));
    content.append(el('p',t('Programm und Modelldaten lassen sich unabhängig aktualisieren. Persönliche Daten und heruntergeladene Dateien bleiben erhalten.','Update the program and model data independently. Personal data and downloaded files are preserved.')));
    content.append(el('p',t('Updatequelle: ','Update source: ')+(state.repository||t('Noch nicht eingerichtet','Not configured yet'))));
    content.append(checkbox('Automatisch beim Start und einmal täglich nach Updates suchen','Check for updates automatically on startup and once a day','automatic'));
    content.append(checkbox('Auch Betaversionen anbieten','Include beta releases','beta'));
    content.append(button('Nach Updates suchen','Check for updates','check',state.check.running||!state.repository));
    content.append(el('p',state.check.running?t('Updates werden geprüft …','Checking for updates …'):t('Letzte Prüfung: ','Last checked: ')+date(state.check.checked)));
    if(state.check.error)content.append(el('p',errorText(state.check.error)));
    if(actionError){const error=el('p',errorText(actionError));error.setAttribute('role','alert');content.append(error);}
    const task=state.update;
    for(const kind of ['program','data']){
      const card=el('section');card.style.cssText='border:1px solid var(--border,#776b52);border-radius:12px;padding:16px;margin:16px 0';
      const program=kind==='program',candidate=state.available[kind],ready=program?state.program_pending:state.pending;
      card.append(el('h3',program?t('Programm','Program'):t('Modelldaten','Model data')));
      card.append(el('p',t('Installiert: ','Installed: ')+(program?state.version:(state.package?.created||t('Kein Datenpaket geladen','No data package installed')))));
      if(candidate?.available){
        card.append(el('p',t('Verfügbar: ','Available: ')+candidate.version+' · '+size(candidate.manifest.bytes)));
        const details=el('details');details.append(el('summary',t('Änderungen ansehen','View changes')));
        const notes=el('pre',candidate.notes||t('Keine Versionshinweise vorhanden.','No release notes provided.'));notes.style.whiteSpace='pre-wrap';details.append(notes);card.append(details);
      }else card.append(el('p',state.check.checked&&!state.check.error?t('Kein neueres Update gefunden.','No newer update found.'):t('Bitte nach Updates suchen.','Please check for updates.')));
      card.append(button(program?'Programmupdate herunterladen':'Modelldaten herunterladen',program?'Download program update':'Download model data',program?'program-update':'data-update',!candidate?.available||task.running||!!ready));
      if(ready){
        card.append(el('p',program?t('Heruntergeladen und geprüft. Installation beim Neustart.','Downloaded and verified. Ready to install on restart.'):t('Heruntergeladen und geprüft. Übernahme beim nächsten Start.','Downloaded and verified. Data will be merged on next startup.')));
        card.append(button(program?'Installieren und neu starten':'Modelldaten übernehmen und neu starten',program?'Install and restart':'Apply model data and restart',program?'install-program':'restart',task.running));
      }
      if(task.kind===kind){
        const phases={download:t('Wird heruntergeladen …','Downloading …'),verify:t('Paket wird geprüft und entpackt …','Verifying and extracting package …'),ready:t('Update ist bereit.','Update is ready.'),error:t('Update fehlgeschlagen: ','Update failed: ')+errorText(task.message),restarting:t('Programm wird neu gestartet …','Restarting program …')};
        card.append(el('p',phases[task.phase]||''));
        if(task.running){const progress=el('progress');progress.max=task.total||1;progress.value=task.done||0;progress.setAttribute('aria-label',t('Downloadfortschritt','Download progress'));progress.style.width='100%';card.append(progress,el('p',size(task.done)+' / '+size(task.total)));}
      }
      content.append(card);
    }
    if(state.install_result){const result=state.install_result;content.append(el('p',result.ok?t('Letzter Neustart erfolgreich: ','Last restart succeeded: ')+result.version:t('Letztes Update fehlgeschlagen; bisherige Version bleibt erhalten. ','Last update failed; previous version is preserved. ')+errorText(result.error)));}
    if(state.update_error)content.append(el('p',errorText(state.update_error)));
    content.append(el('h3',t('Modellbilder offline speichern','Store model images offline')));
    content.append(el('p',t('Bilder werden zunächst bei Bedarf geladen. Der freiwillige Offline-Download kann sehr viel Speicher und Zeit benötigen; er lässt sich pausieren und fortsetzen.','Images load on demand by default. The optional offline download may require considerable space and time; you can pause and resume it.')));
    content.append(el('p',t('Offline gespeichert: ','Stored offline: ')+state.images.stored.toLocaleString(en()?'en-GB':'de-DE')+' · '+size(state.images.stored_bytes)));
    content.append(el('p',t('Erfolgreich in diesem Lauf: ','Completed this run: ')+state.images.done+' · '+t('Fehlgeschlagen: ','Failed: ')+state.images.failed));
    if(state.images.message)content.append(el('p',errorText(state.images.message)));
    const row=el('div');row.className='row';
    row.append(button('Alle Modellbilder offline laden / fortsetzen','Download / resume all model images','images-start',state.images.running),button('Bilddownload pausieren','Pause image downloads','images-stop',!state.images.running),button('Programm beenden','Quit program','shutdown'));
    content.append(row);
  }
  async function request(op,extra={}){
    if(busy)return;busy=true;lastRead=Date.now();
    try{
      const response=await fetch('/api/distribution',op?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({op,...extra})}:{});
      const data=await response.json();if(!data.ok)throw Error(data.error);
      const changed=JSON.stringify(data)!==JSON.stringify(state);
      state=data;lastRead=Date.now();actionError='';if(changed||op)render();
      if(op==='restart'||op==='install-program')content.append(el('p',t('Der Dienst startet neu. Die neue Version öffnet sich nach dem Start im Browser.','The service is restarting. The new version will open in your browser.')));
    }catch(error){actionError=error.message;if(content)render();}
    finally{busy=false;}
  }
  function mount(){
    const settings=document.querySelector('#ac-main-menu nav [data-id="settings"]');
    if(settings&&settings.nextElementSibling!==notice)settings.after(notice);
    const panel=document.getElementById('ds-panel-updates');
    if(!panel||section?.isConnected)return;
    section=el('section');section.className='ds-section';section.dataset.i18nContent='';
    content=el('div');content.setAttribute('aria-live','polite');section.append(content);panel.append(section);render();request();
  }
  notice=el('button');notice.type='button';notice.hidden=true;notice.dataset.i18nContent='';notice.id='portable-update-notice';
  notice.style.cssText='white-space:normal;text-align:left;line-height:1.4;border:1px solid var(--accent,#d9b763);border-left-width:4px;margin-top:6px;font-weight:600';
  notice.setAttribute('aria-live','polite');notice.setAttribute('aria-atomic','true');notice.onclick=openUpdates;
  new MutationObserver(mount).observe(document.body,{childList:true,subtree:true});mount();request();
  addEventListener('ui-language-change',render);
  addEventListener('focus',()=>request());
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')request();});
  setInterval(()=>{if(document.visibilityState!=='visible')return;
    const visible=section?.isConnected&&!section.closest('[hidden],.hidden');
    const delay=(state?.update.running||state?.check.running)?1500:visible?5000:45000;
    if(Date.now()-lastRead>=delay)request();
  },1000);
})();
