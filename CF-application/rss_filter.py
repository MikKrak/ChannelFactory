"""rss_filter.py — объяснимый тематический отбор, без ИИ и внешних моделей.

Рубрики сравниваются точно без учёта регистра. Текст — последовательности слов;
небольшой набор окончаний даёт только приблизительное совпадение словоформ.
Не сохраняет материалы/правила и не делает сетевых запросов.
"""
from collections import Counter
import hashlib
import json
import re
import unicodedata
from bs4 import BeautifulSoup

FIELDS = ('include_categories','exclude_categories','include_words','exclude_words')
LABELS = {'accepted':'Подходит','rejected':'Не подходит','uncertain':'Сомнительно'}
# Это ограниченная эвристика окончаний, не морфологический словарь.
ENDINGS = sorted(('иями','ями','ами','ого','ему','ому','ыми','ими','ией','иях','ах','ях','ов','ев','ей','ый','ий','ой','ая','яя','ое','ее','ые','ие','ую','юю','ать','ять','ить','ия','ие','ию','ии','ывать','ивать','овый','овая','овые','овых','овыми','овому','ового','а','я','ы','и','у','ю','е','о'), key=len, reverse=True)


def plain(value, limit=12000):
    soup=BeautifulSoup(str(value or '')[:50000],'html.parser')
    for tag in soup(['script','style']):tag.decompose()
    return ' '.join(soup.get_text(' ',strip=True).split())[:limit]


def normal(value):
    return ' '.join(unicodedata.normalize('NFKC',str(value or '')).casefold().replace('ё','е').split())


def tokens(value, forms=False):
    words=re.findall(r'[^\W_]+',normal(value),re.UNICODE)
    if not forms:return words
    result=[]
    for word in words:
        if re.fullmatch('[а-я]+',word):
            word=next((word[:-len(end)] for end in ENDINGS if word.endswith(end) and len(word)-len(end)>=3),word)
        result.append(word)
    return result


def normalize_rules(raw):
    """Ограниченная конфигурация, без регулярных выражений и кода пользователя."""
    if isinstance(raw,dict) and raw.get('version')==2:
        from rss_filter_config import normalize
        return normalize(raw)
    if not isinstance(raw,dict):raise ValueError('Правила должны быть объектом.')
    rules={'version':1,'combine':raw.get('combine','all'),'match_forms':raw.get('match_forms',True),'auto_select':raw.get('auto_select',True)}
    if rules['combine'] not in ('all','any') or type(rules['match_forms']) is not bool or type(rules['auto_select']) is not bool:
        raise ValueError('Неверный режим сочетания условий.')
    for field in FIELDS:
        values=raw.get(field,[])
        if isinstance(values,str):values=values.splitlines()
        if not isinstance(values,list) or len(values)>50:raise ValueError('Не более 50 условий в каждом поле.')
        clean=[]
        for value in values:
            if not isinstance(value,str) or len(value)>100:raise ValueError('Каждое условие — строка до 100 символов.')
            value=' '.join(value.strip().split())
            if value and normal(value) not in [normal(x) for x in clean]:
                if field.endswith('words') and (not tokens(value) or len(tokens(value))>12):raise ValueError('Укажи слово или короткую фразу, без выражений.')
                clean.append(value)
        rules[field]=clean
    return rules


def rule_hash(rules):
    return hashlib.sha256(json.dumps(normalize_rules(rules),sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def contains(text, phrase, forms):
    haystack=tokens(text,forms);needle=tokens(phrase,forms)
    return bool(needle) and any(haystack[n:n+len(needle)]==needle for n in range(len(haystack)-len(needle)+1))


def entry_data(entry):
    raw=entry.get('raw_data') if isinstance(entry.get('raw_data'),dict) else entry
    title=plain(entry.get('title') or raw.get('title'))
    description=plain(raw.get('description') or raw.get('summary'))
    cats=raw.get('categories') or []
    if not isinstance(cats,list):cats=[]
    categories=list(dict.fromkeys(plain(x,200) for x in cats if isinstance(x,str) and x.strip()))
    return {'title':title,'description':description,'categories':categories,'url':entry.get('url') or raw.get('url','')}


def classify(entry,rules):
    """Исключения имеют приоритет; неполные нужные поля дают «сомнительно»."""
    if isinstance(rules,dict) and rules.get('version')==2:
        from rss_filter_config import classify as classify_config
        return classify_config(entry,rules)
    r=normalize_rules(rules);data=entry_data(entry)
    categories={normal(x) for x in data['categories']}
    reasons=[];unknown=[]
    def word_hits(terms):
        return [(term,field) for term in terms for field in ('title','description') if contains(data[field],term,r['match_forms'])]
    excluded=[x for x in r['exclude_categories'] if normal(x) in categories]
    if excluded:return {'state':'rejected','reasons':['Исключена рубрика: '+', '.join(excluded)]}
    excluded_words=word_hits(r['exclude_words'])
    if excluded_words:
        term,field=excluded_words[0]
        return {'state':'rejected','reasons':[f'Исключено «{term}» — '+('заголовок' if field=='title' else 'описание')]}
    if r['exclude_categories'] and not categories:unknown.append('Нет рубрик для проверки исключений.')
    if r['exclude_words'] and not data['description']:unknown.append('Нет описания: исключения по тексту проверены не полностью.')
    includes=[]
    if r['include_categories']:
        hits=[x for x in r['include_categories'] if normal(x) in categories]
        includes.append(True if hits else False if categories else None)
        reasons.append('Включена рубрика: '+', '.join(hits) if hits else 'Нет подходящей рубрики.' if categories else 'Источник не указал рубрики.')
    if r['include_words']:
        hits=word_hits(r['include_words'])
        includes.append(True if hits else False if data['description'] else None)
        if hits:
            term,field=hits[0];reasons.append(f'Найдено «{term}» — '+('заголовок' if field=='title' else 'описание'))
        else:reasons.append('Слова/фразы не найдены.' if data['description'] else 'Совпадений в заголовке нет, описание отсутствует.')
    if not includes:
        decision=True if data['title'] or data['description'] or categories else None
        reasons.append('Условия включения не заданы: допускается любая тема.' if decision else 'Нет данных для проверки.')
    elif r['combine']=='all':
        decision=False if False in includes else None if None in includes else True
    else:
        decision=True if True in includes else None if None in includes else False
    if decision is False:return {'state':'rejected','reasons':reasons+['Условия включения не выполнены.']}
    if decision is None or unknown:return {'state':'uncertain','reasons':reasons+unknown}
    return {'state':'accepted','reasons':reasons}


def analyze(entries):
    """Распределение относится только к переданной выборке, не ко всему сайту."""
    categories=Counter();fields=Counter();missing_categories=0;missing_description=0
    for entry in entries:
        data=entry_data(entry)
        for category in data['categories']:categories[category]+=1
        raw=entry.get('raw_data') if isinstance(entry.get('raw_data'),dict) else entry
        if isinstance(raw.get('available_fields'),list):
            for key in set(raw['available_fields']):fields[str(key)]+=1
        else:
            for key,val in raw.items():
                if val not in (None,'',[],{}):fields[str(key)]+=1
        missing_categories+=not bool(data['categories']);missing_description+=not bool(data['description'])
    return {'total':len(entries),'categories':categories.most_common(),'fields':fields.most_common(),'missing_categories':missing_categories,'missing_description':missing_description}
