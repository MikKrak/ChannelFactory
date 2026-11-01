const assert=require('node:assert/strict');
const {Layout}=require('../static/filter-config-panels.js');
const p=new Layout();assert.deepEqual(p.visible(),{editor:true,results:false,ratio:55});
p.show('results',true);p.resize(63);const previous=p.visible();
for(const panel of ['editor','results']){p.maximize(panel);assert.equal(p.visible()[panel],true);assert.equal(p.visible()[panel==='editor'?'results':'editor'],false);p.maximize(panel);assert.deepEqual(p.visible(),previous);}
p.show('editor',false);p.maximize('results');p.maximize('results');assert.equal(p.visible().editor,false);
p.show('results',false);assert.deepEqual(p.visible(),{editor:false,results:false,ratio:63});p.show('editor',true);assert.equal(p.visible().editor,true);
p.resize(-10);assert.equal(p.visible().ratio,25);p.resize(110);assert.equal(p.visible().ratio,75);
const restored=new Layout(p.normal);assert.deepEqual(restored.visible(),p.visible());assert.equal(restored.max,null);
assert.deepEqual(new Layout({editor:'yes',results:false,ratio:900}).visible(),{editor:true,results:false,ratio:55});
console.log('Panels: initial editor, both, hide/show, exact maximize restore, bounds and reload: OK');
