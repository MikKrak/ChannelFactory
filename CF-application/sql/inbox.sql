-- Обращения и ручные ответы: только после отдельного разрешения на применение.
-- Самостоятельный скрипт; не меняет таблицы публикаций и чужие объекты.
BEGIN;
CREATE TABLE public.cf_inbox_consumers (
 bot_id bigint PRIMARY KEY CHECK(bot_id>0), project text NOT NULL CHECK(project='cccp'),
 channel_id bigint NOT NULL, chat_id bigint NOT NULL UNIQUE,
 next_offset bigint CHECK(next_offset>=0), owner_token uuid,
 acquired_at timestamptz, recovery_log jsonb NOT NULL DEFAULT '[]', CHECK((owner_token IS NULL)=(acquired_at IS NULL))
);
CREATE TABLE public.cf_inbox_events (
 bot_id bigint NOT NULL REFERENCES public.cf_inbox_consumers(bot_id),
 update_id bigint NOT NULL CHECK(update_id>=0), payload jsonb NOT NULL,
 state text NOT NULL CHECK(state IN ('stored','unsupported','bot_private')),
 received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(bot_id,update_id), CHECK(jsonb_typeof(payload)='object')
);
CREATE TABLE public.cf_inbox_dialogs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 bot_id bigint NOT NULL REFERENCES public.cf_inbox_consumers(bot_id),
 chat_id bigint NOT NULL, topic_id bigint NOT NULL CHECK(topic_id>0),
 reader_id bigint NOT NULL CHECK(reader_id>0), state text NOT NULL DEFAULT 'new' CHECK(state IN ('new','handled')),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(bot_id,chat_id,topic_id)
);
CREATE INDEX cf_inbox_dialogs_recent ON public.cf_inbox_dialogs(updated_at DESC,id);
CREATE TABLE public.cf_inbox_messages (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), dialog_id uuid NOT NULL REFERENCES public.cf_inbox_dialogs(id),
 bot_id bigint NOT NULL, update_id bigint NOT NULL, message_id bigint NOT NULL CHECK(message_id>0),
 text text NOT NULL, sent_at timestamptz NOT NULL,
 FOREIGN KEY(bot_id,update_id) REFERENCES public.cf_inbox_events(bot_id,update_id),
 UNIQUE(bot_id,update_id), UNIQUE(dialog_id,message_id)
);
CREATE INDEX cf_inbox_messages_dialog ON public.cf_inbox_messages(dialog_id,sent_at,id);
CREATE TABLE public.cf_inbox_replies (
 id uuid PRIMARY KEY, dialog_id uuid NOT NULL REFERENCES public.cf_inbox_dialogs(id),
 text text NOT NULL CHECK(length(btrim(text))>0 AND octet_length(text)<=16384),
 state text NOT NULL DEFAULT 'prepared' CHECK(state IN ('prepared','sending','needs_review','sent','cancelled')),
 worker_token uuid, message_id bigint CHECK(message_id>0), sent_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), review_log jsonb NOT NULL DEFAULT '[]',
 CHECK((state='sent')=(message_id IS NOT NULL AND sent_at IS NOT NULL))
);
CREATE UNIQUE INDEX cf_inbox_reply_unresolved ON public.cf_inbox_replies(dialog_id) WHERE state IN ('prepared','sending','needs_review');
CREATE UNIQUE INDEX cf_inbox_reply_receipt ON public.cf_inbox_replies(dialog_id,message_id) WHERE message_id IS NOT NULL;
CREATE INDEX cf_inbox_replies_dialog ON public.cf_inbox_replies(dialog_id,created_at,id);

-- Только RPC изменяют рабочие записи; конфигурацию бота задаёт оператор до запуска.
CREATE FUNCTION public.cf_inbox_guard() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
BEGIN
 IF TG_OP='DELETE' OR coalesce(current_setting('cf.inbox_write',true),'')<>'yes' THEN RAISE EXCEPTION 'Use inbox RPC'; END IF;
 RETURN NEW;
END $$;
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['cf_inbox_consumers','cf_inbox_events','cf_inbox_dialogs','cf_inbox_messages','cf_inbox_replies'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated,service_role',t);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE ON public.%I TO service_role',t);
  EXECUTE format('CREATE TRIGGER inbox_guard BEFORE INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.cf_inbox_guard()',t);
 END LOOP;
END $$;

CREATE FUNCTION public.cf_inbox_configure(p_bot_id bigint,p_channel_id bigint,p_chat_id bigint) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
BEGIN
 PERFORM set_config('cf.inbox_write','yes',true);
 INSERT INTO public.cf_inbox_consumers(bot_id,project,channel_id,chat_id) VALUES(p_bot_id,'cccp',p_channel_id,p_chat_id);
END $$;

-- Захват не протухает автоматически: после аварии сначала остановить старый процесс.
CREATE FUNCTION public.cf_inbox_acquire(p_bot_id bigint,p_token uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE c public.cf_inbox_consumers;
BEGIN
 SELECT * INTO c FROM public.cf_inbox_consumers WHERE bot_id=p_bot_id FOR UPDATE;
 IF NOT FOUND OR p_token IS NULL OR c.owner_token IS NOT NULL THEN RAISE EXCEPTION 'Consumer unavailable'; END IF;
 PERFORM set_config('cf.inbox_write','yes',true);
 UPDATE public.cf_inbox_consumers SET owner_token=p_token,acquired_at=clock_timestamp() WHERE bot_id=p_bot_id;
 RETURN jsonb_build_object('bot_id',c.bot_id,'channel_id',c.channel_id,'chat_id',c.chat_id,'next_offset',c.next_offset);
END $$;
CREATE FUNCTION public.cf_inbox_release(p_bot_id bigint,p_token uuid) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
BEGIN
 PERFORM set_config('cf.inbox_write','yes',true);
 UPDATE public.cf_inbox_consumers SET owner_token=NULL,acquired_at=NULL WHERE bot_id=p_bot_id AND owner_token=p_token;
 IF NOT FOUND THEN RAISE EXCEPTION 'Wrong consumer'; END IF;
END $$;

CREATE FUNCTION public.cf_inbox_recover_consumer(p_bot_id bigint,p_quiesced boolean,p_note text) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
BEGIN
 IF p_quiesced IS DISTINCT FROM true OR nullif(btrim(p_note),'') IS NULL THEN RAISE EXCEPTION 'Stop old consumer first'; END IF;
 PERFORM set_config('cf.inbox_write','yes',true);
 UPDATE public.cf_inbox_consumers SET owner_token=NULL,acquired_at=NULL,
 recovery_log=recovery_log||jsonb_build_array(jsonb_build_object('note',p_note,'at',clock_timestamp())) WHERE bot_id=p_bot_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Consumer missing'; END IF;
END $$;

CREATE FUNCTION public.cf_inbox_store(p_bot_id bigint,p_token uuid,p_updates jsonb) RETURNS bigint
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE c public.cf_inbox_consumers; u jsonb; m jsonb; topic jsonb; uid bigint; prior bigint; old jsonb; d uuid; kind text; mid bigint; body text;
BEGIN
 SELECT * INTO c FROM public.cf_inbox_consumers WHERE bot_id=p_bot_id FOR UPDATE;
 IF NOT FOUND OR c.owner_token IS DISTINCT FROM p_token OR p_token IS NULL THEN RAISE EXCEPTION 'Wrong consumer'; END IF;
 IF jsonb_typeof(p_updates) IS DISTINCT FROM 'array' OR jsonb_array_length(p_updates)>100 THEN RAISE EXCEPTION 'Invalid batch'; END IF;
 PERFORM set_config('cf.inbox_write','yes',true);
 FOR u IN SELECT value FROM jsonb_array_elements(p_updates) LOOP
  IF jsonb_typeof(u->'update_id') IS DISTINCT FROM 'number' OR (u->>'update_id') !~ '^[0-9]+$' THEN RAISE EXCEPTION 'Invalid update'; END IF;
  uid:=(u->>'update_id')::bigint;
  IF prior IS NOT NULL AND uid<=prior THEN RAISE EXCEPTION 'Batch must be ordered'; END IF;
  prior:=uid;
  SELECT payload INTO old FROM public.cf_inbox_events WHERE bot_id=p_bot_id AND update_id=uid;
  IF FOUND THEN
   IF old IS DISTINCT FROM u THEN RAISE EXCEPTION 'Conflicting update'; END IF;
   CONTINUE;
  END IF;
  IF c.next_offset IS NOT NULL AND uid<c.next_offset THEN RAISE EXCEPTION 'Unsaved old event'; END IF;
  m:=u->'message'; topic:=m->'direct_messages_topic'; kind:='unsupported';
  IF m->'chat'->>'type'='private' THEN kind:='bot_private'; END IF;
  IF m->'chat'->>'id'=c.chat_id::text AND m->'chat'->'is_direct_messages'='true'::jsonb
   AND jsonb_typeof(topic->'topic_id')='number' AND (topic->>'topic_id') ~ '^[1-9][0-9]*$'
   AND jsonb_typeof(topic->'user'->'id')='number' AND (topic->'user'->>'id') ~ '^[1-9][0-9]*$'
   AND m->'from'->'id'=topic->'user'->'id' AND m->'from'->'is_bot'='false'::jsonb AND topic->'user'->'is_bot'='false'::jsonb
   AND jsonb_typeof(m->'message_id')='number' AND (m->>'message_id') ~ '^[1-9][0-9]*$'
   AND jsonb_typeof(m->'date')='number' AND (m->>'date') ~ '^[0-9]+$'
   AND jsonb_typeof(m->'text')='string' AND btrim(m->>'text',E' \n\t\r')<>'' THEN kind:='stored'; END IF;
  INSERT INTO public.cf_inbox_events(bot_id,update_id,payload,state) VALUES(p_bot_id,uid,u,kind);
  IF kind='stored' THEN
   mid:=(m->>'message_id')::bigint;body:=m->>'text';
   INSERT INTO public.cf_inbox_dialogs(bot_id,chat_id,topic_id,reader_id)
    VALUES(p_bot_id,c.chat_id,(topic->>'topic_id')::bigint,(topic->'user'->>'id')::bigint)
    ON CONFLICT(bot_id,chat_id,topic_id) DO NOTHING;
   SELECT id INTO d FROM public.cf_inbox_dialogs WHERE bot_id=p_bot_id AND chat_id=c.chat_id AND topic_id=(topic->>'topic_id')::bigint AND reader_id=(topic->'user'->>'id')::bigint FOR UPDATE;
   IF d IS NULL THEN RAISE EXCEPTION 'Reader conflict'; END IF;
   IF EXISTS(SELECT 1 FROM public.cf_inbox_messages WHERE dialog_id=d AND message_id=mid AND (text<>body OR sent_at<>to_timestamp((m->>'date')::bigint))) THEN RAISE EXCEPTION 'Message conflict'; END IF;
   INSERT INTO public.cf_inbox_messages(dialog_id,bot_id,update_id,message_id,text,sent_at)
    VALUES(d,p_bot_id,uid,mid,body,to_timestamp((m->>'date')::bigint)) ON CONFLICT(dialog_id,message_id) DO NOTHING;
   IF FOUND THEN UPDATE public.cf_inbox_dialogs SET state='new',updated_at=clock_timestamp() WHERE id=d; END IF;
  END IF;
 END LOOP;
 IF prior IS NOT NULL THEN
  UPDATE public.cf_inbox_consumers SET next_offset=greatest(coalesce(next_offset,0),prior+1) WHERE bot_id=p_bot_id RETURNING next_offset INTO c.next_offset;
 END IF;
 RETURN c.next_offset;
END $$;

CREATE FUNCTION public.cf_inbox_mark(p_dialog_id uuid,p_state text,p_seen_message uuid) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
BEGIN
 IF p_state NOT IN ('new','handled') THEN RAISE EXCEPTION 'Invalid state'; END IF;
 PERFORM 1 FROM public.cf_inbox_dialogs WHERE id=p_dialog_id FOR UPDATE;
 IF p_state='handled' AND p_seen_message IS DISTINCT FROM (SELECT id FROM public.cf_inbox_messages WHERE dialog_id=p_dialog_id ORDER BY sent_at DESC,id LIMIT 1) THEN RAISE EXCEPTION 'New message arrived; refresh'; END IF;
 PERFORM set_config('cf.inbox_write','yes',true);
 UPDATE public.cf_inbox_dialogs SET state=p_state WHERE id=p_dialog_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Dialog missing'; END IF;
END $$;
CREATE FUNCTION public.cf_inbox_prepare_reply(p_id uuid,p_dialog_id uuid,p_text text) RETURNS uuid
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE r public.cf_inbox_replies;
BEGIN
 PERFORM 1 FROM public.cf_inbox_dialogs WHERE id=p_dialog_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Dialog missing'; END IF;
 SELECT * INTO r FROM public.cf_inbox_replies WHERE id=p_id;
 IF FOUND THEN
  IF r.dialog_id IS DISTINCT FROM p_dialog_id OR r.text IS DISTINCT FROM p_text THEN RAISE EXCEPTION 'Conflicting reply'; END IF;
  RETURN r.id;
 END IF;
 IF p_text IS NULL OR btrim(p_text,E' \n\t\r')='' THEN RAISE EXCEPTION 'Empty text'; END IF;
 -- UTF-16 длина проверяется ниже независимо от клиента.
 IF (SELECT sum(CASE WHEN octet_length(ch)=4 THEN 2 ELSE 1 END) FROM regexp_split_to_table(p_text,'') ch)>4096 THEN RAISE EXCEPTION 'Reply too long'; END IF;
 PERFORM set_config('cf.inbox_write','yes',true);
 INSERT INTO public.cf_inbox_replies(id,dialog_id,text) VALUES(p_id,p_dialog_id,p_text);
 RETURN p_id;
END $$;
CREATE FUNCTION public.cf_inbox_claim_reply(p_id uuid,p_token uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE r public.cf_inbox_replies; d public.cf_inbox_dialogs;
BEGIN
 SELECT * INTO r FROM public.cf_inbox_replies WHERE id=p_id FOR UPDATE;
 IF NOT FOUND OR r.state<>'prepared' OR p_token IS NULL THEN RAISE EXCEPTION 'Reply already claimed'; END IF;
 SELECT * INTO d FROM public.cf_inbox_dialogs WHERE id=r.dialog_id;
 PERFORM set_config('cf.inbox_write','yes',true);
 UPDATE public.cf_inbox_replies SET state='sending',worker_token=p_token WHERE id=p_id;
 RETURN jsonb_build_object('id',r.id,'bot_id',d.bot_id,'chat_id',d.chat_id,'direct_messages_topic_id',d.topic_id,'text',r.text);
END $$;
CREATE FUNCTION public.cf_inbox_cancel_prepared(p_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
BEGIN
 PERFORM set_config('cf.inbox_write','yes',true);
 UPDATE public.cf_inbox_replies SET state='cancelled' WHERE id=p_id AND state='prepared';
 IF NOT FOUND THEN RAISE EXCEPTION 'Reply no longer prepared'; END IF;
END $$;
CREATE FUNCTION public.cf_inbox_record_reply(p_id uuid,p_token uuid,p_chat_id bigint,p_topic_id bigint,p_message_id bigint,p_date timestamptz) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE r public.cf_inbox_replies; d public.cf_inbox_dialogs;
BEGIN
 SELECT * INTO r FROM public.cf_inbox_replies WHERE id=p_id FOR UPDATE;
 IF NOT FOUND OR r.worker_token IS DISTINCT FROM p_token OR p_token IS NULL THEN RAISE EXCEPTION 'Wrong reply worker'; END IF;
 SELECT * INTO d FROM public.cf_inbox_dialogs WHERE id=r.dialog_id;
 IF d.chat_id IS DISTINCT FROM p_chat_id OR d.topic_id IS DISTINCT FROM p_topic_id OR p_message_id IS NULL OR p_message_id<=0 OR p_date IS NULL THEN RAISE EXCEPTION 'Wrong receipt'; END IF;
 IF r.state='sent' THEN
  IF r.message_id IS DISTINCT FROM p_message_id OR r.sent_at IS DISTINCT FROM p_date THEN RAISE EXCEPTION 'Receipt conflict'; END IF;
  RETURN;
 END IF;
 IF r.state NOT IN ('sending','needs_review') THEN RAISE EXCEPTION 'Invalid reply state'; END IF;
 PERFORM set_config('cf.inbox_write','yes',true);
 UPDATE public.cf_inbox_replies SET state='sent',message_id=p_message_id,sent_at=p_date WHERE id=p_id;
END $$;
CREATE FUNCTION public.cf_inbox_review_reply(p_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
BEGIN
 PERFORM set_config('cf.inbox_write','yes',true);
 UPDATE public.cf_inbox_replies SET state='needs_review' WHERE id=p_id AND state='sending';
END $$;
CREATE FUNCTION public.cf_inbox_reconcile_reply(p_id uuid,p_action text,p_note text,p_quiesced boolean,p_message_id bigint DEFAULT NULL,p_date timestamptz DEFAULT NULL) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE r public.cf_inbox_replies;
BEGIN
 SELECT * INTO r FROM public.cf_inbox_replies WHERE id=p_id FOR UPDATE;
 IF NOT FOUND OR r.state<>'needs_review' OR p_quiesced IS DISTINCT FROM true OR nullif(btrim(p_note),'') IS NULL THEN RAISE EXCEPTION 'Stop sender and verify delivery'; END IF;
 PERFORM set_config('cf.inbox_write','yes',true);
 IF p_action='confirm' AND p_message_id>0 AND p_date IS NOT NULL THEN
  UPDATE public.cf_inbox_replies SET state='sent',message_id=p_message_id,sent_at=p_date WHERE id=p_id;
 ELSIF p_action='no_delivery' THEN
  UPDATE public.cf_inbox_replies SET state='cancelled' WHERE id=p_id;
 ELSE RAISE EXCEPTION 'Invalid decision'; END IF;
 UPDATE public.cf_inbox_replies SET review_log=review_log||jsonb_build_array(jsonb_build_object('action',p_action,'note',p_note,'at',clock_timestamp())) WHERE id=p_id;
END $$;
DO $$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname LIKE 'cf_inbox_%' LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated',f.signature);
  EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role',f.signature);
 END LOOP;
END $$;
COMMIT;
