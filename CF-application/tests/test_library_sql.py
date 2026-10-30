"""Миграция библиотеки — только синтетическая PostgreSQL, без рабочей Supabase."""
import concurrent.futures
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4
from test_publication_sql import sql,literal

ROOT=Path(__file__).resolve().parents[1]


def fixture():
    sql((ROOT/'tests/fixtures/publication_base.sql').read_text(),False)
    sql('''CREATE TABLE cf_sources(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),code text UNIQUE NOT NULL,name text NOT NULL,feed_url text,site_url text,created_at timestamptz NOT NULL DEFAULT now());
ALTER TABLE cf_materials ADD COLUMN source_id uuid REFERENCES cf_sources(id), ADD COLUMN external_id text, ADD COLUMN url text, ADD COLUMN title text, ADD COLUMN published_at timestamptz, ADD COLUMN imported_at timestamptz NOT NULL DEFAULT now(), ADD COLUMN raw_data jsonb NOT NULL DEFAULT '{}', ADD COLUMN content jsonb;
ALTER TABLE cf_materials ADD CONSTRAINT cf_materials_source_url_unique UNIQUE(source_id,url);
CREATE UNIQUE INDEX cf_materials_source_external_id_unique ON cf_materials(source_id,external_id) WHERE external_id IS NOT NULL;
INSERT INTO cf_sources(id,code,name,feed_url,site_url) VALUES('e3c9eb83-5a5f-4351-836b-c2f93b4fa567','botanichka','Ботаничка','https://www.botanichka.ru/feed/','https://www.botanichka.ru/');
INSERT INTO cf_materials(source_id,url,title,content) SELECT 'e3c9eb83-5a5f-4351-836b-c2f93b4fa567','https://example.com/'||i,'Синтетический материал '||i,'{"text":"Сохранённый текст"}'::jsonb FROM generate_series(1,98) i;
INSERT INTO cf_posts(material_id,title,blocks) SELECT id,'Существующий пост','[{"type":"text","content":"Редакционный текст"}]' FROM cf_materials ORDER BY id LIMIT 7;
GRANT SELECT,INSERT,UPDATE,DELETE ON cf_sources,cf_materials TO service_role;''',False)
    # Действующая функция черновика, прочитана из рабочей схемы; только тестовая копия.
    sql('''CREATE FUNCTION public.cf_save_material_draft(p_material_id uuid,p_title text,p_blocks jsonb) RETURNS uuid LANGUAGE plpgsql SET search_path='' AS $$ DECLARE v_id uuid; BEGIN
INSERT INTO public.cf_posts(material_id,title,blocks,status) VALUES(p_material_id,coalesce(p_title,''),coalesce(p_blocks,'[]'::jsonb),'draft')
ON CONFLICT(material_id) WHERE status='draft' AND material_id IS NOT NULL DO UPDATE SET title=excluded.title,blocks=excluded.blocks RETURNING id INTO v_id; RETURN v_id; END $$;''',False)
    sql((ROOT/'sql/publication.sql').read_text(),False)
    sql((ROOT/'sql/inbox.sql').read_text(),False)


@unittest.skipUnless(os.environ.get('CF_TEST_POSTGRES')=='1','Нужна изолированная PostgreSQL')
class LibrarySQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sql('SHOW data_directory',False).stdout.strip()!='/private/tmp/cf-publication-pg-20261029':
            raise RuntimeError('Refusing non-test cluster')

    def setUp(self):
        fixture()
        self.before=self.fingerprints()
        sql((ROOT/'sql/library.sql').read_text(),False)
        self.sid='e3c9eb83-5a5f-4351-836b-c2f93b4fa567'

    def fingerprints(self):
        return sql("SELECT jsonb_build_object('materials',(SELECT md5(string_agg(to_jsonb(m)::text,'' ORDER BY id)) FROM cf_materials m),'posts',(SELECT md5(string_agg(to_jsonb(p)::text,'' ORDER BY id)) FROM cf_posts p))",False).stdout.strip()

    def call(self,name,*args,check=True):
        return sql('SELECT cf_library_'+name+'('+','.join(literal(x) for x in args)+')',check=check)

    def scalar(self,q):return sql(q).stdout.strip()

    def test_migration_preserves_98_materials_7_posts_and_all_associations(self):
        # Единственное новое поле protected исключено из сравнения старых материалов.
        after=sql("SELECT jsonb_build_object('materials',(SELECT md5(string_agg((to_jsonb(m)-'protected')::text,'' ORDER BY id)) FROM cf_materials m),'posts',(SELECT md5(string_agg(to_jsonb(p)::text,'' ORDER BY id)) FROM cf_posts p))",False).stdout.strip()
        self.assertEqual(self.before,after)
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_project_materials'),'98')
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_project_sources'),'1')
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_projects'),'1')
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_inbox_messages'),'0')

    def test_shared_source_independent_settings_and_material_identity(self):
        sql("INSERT INTO cf_projects VALUES('synthetic','Только тест'); INSERT INTO cf_project_sources(project_code,source_id,keyword) VALUES('synthetic',"+literal(self.sid)+",'материал 98')")
        self.assertEqual(self.call('select','synthetic',None,self.sid).stdout.strip(),'1')
        self.assertEqual(self.call('select','synthetic',None,self.sid).stdout.strip(),'0')
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_materials'),'98')
        self.assertEqual(self.scalar("SELECT keyword FROM cf_project_sources WHERE project_code='cccp'"),'')
        sql("DELETE FROM cf_project_sources WHERE project_code='synthetic'")
        self.assertEqual(self.scalar("SELECT count(*) FROM cf_project_materials WHERE project_code='synthetic'"),'1')

    def test_create_and_attach_atomic_duplicate_location_rejected(self):
        sid=str(uuid4())
        args=[sid,'API','api','https://example.com/api','Описание','cccp']
        self.call('save_source',*args);self.call('save_source',*args)
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_sources'),'2')
        self.assertNotEqual(self.call('save_source',str(uuid4()),*args[1:],check=False).returncode,0)
        bad=str(uuid4())
        self.assertNotEqual(self.call('save_source',bad,'Тест','file','file','', 'missing',check=False).returncode,0)
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_sources WHERE id='+literal(bad)),'0')

    def test_import_preserves_content_dedups_concurrent_and_selection_separate(self):
        old=self.scalar('SELECT url FROM cf_materials ORDER BY id LIMIT 1')
        rows=[{'url':old,'title':'Не перезаписывать','raw_data':{}}, {'url':'https://example.com/new','title':'Новая статья','raw_data':{}}]
        q='SELECT cf_library_import('+literal(self.sid)+",'https://www.botanichka.ru/feed/',"+literal(rows)+')'
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            r=list(pool.map(lambda _:sql(q).stdout.strip(),range(2)))
        self.assertEqual(sorted(r),['0','1'])
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_materials'),'99')
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_project_materials'),'98')
        self.assertEqual(self.scalar("SELECT count(*) FROM cf_materials WHERE title='Не перезаписывать'"),'0')
        self.assertNotEqual(self.call('import',self.sid,'changed',rows,check=False).returncode,0)

    def test_cleanup_excludes_used_protected_and_post_linked_and_never_deletes(self):
        ids=[str(uuid4()) for _ in range(4)]
        for i,mid in enumerate(ids):
            sql('INSERT INTO cf_materials(id,source_id,url,title,protected) VALUES('+','.join([literal(mid),literal(self.sid),literal('https://example.com/candidate'+str(i)),literal('Кандидат'), 'true' if i==0 else 'false'])+')')
        self.call('select','cccp',ids[1],None)
        sql('INSERT INTO cf_posts(material_id) VALUES('+literal(ids[2])+')')
        found=json.loads(sql("SELECT coalesce(jsonb_agg(id),'[]') FROM cf_library_cleanup_preview(now()+interval '1 day')").stdout)
        self.assertEqual(found,[ids[3]])
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_materials'),'102')

    def test_publication_and_inbox_after_library_migration(self):
        from test_incoming import event, BOT, CHANNEL, CHAT
        from publication import build_plan
        mid=self.scalar('SELECT id FROM cf_materials ORDER BY id LIMIT 1')
        blocks=[{'type':'text','content':'Тест совместимости'}]
        pid=self.scalar('SELECT cf_save_material_draft('+literal(mid)+",'Проверка',"+literal(blocks)+')')
        sql("UPDATE cf_posts SET status='ready' WHERE id="+literal(pid))
        rev=self.scalar('SELECT revision FROM cf_posts WHERE id='+literal(pid))
        aid,worker=str(uuid4()),str(uuid4())
        sql('SELECT cf_begin_publication('+','.join(map(literal,[aid,worker,pid,rev,123,-100,build_plan(blocks),None]))+')')
        sql('SELECT cf_claim_publication_part('+','.join(map(literal,[aid,worker,1]))+')')
        sql('SELECT cf_record_publication_part('+','.join(map(literal,[aid,worker,1,-100,1,'2026-10-30T12:00:00Z']))+')')
        sql('SELECT cf_finish_publication('+literal(aid)+')')
        self.assertEqual(self.scalar('SELECT status FROM cf_posts WHERE id='+literal(pid)),'published')
        token=str(uuid4())
        for name,args in [('configure',[BOT,CHANNEL,CHAT]),('acquire',[BOT,token]),('store',[BOT,token,[event()]]),('release',[BOT,token])]:
            sql('SELECT cf_inbox_'+name+'('+','.join(map(literal,args))+')')
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_inbox_messages'),'1')

    def test_anonymous_access_denied(self):
        for role in ('anon','authenticated'):
            for q in ('SELECT * FROM cf_projects',"SELECT cf_library_select('cccp',NULL,NULL)","SELECT * FROM cf_library_cleanup_preview(now())"):
                self.assertNotEqual(sql('SET ROLE '+role+';'+q,False,False).returncode,0)
