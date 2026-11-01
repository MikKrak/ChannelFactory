/* workspace.js — вкладки разделов и панели общей рабочей среды.
   Храним только проверенные адреса GET и настройки панелей, без содержимого форм.
   Никакие импорты, публикации, ответы и фоновые операции здесь не запускаются. */
(() => {
  'use strict';
  const tools = {
    factory: [
      ['overview', 'Пульт фабрики', '/studio'],
      ['sources', 'Общие источники', '/studio/library/sources'],
      ['materials', 'Общие материалы', '/studio/library/materials'],
      ['cleanup', 'Просмотр очистки', '/studio/library/cleanup']
    ],
    cccp: [
      ['overview', 'Обзор проекта', '/studio/cccp'],
      ['materials', 'Материалы', '/studio/cccp/materials'],
      ['sources', 'Источники', '/studio/cccp/sources'],
      ['posts', 'Редакционные посты', '/studio/cccp/posts'],
      ['inbox', 'Обращения', '/studio/cccp/inbox']
    ]
  };
  const uuid = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';

  function route(value, origin = 'http://localhost') {
    let url;
    try { url = new URL(value, origin); } catch (_) { return null; }
    if (url.origin !== origin || url.username || url.password) return null;
    const path = url.pathname.replace(/\/$/, '');
    for (const [space, list] of Object.entries(tools)) {
      for (const [key, label, root] of list) {
        if (path !== root && !(key !== 'overview' && path.startsWith(root + '/'))) continue;
        let href = root;
        // После POST или на странице подтверждения вкладка ведёт в безопасный список.
        const detail = path.slice(root.length + 1);
        if (path === root || (['materials', 'sources', 'posts', 'inbox'].includes(key) && new RegExp('^' + uuid + '$', 'i').test(detail)) || (key === 'sources' && (detail === 'new' || new RegExp('^' + uuid + '/filter(?:/review)?$', 'i').test(detail)))) {
          href = path;
        }
        const query = new URLSearchParams();
        for (const [name, val] of url.searchParams) {
          if (name === 'project' && /^[a-z][a-z0-9_-]{0,39}$/.test(val)) query.set(name, val);
          if (name === 'q' && val.length <= 150) query.set(name, val);
          if (name === 'offset' && /^\d{1,6}$/.test(val)) query.set(name, val);
          if (name === 'status' && ['all', 'draft', 'ready', 'published'].includes(val)) query.set(name, val);
          if (name === 'before' && /^\d{4}-\d{2}-\d{2}$/.test(val)) query.set(name, val);
        }
        return {space, key, label, href: href + (query.size ? '?' + query.toString() : '')};
      }
    }
    return null;
  }

  function cleanState(raw, origin = 'http://localhost') {
    const result = {version: 1, spaces: {}};
    for (const space of Object.keys(tools)) {
      const saved = raw && raw.version === 1 && raw.spaces && raw.spaces[space] || {};
      const tabs = [];
      for (const tab of Array.isArray(saved.tabs) ? saved.tabs.slice(0, 12) : []) {
        const item = route(tab && tab.href, origin);
        if (item && item.space === space && !tabs.some(x => x.key === item.key)) tabs.push(item);
      }
      const pref = saved.panels || {};
      result.spaces[space] = {
        tabs,
        active: tabs.some(x => x.key === saved.active) ? saved.active : 'overview',
        panels: {
          left: typeof pref.left === 'boolean' ? pref.left : null,
          right: typeof pref.right === 'boolean' ? pref.right : null,
          leftWidth: Number.isFinite(pref.leftWidth) ? Math.max(180, Math.min(320, pref.leftWidth)) : 220,
          rightWidth: Number.isFinite(pref.rightWidth) ? Math.max(220, Math.min(380, pref.rightWidth)) : 260
        }
      };
    }
    return result;
  }

  // Чистая модель используется изолированными тестами Node, без DOM и сети.
  if (typeof module !== 'undefined' && module.exports) module.exports = {tools, route, cleanState};
  if (typeof document === 'undefined' || !document.body.classList.contains('workbench')) return;
  const origin = location.origin;
  const storageKey = 'cf.workspace.v1';
  let raw = {};
  let storageAvailable = true;
  try { raw = JSON.parse(localStorage.getItem(storageKey) || '{}'); } catch (_) { storageAvailable = false; }
  let state = cleanState(raw, origin);
  const space = document.body.dataset.space;
  if (!state.spaces[space]) return;
  const current = route(location.href, origin) || route(tools[space][0][2], origin);
  let work = state.spaces[space];
  const desktop = window.matchMedia('(min-width: 960px)').matches;
  function activateCurrent() {
    for (const side of ['left', 'right']) if (work.panels[side] === null) work.panels[side] = desktop;
    if (!work.tabs.length && current.key !== 'overview') work.tabs.push(route(tools[space][0][2], origin));
    const index = work.tabs.findIndex(x => x.key === current.key);
    if (index >= 0) work.tabs[index] = current;
    else work.tabs.push(current);
    work.active = current.key;
  }
  activateCurrent();

  function save() {
    if (!storageAvailable) return;
    try { localStorage.setItem(storageKey, JSON.stringify(state)); } catch (_) { storageAvailable = false; }
  }
  function resume(targetSpace) {
    const target = state.spaces[targetSpace];
    return target.tabs.find(x => x.key === target.active)?.href || tools[targetSpace][0][2];
  }
  function updateSpaceLinks() {
    document.querySelectorAll('[data-resume-space]').forEach(link => {
      const target = link.dataset.resumeSpace;
      if (state.spaces[target]) link.href = resume(target);
    });
  }
  updateSpaceLinks();
  const picker = document.getElementById('project-picker');
  if (picker) picker.value = space === 'cccp' ? '/studio/cccp' : '';
  picker?.addEventListener('change', event => {
    if (event.target.value === '/studio/cccp') location.assign(resume('cccp'));
    else if (event.target.value === '') location.assign('/studio');
  });

  function renderTabs() {
    const bar = document.getElementById('workspace-tabs');
    bar.replaceChildren();
    for (const tab of work.tabs) {
      const node = document.createElement('div');
      node.className = 'workspace-tab' + (tab.key === current.key ? ' current' : '');
      const link = document.createElement('a');
      link.href = tab.href;
      link.textContent = tab.label;
      if (tab.key === current.key) link.setAttribute('aria-current', 'page');
      node.append(link);
      if (tab.key !== 'overview') {
        const close = document.createElement('button');
        close.type = 'button';
        close.textContent = '×';
        close.setAttribute('aria-label', 'Закрыть вкладку «' + tab.label + '»');
        close.addEventListener('click', () => {
          work.tabs = work.tabs.filter(x => x.key !== tab.key);
          if (tab.key === current.key) {
            const next = work.tabs[work.tabs.length - 1] || route(tools[space][0][2], origin);
            work.active = next.key;
            save();
            // До подтверждения ухода не убираем вкладку с несохранённой формой.
            location.assign(next.href);
          } else {
            save();
            renderTabs();
          }
        });
        node.append(close);
      }
      bar.append(node);
    }
    const activeTab = bar.querySelector('[aria-current="page"]');
    if (activeTab) bar.scrollLeft = Math.max(0, activeTab.parentElement.offsetLeft - bar.offsetLeft - 15);
  }

  function panels() {
    for (const side of ['left', 'right']) {
      const open = work.panels[side];
      const panel = document.getElementById(side === 'left' ? 'workspace-navigation' : 'workspace-inspector');
      document.body.dataset[side + 'Open'] = String(open);
      panel.hidden = !open;
      const toggle = document.querySelector('[data-toggle-panel="' + side + '"]');
      toggle.setAttribute('aria-expanded', String(open));
      toggle.classList.toggle('pressed', open);
      const handle = document.querySelector('[data-resize-panel="' + side + '"]');
      handle.hidden = !open;
      handle.setAttribute('aria-valuenow', String(work.panels[side + 'Width']));
      handle.setAttribute('aria-valuemin', side === 'left' ? '180' : '220');
      handle.setAttribute('aria-valuemax', side === 'left' ? '320' : '380');
      document.body.style.setProperty('--' + side + '-width', work.panels[side + 'Width'] + 'px');
    }
  }
  document.querySelectorAll('[data-toggle-panel]').forEach(button => button.addEventListener('click', () => {
    const side = button.dataset.togglePanel;
    work.panels[side] = !work.panels[side];
    panels();
    save();
  }));
  document.querySelectorAll('[data-resize-panel]').forEach(handle => {
    const side = handle.dataset.resizePanel;
    function resize(width) {
      const minimum = side === 'left' ? 180 : 220;
      const maximum = side === 'left' ? 320 : 380;
      work.panels[side + 'Width'] = Math.max(minimum, Math.min(maximum, width));
      panels();
    }
    handle.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home'].includes(event.key)) return;
      event.preventDefault();
      let delta = event.key === 'ArrowRight' ? 16 : -16;
      if (side === 'right') delta *= -1;
      resize(event.key === 'Home' ? (side === 'left' ? 220 : 260) : work.panels[side + 'Width'] + delta);
      save();
    });
    handle.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      event.preventDefault();
      const startX = event.clientX;
      const width = work.panels[side + 'Width'];
      handle.setPointerCapture(event.pointerId);
      document.body.classList.add('resizing-panels');
      const move = ev => resize(width + (ev.clientX - startX) * (side === 'left' ? 1 : -1));
      const finish = () => {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', finish);
        handle.removeEventListener('pointercancel', finish);
        document.body.classList.remove('resizing-panels');
        save();
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', finish);
      handle.addEventListener('pointercancel', finish);
    });
  });

  // Предупреждаем и для источника/ответа, не только для редактора поста.
  const forms = Array.from(document.forms).filter(form => form.method.toLowerCase() === 'post' && form.dataset.autosave !== 'true');
  const values = form => JSON.stringify(Array.from(form.elements).filter(el => el.name && !el.disabled && !['hidden', 'submit', 'button'].includes(el.type)).map(el => [el.name, ['checkbox', 'radio'].includes(el.type) ? el.checked : el.value]));
  const initial = new Map(forms.map(form => [form, values(form)]));
  const submitting = new Set();
  const indicator = document.getElementById('workspace-save-state');
  const dirty = () => forms.some(form => !submitting.has(form) && (values(form) !== initial.get(form) || form.dataset.unsaved === 'true'));
  const refreshStatus = () => {
    indicator.textContent = dirty() ? 'Есть несохранённые изменения' : storageAvailable ? 'Вкладки и панели запоминаются в этом браузере' : 'Вкладки и панели доступны без сохранения настроек';
  };
  forms.forEach(form => {
    form.addEventListener('input', refreshStatus);
    form.addEventListener('change', refreshStatus);
    form.addEventListener('submit', event => {
      queueMicrotask(() => { if (!event.defaultPrevented) submitting.add(form); });
    });
  });
  window.addEventListener('beforeunload', event => {
    if (dirty()) { event.preventDefault(); event.returnValue = ''; }
  });
  window.addEventListener('pageshow', event => {
    if (event.persisted) {
      // Возврат браузера не должен терять форму или возвращать старую копию вкладок.
      submitting.clear();
      try { state = cleanState(JSON.parse(localStorage.getItem(storageKey) || '{}'), origin); work = state.spaces[space]; } catch (_) { storageAvailable = false; }
      activateCurrent();
      updateSpaceLinks();
      panels();
      renderTabs();
      save();
      if (picker) picker.value = space === 'cccp' ? '/studio/cccp' : '';
      refreshStatus();
    }
  });
  panels();
  renderTabs();
  save();
  refreshStatus();
})();
