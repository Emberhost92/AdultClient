/* Offline UI localization. Source text remains canonical; data and input values are untouched. */
(function(root,factory){const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;root.AppI18n=api;})(globalThis,function(root){
  'use strict';
  const KEY='ah-ui-language', ATTRS=['title','aria-label','placeholder','alt','aria-description'];
  const canonical=new WeakMap(),attributes=new WeakMap(),protectedValues=new WeakSet();
  let language='de',observer,scheduled=false,writing=false,revision=0;
  try{language=root.localStorage?.getItem(KEY)==='en'?'en':'de';}catch(_){}
  const catalog=root.AppUIMessages||{messages:{},patterns:[]},messages=catalog.messages||{};
  const normalize=s=>String(s??'').replace(/\s+/g,' ').trim();
  const exact=new Map(Object.entries(messages).map(([de,en])=>[normalize(de),en]));
  const escape=s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const patterns=(catalog.patterns||[]).filter(s=>exact.has(normalize(s))&&/[A-Za-zÄÖÜäöüß]{2}/.test(s.replace(/\{\d+\}/g,''))).map(source=>{
    const order=[];let index=0,rx='';
    for(const match of normalize(source).matchAll(/\{(\d+)\}/g)){rx+=escape(normalize(source).slice(index,match.index))+'([\\s\\S]*?)';order.push(match[1]);index=match.index+match[0].length;}
    rx+=escape(normalize(source).slice(index));
    return {rx:new RegExp('^'+rx+'$'),order,target:exact.get(normalize(source)),needle:normalize(source).split(/\{\d+\}/).sort((a,b)=>b.length-a.length)[0],weight:source.replace(/\{\d+\}/g,'').length};
  }).sort((a,b)=>b.weight-a.weight);
  const aliases={Settings:'Einstellungen',Cancel:'Abbrechen',Save:'Speichern',Saved:'Gespeichert',Close:'Schließen',Delete:'Löschen',Yes:'Ja',No:'Nein',Unknown:'Unbekannt',Loading:'Wird geladen',Apply:'Übernehmen',Retry:'Erneut versuchen',Home:'Start',Search:'Suche',Notifications:'Benachrichtigungen',Enabled:'Aktiviert',Disabled:'Deaktiviert',All:'Alle',None:'Keine',Open:'Öffnen',Select:'Auswählen',Preview:'Vorschau',Quality:'Qualität',Volume:'Lautstärke',History:'Verlauf',Images:'Bilder',Groups:'Gruppen',Sources:'Quellen',Statistics:'Statistik',Refresh:'Aktualisieren',Restore:'Wiederherstellen',Backup:'Sicherung'};
  const cache=new Map(),pending=new Set();
  function t(value,target=language,depth=0){
    const raw=String(value??''),key=normalize(raw);
    if(!key||!/[A-Za-zÄÖÜäöüß]/.test(key))return raw;
    if(target==='de')return aliases[key]||raw;
    if(cache.has(key))return raw.replace(raw.trim(),cache.get(key));
    let translated=exact.get(key);
    if(translated==null){
      for(const pattern of patterns){if(!key.includes(pattern.needle))continue;const m=key.match(pattern.rx);if(!m)continue;
        const values={};pattern.order.forEach((id,i)=>values[id]=m[i+1]);
        translated=pattern.target.replace(/\{(\d+)\}/g,(_,id)=>{
          const value=values[id]??'';
          return depth<4&&((value.length>15&&exact.has(normalize(value)))||pattern.needle.startsWith('Schrift:')||(/[·:]/.test(value)&&/\d/.test(value)))?t(value,target,depth+1):value;
        });break;
      }
    }
    if(translated==null&&depth<4&&/(?: · |: |\n)/.test(key)){
      const parts=key.split(/(\s+[·•]\s+|\n|:\s+)/),output=parts.map((part,i)=>i%2?part:t(part,target,depth+1)).join('');
      if(output!==key)translated=output;
    }
    if(translated!=null&&depth<4&&/(?: · |: |\n)/.test(translated)){
      translated=translated.split(/(\s+[·•]\s+|\n|:\s+)/).map((part,i)=>i%2?part:t(part,target,depth+1)).join('');
    }
    if(translated==null){if(cache.size>15000)cache.clear();cache.set(key,raw.trim());return raw;}
    if(cache.size>15000)cache.clear();cache.set(key,translated);
    return raw.replace(raw.trim(),translated);
  }
  function skip(node){
    const parent=node.nodeType===1?node:node.parentElement;
    return !parent||!!parent.closest('script,style,textarea,code,pre,[translate="no"],[data-i18n-content],.sf-biography,.star-bio,.sf-source-value,.sf-personal-note,.sf-badges,.sf-tag-filter,.sf-scene-tag');
  }
  function text(node){
    if(skip(node)||protectedValues.has(node))return;
    const old=canonical.get(node),current=node.nodeValue;
    if(!current?.trim())return;
    const source=old&&current===old.output?old.source:current;
    const output=t(source);
    canonical.set(node,{source,output});
    if(current!==output)node.nodeValue=output;
  }
  function attrs(node){
    if(node.nodeType!==1||node.closest('script,style,textarea,[translate="no"],[data-i18n-content]'))return;
    const saved=attributes.get(node)||{};
    if(node.matches('[data-ui-language]'))node.value=language;
    for(const name of ATTRS){
      if(!node.hasAttribute(name))continue;
      const current=node.getAttribute(name),old=saved[name],source=old&&current===old.output?old.source:current,output=t(source);
      if(name==='aria-label'&&node.getAttribute('data-i18n-source-label')!==source)node.setAttribute('data-i18n-source-label',source);
      saved[name]={source,output};if(output!==current)node.setAttribute(name,output);
    }
    attributes.set(node,saved);
  }
  function walk(node){
    if(node.nodeType===3){text(node);return;}
    if(![1,9,11].includes(node.nodeType))return;
    if(node.nodeType===1){attrs(node);if(skip(node))return;}
    for(const child of node.childNodes)walk(child);
  }
  function flush(){
    scheduled=false;writing=true;
    const nodes=[...pending];pending.clear();
    for(const node of nodes)if(node.isConnected&&!nodes.some(p=>p!==node&&p.contains?.(node)))walk(node);
    writing=false;
  }
  function queue(node){pending.add(node);if(!scheduled){scheduled=true;queueMicrotask(flush);}}
  function original(node){
    if(!node)return '';
    if(node.nodeType===3)return canonical.get(node)?.source??node.nodeValue;
    return [...node.childNodes].map(original).join('');
  }
  function selector(value){
    return value.replace(/\[aria-label=(['"])(.*?)\1\]/g,match=>':is('+match+','+match.replace('aria-label','data-i18n-source-label')+')');
  }
  function protect(node){if(node?.nodeType===1)node.setAttribute('data-i18n-content','');else if(node)protectedValues.add(node);return node;}
  function syncControls(){
    for(const node of root.document?.querySelectorAll('[data-ui-language]')||[])node.value=language;
    if(root.document){root.document.documentElement.lang=language;root.document.documentElement.dataset.uiLanguage=language;}
  }
  function setLanguage(value){
    language=value==='en'?'en':'de';revision++;
    try{root.localStorage?.setItem(KEY,language);}catch(_){}
    syncControls();if(root.document)walk(root.document.body);
    root.dispatchEvent?.(new CustomEvent('ui-language-change',{detail:{language,locale:locale(),revision}}));
    return language;
  }
  function locale(){return language==='en'?'en-GB':'de-DE';}
  function mount(){
    if(!root.document)return;
    syncControls();
    root.document.addEventListener('change',e=>{if(e.target.matches('[data-ui-language]'))setLanguage(e.target.value);});
    walk(root.document.body);
    observer=new MutationObserver(records=>{
      for(const record of records){
        if(record.type==='characterData'){
          const old=canonical.get(record.target);if(old&&record.target.nodeValue===old.output)continue;
          queue(record.target);
        }else if(record.type==='attributes'){
          const old=attributes.get(record.target)?.[record.attributeName];
          if(old&&record.target.getAttribute(record.attributeName)===old.output)continue;
          queue(record.target);
        }else for(const node of record.addedNodes)queue(node);
      }
    });
    observer.observe(root.document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:ATTRS});
  }
  if(root.document){
    for(const name of ['alert','confirm','prompt'])if(typeof root[name]==='function'){
      const originalDialog=root[name].bind(root);root[name]=(message,...args)=>originalDialog(t(message),...args);
    }
    root.addEventListener('storage',e=>{if(e.key===KEY&&e.newValue!==language)setLanguage(e.newValue);});
    if(root.document.readyState==='loading')root.document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
  }
  return {t,setLanguage,get language(){return language;},locale,original,selector,protect,refresh:()=>{if(root.document)walk(root.document.body);},get revision(){return revision;}};
});
