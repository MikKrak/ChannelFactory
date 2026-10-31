/* Только добавление выбранной рубрики в текстовое поле; без запросов и сохранения. */
(() => {
  document.querySelectorAll('[data-category-target]').forEach(button => button.addEventListener('click', () => {
    const target=document.getElementById(button.dataset.categoryTarget);
    if (!target) return;
    const values=target.value.split('\n').map(x=>x.trim()).filter(Boolean);
    if (!values.some(x=>x.toLocaleLowerCase()===button.dataset.category.toLocaleLowerCase())) values.push(button.dataset.category);
    target.value=values.join('\n');
    target.dispatchEvent(new Event('input',{bubbles:true}));
    target.focus();
  }));
})();
