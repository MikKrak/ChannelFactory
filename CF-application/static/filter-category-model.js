/* filter-category-model.js — два представления одной конфигурации рубрик.
   Рекомендации добавляют варианты показа, но сами никогда не меняют правила. */
(function(root){
  'use strict';
  const M=typeof module!=='undefined'&&module.exports?require('./filter-config-model.js'):root.FilterConfigModel;
  function names(...groups){const map=new Map();for(const group of groups)for(const name of group)if(!map.has(M.key(name)))map.set(M.key(name),name);return [...map.values()];}
  function views(known,rules,recommended=[],showRecommended=false){
    const all=names(known,rules.include_categories,rules.exclude_categories,recommended).map(name=>({name,on:M.included(name,rules)}));
    const recommendedKeys=new Set(recommended.map(M.key));
    return {all,selected:all.filter(row=>row.on||(showRecommended&&recommendedKeys.has(M.key(row.name))))};
  }
  function remember(rules,known){const all=names(known,rules.include_categories,rules.exclude_categories);return {...M.clone(rules),include_categories:all.filter(c=>M.included(c,rules)),exclude_categories:all.filter(c=>!M.included(c,rules))};}
  const api={names,views,remember};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.FilterCategoryModel=api;
})(typeof window!=='undefined'?window:this);
