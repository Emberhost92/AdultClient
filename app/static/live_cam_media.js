/* Live-only entry point. Uses the existing on-device media stores. */
(function(root){
 'use strict';const D=root.LiveCamDomain;
 class MediaHub{
  constructor(){this.dialogs=new Set();this.active=false;this.epoch=0;this.preserveGalleryPage=true;}
  async initialize(ctx){this.ctx=ctx;if(this.initialized)return;if(!this.loading)this.loading=(async()=>{await root.LiveCamAnalytics.start();this.store=root.LiveCamAnalytics.recorder.store;this.data=this.store.value;this.capture={};this.store.subscribe(value=>this.data=value);this.gallery=new root.LiveCamGallery.Gallery(this);this.gallery.filters=root.LiveCamMediaDomain.validate(await this.store.get('cache','live-media-preferences')||{});this.initialized=true;})().catch(error=>{this.loading=null;throw error;});await this.loading;}
  async mount(panel,ctx){const epoch=++this.epoch;this.active=true;await this.initialize(ctx);if(!this.active||epoch!==this.epoch)return;this.panel=panel;panel.replaceChildren();const heading=document.createElement('h3');heading.textContent='Live-Galerie';const body=document.createElement('div');panel.append(heading,body);this.note=document.createElement('p');this.note.setAttribute('role','status');panel.prepend(this.note);await this.gallery.mount(body);}
  leave(){this.active=false;this.epoch++;this.gallery?.detach();for(const dialog of this.dialogs)dialog.close();}
  settings(){return root.LiveCamSingleDomain.defaults();}
  model(){return D.room(this.identity)||{};}
  change(fn){if(this.data.private)throw Error('Im Privatmodus werden keine Änderungen gespeichert.');return this.store.mutate(fn);}
  command(fn){return async event=>{try{await fn(event);}catch(error){this.error(error);}};}
  notify(message){if(this.note){this.note.textContent=message;this.note.setAttribute('role','status');}}
  error(error){this.notify(error.message);this.note?.setAttribute('role','alert');const dialog=[...this.dialogs].at(-1);if(dialog){let note=dialog.querySelector('.lg-error');if(!note){note=document.createElement('p');note.className='lg-error';note.setAttribute('role','alert');dialog.append(note);}note.textContent=error.message;}}
  saveGalleryPrefs(filters){if(!this.data.private)this.store.put('cache',structuredClone(filters),'live-media-preferences').catch(error=>this.error(error));}
  dialog(title){const dialog=document.createElement('dialog'),header=document.createElement('header'),heading=document.createElement('h3'),close=document.createElement('button'),body=document.createElement('div');dialog.className='lc-dialog lg-dialog';dialog.setAttribute('aria-label',title);heading.textContent=title;close.type='button';close.textContent='Schließen';close.onclick=()=>dialog.close();body.className='lc-dialog-body';header.append(heading,close);dialog.append(header,body);this.dialogs.add(dialog);dialog.addEventListener('close',()=>{try{dialog.onCleanup?.();}finally{this.dialogs.delete(dialog);dialog.remove();}},{once:true});document.body.append(dialog);dialog.showModal();return {dialog,body};}
 }
 const instance=new MediaHub();root.LiveCamMedia={instance,mount:(panel,ctx)=>instance.mount(panel,ctx),leave:()=>instance.leave()};
 if(typeof module==='object'&&module.exports)module.exports={MediaHub};
})(globalThis);
