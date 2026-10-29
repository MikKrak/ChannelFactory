/* Предпросмотр, счётчик и предупреждение о несохранённом тексте.
   Сохранение выполняется обычной HTML-формой на сервере, не в браузере. */
(() => {
  document.querySelectorAll('.telegram-preview img, .read-post img').forEach(image => {
    function fallback() {
      const note = document.createElement('div');
      note.className = 'no-image';
      note.textContent = 'Изображение недоступно';
      image.replaceWith(note);
    }
    image.addEventListener('error', fallback, {once: true});
    if (image.complete && image.naturalWidth === 0) fallback();
  });
  const form = document.querySelector('[data-editor]');
  if (!form) return;
  const text = form.querySelector('textarea');
  const preview = document.getElementById('post-preview');
  const count = document.getElementById('char-count');
  const state = document.getElementById('dirty-status');
  const initial = text.value;
  let submitting = false;
  function update() {
    preview.textContent = text.value;
    count.textContent = `${Array.from(text.value).length} символов`;
    if (text.value !== initial) state.textContent = 'Есть несохранённые изменения';
    else state.textContent = state.dataset.initial;
  }
  state.dataset.initial = state.textContent;
  text.addEventListener('input', update);
  form.addEventListener('submit', event => {
    if (submitting) { event.preventDefault(); return; }
    if (!text.value.trim()) {
      event.preventDefault();
      text.setCustomValidity('Добавь непустой текст поста.');
      text.reportValidity();
      return;
    }
    submitting = true;
    state.textContent = 'Сохраняем…';
    // Не отключаем submit-кнопку: её name/action нужен серверу.
    document.body.classList.add('busy');
  });
  text.addEventListener('input', () => text.setCustomValidity(''));
  window.addEventListener('beforeunload', event => {
    if (!submitting && text.value !== initial) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
  // Возврат назад через bfcache должен снова разрешать сохранение.
  window.addEventListener('pageshow', event => {
    if (event.persisted) { submitting = false; document.body.classList.remove('busy'); update(); }
  });
  update();
})();
