/* Чистая модель категорий и последовательная очередь сохранений; тестируется в Node. */
(function(root){
  'use strict';
  const key=x=>String(x).normalize('NFKC').toLocaleLowerCase().replace(/ё/g,'е').trim().replace(/\s+/g,' ');
  const clone=x=>JSON.parse(JSON.stringify(x));
  const stable=x=>Array.isArray(x)?x.map(stable):x&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,stable(x[k])])):x;
  const same=(a,b)=>JSON.stringify(stable(a))===JSON.stringify(stable(b));
  function included(category,r){const k=key(category);return r.include_categories.some(x=>key(x)===k)||(!r.exclude_categories.some(x=>key(x)===k)&&r.category_default==='include');}
  function setCategory(r,category,on){if(included(category,r)===on)return clone(r);r=clone(r);r.include_categories=r.include_categories.filter(x=>key(x)!==key(category));r.exclude_categories=r.exclude_categories.filter(x=>key(x)!==key(category));if(on!==(r.category_default==='include'))r[on?'include_categories':'exclude_categories'].push(category);return r;}
  function all(r,on){r=clone(r);r.category_default=on?'include':'exclude';r.include_categories=[];r.exclude_categories=[];return r;}
  function restorable(draft,now=Date.now()){
    if(!draft||!Number.isInteger(draft.revision)||draft.revision<0||!Number.isFinite(draft.at)||now-draft.at<0||now-draft.at>=7*86400000||!draft.rules)return false;
    const r=draft.rules;
    // Черновик вправе быть семантически невалидным (например, 101 символ).
    // Ограничиваем только структуру и предельный объём HTML-полей, а не правила сохранения.
    return ['include_categories','exclude_categories','include_words','exclude_words'].every(k=>Array.isArray(r[k])&&r[k].length<=6000&&r[k].every(v=>typeof v==='string')&&r[k].join('\n').length<=6000)&&typeof r.filter_enabled==='boolean'&&typeof r.match_forms==='boolean'&&['include','exclude'].includes(r.category_default)&&['all','any'].includes(r.combine);
  }
  class Queue {
    constructor(state,write,read){this.configured=state.configured!==false;this.saved=clone(state.rules);this.revision=state.revision;this.write=write;this.read=read;this.pending=null;this.running=null;this.error=null;}
    save(rules){this.pending=clone(rules);if(this.running)return this.running.then(()=>this.pending?this.save(this.pending):this.saved);this.running=this.drain().finally(()=>{this.running=null;});return this.running;}
    async drain(){while(this.pending){const next=this.pending;this.pending=null;if(this.configured&&same(next,this.saved))continue;let result;
      try{result=await this.write(next,this.revision);}catch(error){
        // Неизвестный исход: сверить сервер, не повторять запись вслепую.
        let actual;try{actual=await this.read();}catch(_){this.error=error;throw error;}
        if(actual.configured!==false&&same(actual.rules,next)){result=actual;}else{if(actual.revision!==this.revision)error.status=409;this.error=error;throw error;}
      }
      this.revision=result.revision;this.saved=clone(result.rules);this.configured=true;this.error=null;
    }return this.saved;}
  }
  const api={key,clone,same,included,setCategory,all,restorable,Queue};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.FilterConfigModel=api;
})(typeof window!=='undefined'?window:this);
