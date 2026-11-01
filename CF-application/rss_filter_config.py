"""rss_filter_config.py — версия 2: рубрики как основания, независимый выключатель.

Чистые функции без сети и хранения. Версия 1 не переосмысляется автоматически.
"""
from rss_filter import normalize_rules as legacy_normalize, normal, contains, entry_data, tokens


def normalize(raw):
    if not isinstance(raw,dict) or raw.get('version',2)!=2:raise ValueError('Нужна конфигурация версии 2.')
    # Общие ограничения длины и словоформ остаются теми же, что в версии 1.
    r=legacy_normalize({k:v for k,v in raw.items() if k!='version'})
    for key,default in [('filter_enabled',False)]:
        value=raw.get(key,default)
        if type(value) is not bool:raise ValueError('Состояние фильтра должно быть явным.')
        r[key]=value
    r['category_default']=raw.get('category_default','include')
    if r['category_default'] not in ('include','exclude'):raise ValueError('Неверное состояние новых рубрик.')
    if set(map(normal,r['include_categories'])) & set(map(normal,r['exclude_categories'])):
        raise ValueError('Рубрика не может быть одновременно включена и исключена.')
    r.update(version=2,auto_select=True)
    return r


def category_included(category,rules):
    key=normal(category)
    if key in set(map(normal,rules['include_categories'])):return True
    if key in set(map(normal,rules['exclude_categories'])):return False
    return rules['category_default']=='include'


def classify(entry,raw,preview=False):
    r=normalize(raw);d=entry_data(entry)
    if not preview and not r['filter_enabled']:
        return {'state':'accepted','reasons':['Фильтр выключен: тематические ограничения не применяются.']}
    def hits(terms):
        return [(term,field) for term in terms for field in ('title','description') if contains(d[field],term,r['match_forms'])]
    deny=hits(r['exclude_words'])
    if deny:
        term,field=deny[0]
        return {'state':'rejected','reasons':[f'Исключающая фраза «{term}» — '+('заголовок' if field=='title' else 'описание')]}
    allowed=[cat for cat in d['categories'] if category_included(cat,r)]
    words=hits(r['include_words']);reasons=[]
    if allowed:reasons.append('Основание — включённая рубрика: '+', '.join(allowed))
    elif d['categories']:reasons.append('Ни одна рубрика материала не включена.')
    else:reasons.append('Без рубрик: тема проверяется по тексту.')
    if words:
        term,field=words[0];reasons.append(f'Найдена фраза «{term}» — '+('заголовок' if field=='title' else 'описание'))
    # Без рубрик текст заменяет отсутствующее рубричное основание даже в режиме И.
    if not d['categories']:
        decision=bool(words) if r['include_words'] else None
        if r['include_words'] and not words and not d['description']:decision=None
    elif not r['include_words']:decision=bool(allowed)
    else:
        text=True if words else False if d['description'] else None
        if r['combine']=='all':decision=False if not allowed or text is False else text
        else:decision=True if allowed or text is True else text
    if decision is False:return {'state':'rejected','reasons':reasons+['Условия отбора не выполнены.']}
    if r['exclude_words'] and not d['description']:
        return {'state':'uncertain','reasons':reasons+['Нет описания: исключающие фразы проверены не полностью.']}
    if decision is None:return {'state':'uncertain','reasons':reasons+['Тематически не определён: данных для подтверждения недостаточно.']}
    return {'state':'accepted','reasons':reasons}


def suggestion(project,categories):
    """Только совпадение слов в имени/описании; предложение никогда не применяется само."""
    context=' '.join(str(project.get(k) or '') for k in ('name','description'))
    common={'для','при','под','над','или','как','это','что','так','про','все','сво','наш','ваш','мой','его','нее','она','они'}
    words={x for x in tokens(context,True) if len(x)>=3 and x not in common}
    matched=[c for c in categories if words & {x for x in tokens(c,True) if len(x)>=3 and x not in common}]
    if not matched:return None
    return {'categories':matched,'reason':'Совпали слова в названии/описании проекта и названиях рубрик. Это подсказка по словам, не анализ смысла.'}
