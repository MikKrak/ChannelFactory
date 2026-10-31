/* Чистые проверки адресов и сохранённого состояния. Браузер и сеть не нужны. */
const assert = require('node:assert/strict');
const {route, cleanState} = require('../static/workspace.js');
const origin = 'http://127.0.0.1:8002';
const id = '7ef10475-0397-4539-8e54-72797a6dc394';
assert.equal(route('/studio',origin).space,'factory');
assert.equal(route('/studio/cccp',origin).space,'cccp');
assert.equal(route('/studio/library/materials',origin).space,'factory');
assert.equal(route('/studio/cccp/materials/'+id,origin).space,'cccp');
assert.equal(route('/studio/library/sources/'+id,origin).key,'sources');
for (const address of ['https://evil.example/studio','//evil.example/studio','javascript:alert(1)','/import','/studio/unknown','/studio/cccp-evil']) assert.equal(route(address,origin),null);
for (const [path,root] of [
  ['/studio/cccp/posts/'+id+'/publish-now','/studio/cccp/posts'],
  ['/studio/library/sources/'+id+'/import','/studio/library/sources'],
  ['/studio/cccp/inbox/replies/'+id+'/confirm','/studio/cccp/inbox'],
  ['/studio/cccp/sources/'+id+'/disconnect','/studio/cccp/sources']
]) assert.equal(route(path,origin).href,root);
assert.equal(route('/studio/cccp/posts?status=ready&token=SECRET&saved=true',origin).href,'/studio/cccp/posts?status=ready');
assert.equal(route('/studio/cccp/materials?q=земляника&offset=20',origin).href,'/studio/cccp/materials?q=%D0%B7%D0%B5%D0%BC%D0%BB%D1%8F%D0%BD%D0%B8%D0%BA%D0%B0&offset=20');
assert.equal(route('/studio/cccp/posts?offset=-1&status=wrong',origin).href,'/studio/cccp/posts');
const state=cleanState({version:1,spaces:{factory:{active:'materials',tabs:[{href:'/studio/library/materials'},{href:'https://evil.example/studio'},{href:'/studio/cccp/posts'}],panels:{left:false,right:true,leftWidth:9999,rightWidth:-1}},cccp:{active:'posts',tabs:[{href:'/studio/cccp/posts?status=draft'},{href:'/studio/cccp/posts?status=ready'},{href:'/studio/library/materials'}],panels:{left:true,right:false}}}},origin);
assert.deepEqual(state.spaces.factory.tabs.map(x=>x.key),['materials']);
assert.equal(state.spaces.factory.active,'materials');
assert.equal(state.spaces.cccp.tabs.length,1);
assert.equal(state.spaces.cccp.tabs[0].href,'/studio/cccp/posts?status=draft');
assert.equal(state.spaces.cccp.active,'posts');
assert.equal(state.spaces.factory.panels.leftWidth,320);
assert.equal(state.spaces.factory.panels.rightWidth,220);
assert.equal(state.spaces.factory.panels.left,false);
assert.equal(state.spaces.cccp.panels.left,true);
assert.deepEqual(cleanState({version:999,spaces:state.spaces},origin).spaces.factory.tabs,[]);
for (const broken of [null,[],{},'broken',{version:1,spaces:{factory:{tabs:'bad',panels:null}}}]) assert.doesNotThrow(()=>cleanState(broken,origin));
console.log('Workspace model: routes, safe restore, separated spaces and panel bounds passed');
