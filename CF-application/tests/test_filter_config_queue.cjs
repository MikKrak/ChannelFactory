const assert=require('node:assert/strict');
const M=require('../static/filter-config-model.js');
const base={category_default:'include',include_categories:[],exclude_categories:[],filter_enabled:false};
(async()=>{
 let r=M.clone(base);
 for(let i=0;i<10;i++)r=M.setCategory(r,'Рубрика '+i,i<5);
 assert.equal(Array.from({length:10},(_,i)=>M.included('Рубрика '+i,r)).filter(Boolean).length,5);
 assert.deepEqual(M.setCategory(r,'Рубрика 6',false),r);
 assert.equal(M.included('Рубрика 6',M.setCategory(r,'Рубрика 6',true)),true);
 assert.equal(M.included('Новое',M.all(r,false)),false);
 assert.equal(M.included('Новое',M.all(r,true)),true);
 const draft={at:Date.now(),revision:1,rules:{...base,include_words:['x'.repeat(101)],exclude_words:[],match_forms:true,combine:'all'}};
 assert(M.restorable(draft));assert(!M.restorable({...draft,at:Date.now()-8*86400000}));assert(!M.restorable({...draft,rules:{...draft.rules,include_words:123}}));
 let release,store=M.clone(base),revision=0,calls=[];
 const q=new M.Queue({rules:store,revision},async(next,rev)=>{calls.push(rev);if(calls.length===1)await new Promise(done=>release=done);assert.equal(rev,revision);store=next;return{rules:store,revision:++revision};},async()=>({rules:store,revision}));
 const first=q.save({...base,filter_enabled:true});
 q.save({...base,include_categories:['Среднее']});q.save({...base,exclude_categories:['Последнее']});release();await first;
 assert.deepEqual(calls,[0,1]);assert.deepEqual(q.saved.exclude_categories,['Последнее']);
 // Сервер сохранил, но ответ потерялся: одно чтение подтверждает исход без повторной записи.
 let writes=0;const lost=new M.Queue({rules:base,revision:0},async next=>{store=next;writes++;throw new Error('network');},async()=>({rules:store,revision:1}));await lost.save({...base,filter_enabled:true});assert.equal(writes,1);assert.equal(lost.revision,1);
 // Конфликт не переносит локальный expected revision на чужую актуальную версию.
 const conflict=new M.Queue({rules:base,revision:0},async()=>{const e=new Error('conflict');e.status=409;throw e;},async()=>({rules:{...base,exclude_categories:['Чужое']},revision:4}));
 await assert.rejects(conflict.save({...base,filter_enabled:true}));assert.equal(conflict.revision,0);assert.deepEqual(conflict.saved,base);
 assert(M.same({b:2,a:1},{a:1,b:2}));
 let fastRevision=0;const fast=new M.Queue({rules:base,revision:0},async rules=>({rules,revision:++fastRevision}),async()=>({rules:base,revision:0}));const noop=fast.save(base);const changed=fast.save({...base,filter_enabled:true});await Promise.all([noop,changed]);assert.equal(fast.saved.filter_enabled,true);assert.equal(fastRevision,1);
 let defaultsWrites=0;const defaults=new M.Queue({rules:base,revision:0,configured:false},async rules=>{defaultsWrites++;return{rules,revision:1,configured:true};},async()=>({rules:base,revision:0,configured:false}));await defaults.save(base);assert.equal(defaultsWrites,1);assert(defaults.configured);
 const offline=new M.Queue({rules:base,revision:0},async()=>{throw new Error('offline');},async()=>{throw new Error('offline');});await assert.rejects(offline.save({...base,filter_enabled:true}));assert.deepEqual(offline.saved,base);assert.equal(offline.revision,0);
 console.log('Categories 5+5, idempotence, mass changes, serial saves, lost response and conflict: OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
