/* Компоновка рабочих панелей хранится отдельно от правил и результатов.
   Разворачивание временно: восстановление возвращает точный прежний снимок. */
(function(root){
  'use strict';
  const clamp=x=>Math.max(25,Math.min(75,x));
  class Layout {
    constructor(saved){this.normal={editor:true,results:false,ratio:55};if(saved&&typeof saved.editor==='boolean'&&typeof saved.results==='boolean'&&Number.isFinite(saved.ratio))this.normal={editor:saved.editor,results:saved.results,ratio:clamp(saved.ratio)};this.max=null;}
    visible(){return this.max?{...this.normal,editor:this.max==='editor',results:this.max==='results'}:{...this.normal};}
    show(panel,on){this.max=null;this.normal[panel]=on;}
    maximize(panel){this.max=this.max===panel?null:panel;}
    resize(ratio){if(Number.isFinite(ratio))this.normal.ratio=clamp(ratio);}
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={Layout};return;}
  root.FilterPanelLayout=Layout;
  const form=document.getElementById('config-form');if(!form)return;
  const box=document.getElementById('config-panels'),divider=document.getElementById('config-divider'),key='cf.filter-panels.v1:'+form.dataset.endpoint;
  let saved;try{saved=JSON.parse(localStorage.getItem(key));}catch(_){}
  const layout=new Layout(saved);
  function render(){const state=layout.visible();form.dataset.both=String(state.editor&&state.results);box.dataset.editor=String(state.editor);box.dataset.results=String(state.results);box.style.setProperty('--config-ratio',state.ratio+'%');divider.hidden=!(state.editor&&state.results);divider.setAttribute('aria-valuenow',String(Math.round(state.ratio)));
    for(const panel of ['editor','results']){
      document.getElementById('config-'+panel+'-pane').hidden=!state[panel];
      document.querySelectorAll('[data-panel-show="'+panel+'"]').forEach(b=>{b.hidden=state[panel];b.setAttribute('aria-expanded',String(state[panel]));b.setAttribute('aria-controls','config-'+panel+'-pane');});
      const b=document.querySelector('[data-panel-max="'+panel+'"]'),restore=layout.max===panel,label=restore?'Восстановить':'Развернуть: '+(panel==='editor'?'Настройка фильтра':'Результаты');b.textContent=restore?'❐':'⛶';b.setAttribute('title',label);b.setAttribute('aria-label',label);
    }
    document.getElementById('config-panel-recovery').hidden=state.editor||state.results;
    try{localStorage.setItem(key,JSON.stringify(layout.normal));}catch(_){}
  }
  document.querySelectorAll('[data-panel-show]').forEach(b=>b.addEventListener('click',()=>{layout.show(b.dataset.panelShow,true);render();}));
  document.querySelectorAll('[data-panel-hide]').forEach(b=>b.addEventListener('click',()=>{layout.show(b.dataset.panelHide,false);render();[...document.querySelectorAll('[data-panel-show="'+b.dataset.panelHide+'"]')].find(x=>x.getClientRects().length)?.focus();}));
  document.querySelectorAll('[data-panel-max]').forEach(b=>b.addEventListener('click',()=>{layout.maximize(b.dataset.panelMax);render();}));
  divider.addEventListener('keydown',e=>{let value=layout.normal.ratio;if(e.key==='ArrowLeft')value-=2;else if(e.key==='ArrowRight')value+=2;else if(e.key==='Home')value=25;else if(e.key==='End')value=75;else return;e.preventDefault();layout.resize(value);render();});
  divider.addEventListener('pointerdown',e=>{if(e.button!==0)return;e.preventDefault();divider.setPointerCapture(e.pointerId);divider.classList.add('dragging');});
  divider.addEventListener('pointermove',e=>{if(!divider.hasPointerCapture(e.pointerId))return;const rect=box.getBoundingClientRect();layout.resize((e.clientX-rect.left)/rect.width*100);render();});
  for(const type of ['pointerup','pointercancel','lostpointercapture'])divider.addEventListener(type,e=>{divider.classList.remove('dragging');if(divider.hasPointerCapture(e.pointerId))divider.releasePointerCapture(e.pointerId);});
  render();
})(typeof window!=='undefined'?window:this);
