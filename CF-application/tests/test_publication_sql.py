"""SQL-интеграции: только одноразовый кластер /private/tmp/cf-publication-pg-20261029.

Запуск: CF_TEST_POSTGRES=1 .venv/bin/python -m unittest discover -s tests -v
Никогда не подключается к SUPABASE_URL; psql — локальный Unix socket.
"""
import concurrent.futures
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from publication import build_plan


def literal(value):
    if value is None:return 'NULL'
    if isinstance(value,(dict,list)):return "'"+json.dumps(value,ensure_ascii=False).replace("'","''")+"'::jsonb"
    return "'"+str(value).replace("'","''")+"'"


def sql(query,role=True,check=True):
    cmd=['psql','-X','-qAt','-h','/private/tmp','-p','55439','-d','cf_publication_test','-v','ON_ERROR_STOP=1']
    result=subprocess.run(cmd,input=('SET ROLE service_role;\n' if role else '')+query,text=True,capture_output=True,timeout=20)
    if check and result.returncode:raise AssertionError(result.stderr)
    return result


@unittest.skipUnless(os.environ.get('CF_TEST_POSTGRES')=='1','Изолированная PostgreSQL явно не включена')
class SQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # До любого изменения убеждаемся, что это наш временный кластер.
        directory=sql("SHOW data_directory",False).stdout.strip()
        if directory!='/private/tmp/cf-publication-pg-20261029':raise RuntimeError('Refusing non-test cluster')
        root=Path(__file__).resolve().parents[1]
        sql((root/'tests/fixtures/publication_base.sql').read_text(),False)
        sql((root/'sql/publication.sql').read_text(),False)

    def setUp(self):
        sql('TRUNCATE public.cf_posts CASCADE;',False)
        self.pid=str(uuid4());self.aid=str(uuid4());self.worker=str(uuid4())
        self.blocks=[{'type':'text','content':'Первая часть '+('😀'*5000)}]
        self.plan=build_plan(self.blocks)
        sql(f"INSERT INTO cf_posts(id,title,blocks) VALUES({literal(self.pid)},'Тест',{literal(self.blocks)}); UPDATE cf_posts SET status='ready' WHERE id={literal(self.pid)};")

    def begin_query(self,aid=None,plan=None):
        return f"SELECT cf_begin_publication({literal(aid or self.aid)},{literal(self.worker)},{literal(self.pid)},2,123,-100,{literal(self.plan if plan is None else plan)},NULL);"

    def call(self,name,*args,check=True):
        return sql('SELECT '+name+'('+','.join(literal(v) for v in args)+');',check=check)

    def state(self):
        return sql(f'SELECT state FROM cf_publication_attempts WHERE id={literal(self.aid)}').stdout.strip()

    def test_plan_matches_python_unicode(self):
        result=sql(f'SELECT cf_publication_plan({literal(self.blocks)},NULL)').stdout
        self.assertEqual(json.loads(result),self.plan)
        for length in (0,1,1024,1025,4096,4097):
            blocks=[{'type':'image','url':'https://example.com/a.png'},{'type':'text','content':'😀'*max(1,length)}]
            media={'url':'https://example.com/a.png','mime':'image/png','sha256':'a'*64}
            self.assertEqual(json.loads(sql(f'SELECT cf_publication_plan({literal(blocks)},{literal(media)})').stdout),build_plan(blocks,media))

    def test_tampered_plan_and_stale_revision_rejected(self):
        bad=copy.deepcopy(self.plan);bad[0]['payload']['text']='Подмена'
        self.assertNotEqual(sql(self.begin_query(plan=bad),check=False).returncode,0)
        self.assertNotEqual(sql(self.begin_query().replace(',2,123,',',1,123,'),check=False).returncode,0)
        self.assertEqual(sql('SELECT count(*) FROM cf_publication_attempts').stdout.strip(),'0')

    def test_two_concurrent_begins(self):
        queries=['BEGIN;'+self.begin_query()+"SELECT pg_sleep(0.3);COMMIT;",self.begin_query(str(uuid4()))]
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda q:sql(q,check=False),queries))
        self.assertEqual(sum(r.returncode==0 for r in results),1)
        self.assertEqual(sql('SELECT count(*) FROM cf_publication_attempts').stdout.strip(),'1')

    def test_complete_and_idempotent_receipts_and_finalization(self):
        sql(self.begin_query())
        for n in range(1,len(self.plan)+1):
            self.call('cf_claim_publication_part',self.aid,self.worker,n)
            self.call('cf_record_publication_part',self.aid,self.worker,n,-100,n,'2026-10-29T12:00:00Z')
            self.call('cf_record_publication_part',self.aid,self.worker,n,-100,n,'2026-10-29T12:00:00Z')
        self.call('cf_finish_publication',self.aid);self.call('cf_finish_publication',self.aid)
        self.assertEqual(self.state(),'succeeded')
        self.assertEqual(sql(f"SELECT status FROM cf_posts WHERE id={literal(self.pid)}").stdout.strip(),'published')
        self.assertNotEqual(sql(self.begin_query(str(uuid4())),check=False).returncode,0)

    def test_claim_cannot_repeat_or_skip_and_edit_locked(self):
        sql(self.begin_query())
        self.assertNotEqual(self.call('cf_claim_publication_part',self.aid,self.worker,2,check=False).returncode,0)
        self.call('cf_claim_publication_part',self.aid,self.worker,1)
        self.assertNotEqual(self.call('cf_claim_publication_part',self.aid,self.worker,1,check=False).returncode,0)
        self.assertNotEqual(sql(f"UPDATE cf_posts SET status='draft' WHERE id={literal(self.pid)}",check=False).returncode,0)
        self.assertNotEqual(self.call('cf_claim_publication_part',self.aid,None,2,check=False).returncode,0)

    def test_restart_and_late_receipt_do_not_resume(self):
        sql(self.begin_query());self.call('cf_claim_publication_part',self.aid,self.worker,1)
        self.call('cf_review_publication',self.aid,'process_lost',1,False)
        self.call('cf_record_publication_part',self.aid,self.worker,1,-100,123,'2026-10-29T12:00:00Z')
        self.assertEqual(self.state(),'needs_review')
        self.assertNotEqual(self.call('cf_claim_publication_part',self.aid,self.worker,2,check=False).returncode,0)
        self.assertNotEqual(sql(self.begin_query(str(uuid4())),check=False).returncode,0)
        self.assertNotEqual(self.call('cf_finish_publication',self.aid,check=False).returncode,0)

    def test_direct_updates_and_public_access_denied(self):
        sql(self.begin_query())
        self.assertNotEqual(sql(f"UPDATE cf_publication_parts SET payload='{{}}' WHERE attempt_id={literal(self.aid)}",check=False).returncode,0)
        self.assertNotEqual(sql(f"UPDATE cf_posts SET status='published',published_at=now() WHERE id={literal(self.pid)}",check=False).returncode,0)
        self.assertNotEqual(sql('SET ROLE anon; SELECT * FROM cf_publication_attempts;',False,False).returncode,0)
        self.assertNotEqual(sql('SET ROLE anon; SELECT cf_finish_publication('+literal(self.aid)+');',False,False).returncode,0)

    def test_manual_reconciliation_and_cancel_guard(self):
        # Одинарная часть позволяет проверить полный ручной финал после потери ответа.
        sql(f"UPDATE cf_posts SET status='draft' WHERE id={literal(self.pid)}; UPDATE cf_posts SET blocks='[{{\"type\":\"text\",\"content\":\"Короткий пост\"}}]' WHERE id={literal(self.pid)}; UPDATE cf_posts SET status='ready' WHERE id={literal(self.pid)}")
        self.blocks=[{'type':'text','content':'Короткий пост'}];self.plan=build_plan(self.blocks)
        sql(self.begin_query().replace(',2,123,',',4,123,'))
        self.call('cf_claim_publication_part',self.aid,self.worker,1)
        self.call('cf_review_publication',self.aid,'transport',1,False)
        self.assertNotEqual(self.call('cf_reconcile_publication',self.aid,'confirm','Владелец','Проверено',False,1,333,'2026-10-29T12:00:00Z',check=False).returncode,0)
        self.call('cf_reconcile_publication',self.aid,'confirm','Владелец','Проверено в канале',True,1,333,'2026-10-29T12:00:00Z')
        self.assertNotEqual(self.call('cf_reconcile_publication',self.aid,'cancel_no_delivery','Владелец','Нет',True,check=False).returncode,0)
        self.call('cf_finish_publication',self.aid)
        self.assertEqual(self.state(),'succeeded')

    def test_edit_and_begin_compete_on_post_lock(self):
        edit = "BEGIN; UPDATE cf_posts SET status='draft' WHERE id="+literal(self.pid)+"; SELECT pg_sleep(0.3); COMMIT;"
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda q:sql(q,check=False),[edit,self.begin_query()]))
        self.assertEqual(sum(r.returncode==0 for r in results),1)

    def test_expired_attempt_cannot_reclaim_or_restart(self):
        sql("SELECT set_config('cf.publication_write','yes',false); INSERT INTO cf_publication_attempts(id,post_id,post_revision,bot_id,chat_id,snapshot,worker_token,review_after) VALUES("+','.join([literal(self.aid),literal(self.pid),'2','123','-100',"'{}'",literal(self.worker),"now()-interval '1 minute'"])+"); INSERT INTO cf_publication_parts(attempt_id,ordinal,chat_id,method,payload) VALUES("+literal(self.aid)+",1,-100,'sendMessage','{\"text\":\"hello\"}');")
        self.assertNotEqual(self.call('cf_claim_publication_part',self.aid,self.worker,1,check=False).returncode,0)
        self.assertNotEqual(sql(self.begin_query(str(uuid4())),check=False).returncode,0)
        self.call('cf_review_publication',self.aid,'expired')
        self.assertEqual(self.state(),'needs_review')

    def test_cancel_is_audited_and_same_version_is_never_retried(self):
        sql(self.begin_query());self.call('cf_review_publication',self.aid,'interrupted')
        args=[self.aid,'cancel_no_delivery','Владелец','Отправитель остановлен; канал проверен',True]
        self.call('cf_reconcile_publication',*args)
        self.call('cf_reconcile_publication',*args)
        self.assertEqual(self.state(),'cancelled_no_delivery')
        self.assertEqual(sql('SELECT jsonb_array_length(review_log) FROM cf_publication_attempts').stdout.strip(),'1')
        self.assertNotEqual(sql(self.begin_query(str(uuid4())),check=False).returncode,0)
        sql("UPDATE cf_posts SET status='draft' WHERE id="+literal(self.pid)+"; UPDATE cf_posts SET status='ready' WHERE id="+literal(self.pid))
        self.assertEqual(sql(self.begin_query(str(uuid4())).replace(',2,123,',',3,123,'),check=False).returncode,0)

    def test_edit_and_mark_ready_in_single_update(self):
        sql("UPDATE cf_posts SET status='draft' WHERE id="+literal(self.pid))
        sql("UPDATE cf_posts SET blocks='[{\"type\":\"text\",\"content\":\"Исправленный готовый текст\"}]',status='ready' WHERE id="+literal(self.pid))
        row=json.loads(sql("SELECT row_to_json(x) FROM (SELECT status,revision FROM cf_posts WHERE id="+literal(self.pid)+") x").stdout)
        self.assertEqual(row,{'status':'ready','revision':3})

    def test_python_repository_to_real_sql_complete_cycle(self):
        from publication import SupabasePublicationRepository, publish
        from types import SimpleNamespace
        class Query:
            def __init__(self,table):self.table=table;self.filters=[];self.sort='';self.limit_value=''
            def select(self,fields):self.fields=fields;return self
            def eq(self,column,value):self.filters.append(column+'='+literal(value));return self
            def order(self,column,desc=False):self.sort=' ORDER BY '+column+(' DESC' if desc else '');return self
            def limit(self,count):self.limit_value=' LIMIT '+str(count);return self
            def execute(self):
                query='SELECT coalesce(jsonb_agg(to_jsonb(x)),\'[]\'::jsonb) FROM (SELECT '+self.fields+' FROM '+self.table+' WHERE '+' AND '.join(self.filters)+self.sort+self.limit_value+') x'
                return SimpleNamespace(data=json.loads(sql(query).stdout))
        class Client:
            def table(self,table):return Query(table)
            def rpc(self,name,params):
                query='SELECT to_jsonb('+name+'('+','.join(k+'=>'+literal(v) for k,v in params.items())+'))'
                return SimpleNamespace(execute=lambda:SimpleNamespace(data=json.loads(sql(query).stdout)))
        fake=SimpleNamespace(db=Client(),get_post=lambda pid:json.loads(sql('SELECT to_jsonb(p) FROM cf_posts p WHERE id='+literal(pid)).stdout))
        repo=SupabasePublicationRepository(fake)
        class Transport:
            def ensure_enabled(self,id):pass
            def prepare(self,image):return None,None
            def target(self):return 123,-100
            def send(self,part,raw,chat):
                self.sent+=1
                return {'chat_id':chat,'message_id':self.sent,'date':'2026-10-29T12:00:00+00:00'}
        tr=Transport();tr.sent=0
        aid=publish(repo,tr,self.pid,2)
        self.assertEqual(repo.latest(self.pid)['state'],'succeeded')
        self.assertEqual(len(repo.parts(aid)),tr.sent)
        self.assertEqual(repo.post(self.pid)['status'],'published')


if __name__=='__main__': unittest.main()
