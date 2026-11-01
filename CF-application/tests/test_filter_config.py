"""Новая модель проверяется отдельно: старые правила не меняются."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
from rss_filter_config import normalize,classify,category_included,suggestion

class ConfigTests(unittest.TestCase):
    def test_default_disabled_and_toggle_preserves_rules(self):
        r=normalize({'include_words':['томат'],'exclude_categories':['Рецепты']})
        self.assertFalse(r['filter_enabled'])
        entry={'title':'Иное','description':'Текст','categories':['Рецепты']}
        self.assertEqual(classify(entry,r)['state'],'accepted')
        self.assertEqual(classify(entry,r,preview=True)['state'],'rejected')
        self.assertEqual(classify(entry,{**r,'filter_enabled':True})['state'],'rejected')
        self.assertEqual(r['include_words'],['томат'])

    def test_each_category_has_two_states_and_included_wins(self):
        r=normalize({'exclude_categories':['Рецепты']})
        self.assertTrue(category_included('Новая',r))
        self.assertFalse(category_included('рецепты',r))
        self.assertEqual(classify({'categories':['Рецепты','Сад']},r,True)['state'],'accepted')
        self.assertEqual(classify({'categories':['Рецепты']},r,True)['state'],'rejected')
        r=normalize({'category_default':'exclude','include_categories':['Сад']})
        self.assertEqual(classify({'categories':['Новое','Сад']},r,True)['state'],'accepted')
        self.assertFalse(category_included('Новое',r))
        with self.assertRaises(ValueError):normalize({'include_categories':['Сад'],'exclude_categories':['сад']})

    def test_missing_categories_text_fallback_and_exclusions(self):
        r=normalize({'include_words':['томат'],'exclude_categories':['Рецепты']})
        self.assertEqual(classify({'title':'Томаты','description':'Томаты растут'},r,True)['state'],'accepted')
        self.assertEqual(classify({'title':'Нечто'},r,True)['state'],'uncertain')
        self.assertEqual(classify({'title':'Нечто','description':'Полный текст'},r,True)['state'],'rejected')
        self.assertEqual(classify({'title':'Нечто'},normalize({}),True)['state'],'uncertain')
        r=normalize({'exclude_words':['реклама']})
        self.assertEqual(classify({'title':'Реклама','categories':['Сад']},r,True)['state'],'rejected')
        self.assertEqual(classify({'title':'Сад','categories':['Сад']},r,True)['state'],'uncertain')

    def test_and_or_and_proposal_never_enables_filter(self):
        entry={'title':'Сад','description':'Цветы','categories':['Сад']}
        r=normalize({'include_words':['томат']})
        self.assertEqual(classify(entry,r,True)['state'],'rejected')
        self.assertEqual(classify(entry,{**r,'combine':'any'},True)['state'],'accepted')
        self.assertIsNone(suggestion({'name':'Числа'},['Сад','Рецепты']))
        p=suggestion({'name':'Уход за садом'},['Уход за садом','Рецепты'])
        self.assertEqual(p['categories'],['Уход за садом'])
        self.assertFalse(normalize({})['filter_enabled'])
