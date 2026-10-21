/* Groups share provider identities and Multicam workspaces with the Live section. */
(function(root,factory){const common=typeof module==='object'&&module.exports,api=factory(common?require('./live_cam_domain.js'):root.LiveCamDomain,common?require('./live_cam_models_domain.js'):root.LiveCamModelsDomain);if(common)module.exports=api;else root.LiveCamGroupsDomain=api;})(globalThis,function(D,M){
  'use strict';
  const manual=g=>!!g&&!g.systemRole&&g.kind!=='smart';
  function tree(groups){const result=[],seen=new Set();function visit(parent,depth){for(const g of groups.filter(v=>(v.parent||'')===parent)){if(seen.has(g.id))continue;seen.add(g.id);result.push({...g,depth});visit(g.id,depth+1);}}visit('',0);for(const g of groups)if(!seen.has(g.id))result.push({...g,depth:0});return result;}
  function drag(value){try{const raw=JSON.parse(value);if(!Array.isArray(raw)||!raw.length||raw.length>5000||raw.some(v=>!D.room(v)))return [];return [...new Set(raw)];}catch{return D.room(value)?[value]:[];}}
  function workspace(group,sites){if(!group||typeof group.id!=='string')throw Error('Bitte eine Gruppe öffnen.');const w=D.workspace(group.name);w.description=group.description||'';w.settings.source='library';w.settings.capacity=4;w.settings.playbackFilters.group=group.id;w.settings.sidebarFilters.group=group.id;w.settings.sites=[...sites];return w;}
  function selectionWorkspaces(ids,name,sites,available){if(!Array.isArray(ids)||!ids.length||ids.some(k=>!D.room(k)))throw Error('Bitte Models auswählen.');const unique=[...new Set(ids)],count=Math.ceil(unique.length/20);if(count>available)throw Error('Diese Auswahl benötigt '+count+' Arbeitsbereiche. Es sind nur noch '+available+' frei. Bitte die Auswahl eingrenzen oder eine ganze Gruppe mit blätterbaren Kameraseiten öffnen.');return Array.from({length:count},(_,i)=>{const w=D.workspace(name+(count>1?' · '+(i+1)+'/'+count:''));unique.slice(i*20,i*20+20).forEach((id,index)=>w.slots[index]=id);w.settings.sites=[...sites];w.settings.capacity=Math.min(4,unique.length-i*20);return w;});}
  const DEFAULT_FIELDS=['image','liveStatus','lastSeen','subject','viewers','country','age','publicTags','groups','actions'];
  function preference(raw={}){
    const explicit=Array.isArray(raw.fields),valid=new Set(M.FIELDS.map(([key])=>key));
    const fields=explicit?[...new Set(raw.fields.filter(key=>valid.has(key)))]:DEFAULT_FIELDS.filter(key=>raw.info!==false||['image','actions'].includes(key));
    if(!explicit&&raw.assignments===true)fields.push('groupAssignment');
    return {view:raw.view==='list'?'list':'tiles',columns:[0,2,3,4,5,6,8,10,12].includes(raw.columns)?raw.columns:0,width:[160,200,240,320,400].includes(raw.width)?raw.width:240,size:[24,36,48,50,72,120].includes(raw.size)?raw.size:50,info:true,assignments:fields.includes('groupAssignment'),fields};
  }
  return {manual,tree,drag,workspace,selectionWorkspaces,preference,DEFAULT_FIELDS};
});
