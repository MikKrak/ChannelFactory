const assert=require('node:assert/strict');
const M=require('../static/filter-config-model.js'),C=require('../static/filter-category-model.js');
const base={version:2,filter_enabled:false,category_default:'exclude',include_categories:['Сад'],exclude_categories:['Рецепты'],include_words:[],exclude_words:[],combine:'all',match_forms:true,auto_select:true};
const known=['Сад','Рецепты','Овощи'];
let r=M.clone(base),before=M.clone(r);
let views=C.views(known,r,['Овощи','сад'],false);assert.deepEqual(views.selected,[{name:'Сад',on:true}]);
views=C.views(known,r,['Овощи','сад'],true);assert.deepEqual(views.selected,[{name:'Сад',on:true},{name:'Овощи',on:false}]);assert.deepEqual(r,before);
r=C.remember(M.setCategory(r,'Овощи',true),known);views=C.views(known,r,['Овощи'],false);assert.equal(views.selected.length,2);assert(views.selected.every(x=>Object.keys(x).sort().join(',')==='name,on'));
r=C.remember(M.setCategory(r,'Овощи',false),known);assert.equal(C.views(known,r,['Овощи'],false).selected.length,1);assert.equal(C.views(known,r,['Овощи'],true).selected.find(x=>x.name==='Овощи').on,false);
for(const on of [true,false]){r=C.remember(M.all(r,on),known);const list=C.views(known,r).all;assert.equal(list.filter(x=>x.on).length,on?known.length:0);}
r=C.remember(M.setCategory(r,'Сад',true),known);assert.equal(C.views(known,r).selected.length,1);
const restored=JSON.parse(JSON.stringify(r));assert.deepEqual(C.views([],restored).selected,[{name:'Сад',on:true}]);
const refreshed=C.views([...known,'Цветы'],restored);assert.equal(refreshed.all.find(x=>x.name==='Цветы').on,false);assert.deepEqual(restored,r);
assert.deepEqual(C.names(['САД'],['сад','Овощи']),['САД','Овощи']);
console.log('Category views: one configuration, recommendations without writes, select/remove, mass changes, restore and new values: OK');
