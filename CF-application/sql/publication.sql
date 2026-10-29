-- Надёжная публикация: применять только после согласования целевой БД.
-- Две таблицы журнала; без изменений таблиц диалогов и чужих объектов.
BEGIN;
ALTER TABLE public.cf_posts ADD COLUMN revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0);
CREATE TABLE public.cf_publication_attempts (
 id uuid PRIMARY KEY,
 post_id uuid NOT NULL REFERENCES public.cf_posts(id) ON DELETE RESTRICT,
 post_revision bigint NOT NULL CHECK(post_revision > 0),
 bot_id bigint NOT NULL CHECK(bot_id > 0), chat_id bigint NOT NULL,
 snapshot jsonb NOT NULL CHECK(jsonb_typeof(snapshot)='object'),
 plan_version text NOT NULL DEFAULT 'telegram-plain-v1' CHECK(plan_version='telegram-plain-v1'),
 state text NOT NULL DEFAULT 'sending' CHECK(state IN ('sending','needs_review','succeeded','cancelled_no_delivery')),
 worker_token uuid NOT NULL,
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 review_after timestamptz NOT NULL DEFAULT (clock_timestamp()+interval '5 minutes'),
 finished_at timestamptz, reason_code text,
 review_note text, reviewed_by text, reviewed_at timestamptz,
 review_log jsonb NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(review_log)='array'),
 UNIQUE(post_id,post_revision), UNIQUE(id,chat_id)
);
CREATE UNIQUE INDEX cf_publication_one_unresolved ON public.cf_publication_attempts(post_id)
 WHERE state IN ('sending','needs_review');
CREATE TABLE public.cf_publication_parts (
 attempt_id uuid NOT NULL, ordinal integer NOT NULL CHECK(ordinal>0), chat_id bigint NOT NULL,
 method text NOT NULL CHECK(method IN ('sendMessage','sendPhoto')),
 payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','in_flight','confirmed','rejected','unknown')),
 request_started_at timestamptz, message_id bigint CHECK(message_id>0),
 telegram_date timestamptz, recorded_at timestamptz,
 confirmation_source text CHECK(confirmation_source IN ('api','manual')), reason_code text,
 PRIMARY KEY(attempt_id,ordinal),
 FOREIGN KEY(attempt_id,chat_id) REFERENCES public.cf_publication_attempts(id,chat_id) ON DELETE RESTRICT,
 CHECK((state='confirmed' AND message_id IS NOT NULL AND telegram_date IS NOT NULL
   AND recorded_at IS NOT NULL AND confirmation_source IS NOT NULL)
 OR (state<>'confirmed' AND message_id IS NULL AND telegram_date IS NULL
   AND recorded_at IS NULL AND confirmation_source IS NULL))
);
CREATE UNIQUE INDEX cf_publication_message_unique ON public.cf_publication_parts(chat_id,message_id) WHERE message_id IS NOT NULL;
ALTER TABLE public.cf_publication_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cf_publication_parts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.cf_publication_attempts,public.cf_publication_parts FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT,INSERT,UPDATE ON public.cf_publication_attempts,public.cf_publication_parts TO service_role;

-- Unicode-кодовые точки обходятся целиком; символы вне BMP занимают 2 UTF-16 units.
CREATE FUNCTION public.cf_publication_chunks(p_text text,p_limit integer) RETURNS text[]
LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
DECLARE result text[] := ARRAY[]::text[]; part text := ''; ch text; units integer:=0; width integer; i integer;
BEGIN
 IF p_limit<2 THEN RAISE EXCEPTION 'Invalid limit'; END IF;
 FOR i IN 1..char_length(p_text) LOOP
  ch:=substr(p_text,i,1); width:=CASE WHEN octet_length(ch)=4 THEN 2 ELSE 1 END;
  IF units+width>p_limit THEN result:=array_append(result,part);part:='';units:=0; END IF;
  part:=part||ch;units:=units+width;
 END LOOP;
 IF part<>'' THEN result:=array_append(result,part); END IF;
 RETURN result;
END $$;

-- SQL независимо строит ТОТ ЖЕ план из заблокированного снимка, а не доверяет клиенту.
CREATE FUNCTION public.cf_publication_plan(p_blocks jsonb,p_media jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
DECLARE b jsonb; txt text:=''; chunk text; image text; has_text boolean:=false; result jsonb:='[]'; arr text[];
BEGIN
 IF jsonb_typeof(p_blocks) IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'Invalid blocks'; END IF;
 FOR b IN SELECT value FROM jsonb_array_elements(p_blocks) LOOP
  IF b->>'type'='image' THEN image:=nullif(b->>'url','');
  ELSIF b->>'type'='text' THEN
   IF btrim(coalesce(b->>'content',''),E' \t\r\n')<>'' THEN has_text:=true; END IF;
   IF coalesce(b->>'content','')<>'' THEN
    txt:=txt||CASE WHEN txt='' THEN '' ELSE E'\n\n' END||(b->>'content');
   END IF;
  ELSIF b->>'type'='source' AND coalesce(b->>'url','')<>'' THEN
   txt:=txt||CASE WHEN txt='' THEN '' ELSE E'\n\n' END||'Источник: '||(b->>'url');
  END IF;
 END LOOP;
 IF NOT has_text THEN RAISE EXCEPTION 'Empty post text'; END IF;
 IF image IS NOT NULL THEN
  IF p_media IS NULL OR jsonb_typeof(p_media) IS DISTINCT FROM 'object'
    OR p_media->>'url' IS DISTINCT FROM image
    OR coalesce(p_media->>'sha256','') !~ '^[0-9a-f]{64}$'
    OR coalesce(p_media->>'mime','') NOT IN ('image/jpeg','image/png','image/webp')
    OR p_media - ARRAY['url','sha256','mime'] <> '{}'::jsonb THEN
    RAISE EXCEPTION 'Invalid prepared image';
  END IF;
  arr:=public.cf_publication_chunks(txt,1024);
  IF cardinality(arr)=1 THEN
   RETURN jsonb_build_array(jsonb_build_object('method','sendPhoto','payload',p_media||jsonb_build_object('caption',txt)));
  END IF;
  result:=result||jsonb_build_array(jsonb_build_object('method','sendPhoto','payload',p_media));
 ELSIF p_media IS NOT NULL THEN RAISE EXCEPTION 'Unexpected media';
 END IF;
 FOREACH chunk IN ARRAY public.cf_publication_chunks(txt,4096) LOOP
  result:=result||jsonb_build_array(jsonb_build_object('method','sendMessage','payload',jsonb_build_object('text',chunk)));
 END LOOP;
 IF jsonb_array_length(result)>100 THEN RAISE EXCEPTION 'Post too large'; END IF;
 RETURN result;
END $$;

-- Маркер принадлежит текущей транзакции RPC; прямые REST UPDATE журналов запрещены.
CREATE FUNCTION public.cf_publication_guard_rows() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Publication history is immutable'; END IF;
 IF coalesce(current_setting('cf.publication_write',true),'')<>'yes' THEN RAISE EXCEPTION 'Use publication RPC'; END IF;
 IF TG_OP='INSERT' THEN RETURN NEW; END IF;
 IF TG_TABLE_NAME='cf_publication_attempts' THEN
  IF ROW(NEW.id,NEW.post_id,NEW.post_revision,NEW.bot_id,NEW.chat_id,NEW.snapshot,NEW.plan_version,NEW.worker_token,NEW.started_at,NEW.review_after)
   IS DISTINCT FROM ROW(OLD.id,OLD.post_id,OLD.post_revision,OLD.bot_id,OLD.chat_id,OLD.snapshot,OLD.plan_version,OLD.worker_token,OLD.started_at,OLD.review_after)
   THEN RAISE EXCEPTION 'Attempt snapshot is immutable'; END IF;
  IF OLD.state IN ('succeeded','cancelled_no_delivery') AND NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'Attempt is closed'; END IF;
  IF NEW.state<>OLD.state AND NOT (OLD.state='sending' AND NEW.state IN ('needs_review','succeeded')
    OR OLD.state='needs_review' AND NEW.state IN ('succeeded','cancelled_no_delivery')) THEN RAISE EXCEPTION 'Invalid attempt transition'; END IF;
 ELSE
  IF ROW(NEW.attempt_id,NEW.ordinal,NEW.chat_id,NEW.method,NEW.payload)
   IS DISTINCT FROM ROW(OLD.attempt_id,OLD.ordinal,OLD.chat_id,OLD.method,OLD.payload) THEN RAISE EXCEPTION 'Plan is immutable'; END IF;
  IF OLD.state='confirmed' AND NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'Receipt is immutable'; END IF;
  IF NEW.state<>OLD.state AND NOT (OLD.state='pending' AND NEW.state='in_flight'
    OR OLD.state='in_flight' AND NEW.state IN ('confirmed','rejected','unknown')
    OR OLD.state='unknown' AND NEW.state='confirmed') THEN RAISE EXCEPTION 'Invalid part transition'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cf_attempts_guard BEFORE INSERT OR UPDATE OR DELETE ON public.cf_publication_attempts FOR EACH ROW EXECUTE FUNCTION public.cf_publication_guard_rows();
CREATE TRIGGER cf_parts_guard BEFORE INSERT OR UPDATE OR DELETE ON public.cf_publication_parts FOR EACH ROW EXECUTE FUNCTION public.cf_publication_guard_rows();

CREATE FUNCTION public.cf_guard_post_revision() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE changed boolean;
BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.status<>'draft' OR NEW.published_at IS NOT NULL THEN RAISE EXCEPTION 'New posts start as drafts'; END IF;
  NEW.revision:=1;RETURN NEW;
 END IF;
 changed:=ROW(NEW.title,NEW.blocks,NEW.material_id) IS DISTINCT FROM ROW(OLD.title,OLD.blocks,OLD.material_id);
 IF OLD.status='published' AND (changed OR NEW.status<>OLD.status OR NEW.published_at IS DISTINCT FROM OLD.published_at) THEN RAISE EXCEPTION 'Published post is immutable'; END IF;
 IF changed AND OLD.status<>'draft' THEN RAISE EXCEPTION 'Edit drafts only'; END IF;
 IF EXISTS(SELECT 1 FROM public.cf_publication_attempts WHERE post_id=OLD.id AND state IN ('sending','needs_review'))
   AND (changed OR NEW.status<>OLD.status OR NEW.published_at IS DISTINCT FROM OLD.published_at) THEN RAISE EXCEPTION 'Review publication first'; END IF;
 NEW.revision:=OLD.revision+CASE WHEN changed OR (OLD.status='draft' AND NEW.status='ready') THEN 1 ELSE 0 END;
 IF NEW.status='published' AND OLD.status<>'published' THEN
  IF NEW.published_at IS NULL OR NOT EXISTS(SELECT 1 FROM public.cf_publication_attempts a WHERE a.post_id=OLD.id AND a.post_revision=OLD.revision AND a.state='succeeded'
    AND EXISTS(SELECT 1 FROM public.cf_publication_parts x WHERE x.attempt_id=a.id)
    AND NOT EXISTS(SELECT 1 FROM public.cf_publication_parts x WHERE x.attempt_id=a.id AND x.state<>'confirmed')
    AND NEW.published_at=(SELECT max(x.telegram_date) FROM public.cf_publication_parts x WHERE x.attempt_id=a.id)) THEN RAISE EXCEPTION 'Incomplete receipts'; END IF;
 ELSIF NEW.published_at IS DISTINCT FROM OLD.published_at THEN RAISE EXCEPTION 'Publication time requires receipts'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cf_posts_revision_guard BEFORE INSERT OR UPDATE ON public.cf_posts FOR EACH ROW EXECUTE FUNCTION public.cf_guard_post_revision();

CREATE FUNCTION public.cf_begin_publication(p_attempt_id uuid,p_worker_token uuid,p_post_id uuid,p_expected_revision bigint,p_bot_id bigint,p_chat_id bigint,p_parts jsonb,p_media jsonb)
RETURNS uuid LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE p public.cf_posts%rowtype; plan jsonb; part jsonb; n integer:=0;
BEGIN
 SELECT * INTO p FROM public.cf_posts WHERE id=p_post_id FOR UPDATE;
 IF NOT FOUND OR p.status<>'ready' OR p.revision IS DISTINCT FROM p_expected_revision THEN RAISE EXCEPTION 'Post not ready or revision changed'; END IF;
 IF EXISTS(SELECT 1 FROM public.cf_publication_attempts WHERE post_id=p.id AND (post_revision=p.revision OR state IN ('sending','needs_review'))) THEN RAISE EXCEPTION 'Attempt already exists'; END IF;
 plan:=public.cf_publication_plan(p.blocks,p_media);
 IF plan IS DISTINCT FROM p_parts THEN RAISE EXCEPTION 'Plan does not match locked post'; END IF;
 PERFORM set_config('cf.publication_write','yes',true);
 INSERT INTO public.cf_publication_attempts(id,post_id,post_revision,bot_id,chat_id,snapshot,worker_token)
 VALUES(p_attempt_id,p.id,p.revision,p_bot_id,p_chat_id,jsonb_build_object('title',p.title,'blocks',p.blocks,'material_id',p.material_id),p_worker_token);
 FOR part IN SELECT value FROM jsonb_array_elements(plan) LOOP
  n:=n+1;
  INSERT INTO public.cf_publication_parts(attempt_id,ordinal,chat_id,method,payload) VALUES(p_attempt_id,n,p_chat_id,part->>'method',part->'payload');
 END LOOP;
 RETURN p_attempt_id;
END $$;

-- Порядок блокировок во всех RPC: post -> attempt -> part.
CREATE FUNCTION public.cf_lock_publication(p_attempt_id uuid) RETURNS public.cf_publication_attempts
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE a public.cf_publication_attempts;
BEGIN
 SELECT * INTO a FROM public.cf_publication_attempts WHERE id=p_attempt_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Attempt not found'; END IF;
 PERFORM 1 FROM public.cf_posts WHERE id=a.post_id FOR UPDATE;
 SELECT * INTO a FROM public.cf_publication_attempts WHERE id=p_attempt_id FOR UPDATE;
 RETURN a;
END $$;

CREATE FUNCTION public.cf_claim_publication_part(p_attempt_id uuid,p_worker_token uuid,p_ordinal integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE a public.cf_publication_attempts; part public.cf_publication_parts;
BEGIN
 a:=public.cf_lock_publication(p_attempt_id);
 IF a.worker_token IS DISTINCT FROM p_worker_token OR a.state<>'sending' OR clock_timestamp()>=a.review_after THEN RAISE EXCEPTION 'Attempt not claimable'; END IF;
 IF EXISTS(SELECT 1 FROM public.cf_publication_parts WHERE attempt_id=a.id AND ordinal<p_ordinal AND state<>'confirmed') THEN RAISE EXCEPTION 'Previous part not confirmed'; END IF;
 SELECT * INTO part FROM public.cf_publication_parts WHERE attempt_id=a.id AND ordinal=p_ordinal FOR UPDATE;
 IF NOT FOUND OR part.state<>'pending' THEN RAISE EXCEPTION 'Part already claimed or missing'; END IF;
 PERFORM set_config('cf.publication_write','yes',true);
 UPDATE public.cf_publication_parts SET state='in_flight',request_started_at=clock_timestamp() WHERE attempt_id=a.id AND ordinal=p_ordinal;
 RETURN jsonb_build_object('method',part.method,'payload',part.payload);
END $$;

CREATE FUNCTION public.cf_record_publication_part(p_attempt_id uuid,p_worker_token uuid,p_ordinal integer,p_chat_id bigint,p_message_id bigint,p_date timestamptz) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE a public.cf_publication_attempts; part public.cf_publication_parts;
BEGIN
 a:=public.cf_lock_publication(p_attempt_id);
 IF a.worker_token IS DISTINCT FROM p_worker_token OR a.chat_id IS DISTINCT FROM p_chat_id THEN RAISE EXCEPTION 'Wrong worker or target'; END IF;
 SELECT * INTO part FROM public.cf_publication_parts WHERE attempt_id=a.id AND ordinal=p_ordinal FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Part missing'; END IF;
 IF part.state='confirmed' THEN
  IF part.message_id IS DISTINCT FROM p_message_id OR part.telegram_date IS DISTINCT FROM p_date THEN RAISE EXCEPTION 'Conflicting receipt'; END IF;
  RETURN;
 END IF;
 IF a.state NOT IN ('sending','needs_review') OR part.state NOT IN ('in_flight','unknown') THEN RAISE EXCEPTION 'Part not in flight'; END IF;
 IF p_message_id IS NULL OR p_message_id<=0 OR p_date IS NULL THEN RAISE EXCEPTION 'Invalid receipt'; END IF;
 PERFORM set_config('cf.publication_write','yes',true);
 UPDATE public.cf_publication_parts SET state='confirmed',message_id=p_message_id,telegram_date=p_date,recorded_at=clock_timestamp(),confirmation_source='api'
 WHERE attempt_id=a.id AND ordinal=p_ordinal;
END $$;

CREATE FUNCTION public.cf_review_publication(p_attempt_id uuid,p_reason text,p_ordinal integer DEFAULT NULL,p_rejected boolean DEFAULT false) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE a public.cf_publication_attempts;
BEGIN
 a:=public.cf_lock_publication(p_attempt_id);
 IF p_reason NOT IN ('transport','telegram_rejected','database','process_lost','expired','receipt_conflict','interrupted') THEN RAISE EXCEPTION 'Invalid reason'; END IF;
 IF a.state IN ('succeeded','cancelled_no_delivery') THEN RETURN; END IF;
 PERFORM set_config('cf.publication_write','yes',true);
 UPDATE public.cf_publication_attempts SET state='needs_review',reason_code=p_reason WHERE id=a.id;
 IF p_ordinal IS NOT NULL THEN
  UPDATE public.cf_publication_parts SET state=CASE WHEN p_rejected THEN 'rejected' ELSE 'unknown' END,reason_code=p_reason
  WHERE attempt_id=a.id AND ordinal=p_ordinal AND state='in_flight';
 END IF;
END $$;

CREATE FUNCTION public.cf_finish_publication(p_attempt_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE a public.cf_publication_attempts; sent_at timestamptz;
BEGIN
 a:=public.cf_lock_publication(p_attempt_id);
 IF a.state='succeeded' THEN RETURN; END IF;
 IF a.state NOT IN ('sending','needs_review') OR NOT EXISTS(SELECT 1 FROM public.cf_publication_parts WHERE attempt_id=a.id)
  OR EXISTS(SELECT 1 FROM public.cf_publication_parts WHERE attempt_id=a.id AND state<>'confirmed') THEN RAISE EXCEPTION 'Incomplete receipts'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.cf_posts WHERE id=a.post_id AND revision=a.post_revision AND status='ready') THEN RAISE EXCEPTION 'Post changed'; END IF;
 SELECT max(telegram_date) INTO sent_at FROM public.cf_publication_parts WHERE attempt_id=a.id;
 PERFORM set_config('cf.publication_write','yes',true);
 UPDATE public.cf_publication_attempts SET state='succeeded',finished_at=clock_timestamp() WHERE id=a.id;
 UPDATE public.cf_posts SET status='published',published_at=sent_at WHERE id=a.post_id;
END $$;

CREATE FUNCTION public.cf_reconcile_publication(p_attempt_id uuid,p_action text,p_reviewer text,p_note text,p_quiesced boolean,p_ordinal integer DEFAULT NULL,p_message_id bigint DEFAULT NULL,p_date timestamptz DEFAULT NULL) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE a public.cf_publication_attempts; part public.cf_publication_parts;
BEGIN
 a:=public.cf_lock_publication(p_attempt_id);
 IF p_quiesced IS DISTINCT FROM true OR nullif(btrim(p_reviewer),'') IS NULL OR nullif(btrim(p_note),'') IS NULL THEN RAISE EXCEPTION 'Stop sender and supply review evidence'; END IF;
 IF a.state='cancelled_no_delivery' AND p_action='cancel_no_delivery'
   AND a.review_note=p_note AND a.reviewed_by=p_reviewer THEN RETURN; END IF;
 IF a.state<>'needs_review' THEN RAISE EXCEPTION 'Review required'; END IF;
 PERFORM set_config('cf.publication_write','yes',true);
 IF p_action='confirm' THEN
  SELECT * INTO part FROM public.cf_publication_parts WHERE attempt_id=a.id AND ordinal=p_ordinal FOR UPDATE;
  IF NOT FOUND OR part.state NOT IN ('in_flight','unknown','confirmed') THEN RAISE EXCEPTION 'Only uncertain sent parts can be reconciled'; END IF;
  IF part.state='confirmed' THEN
   IF part.message_id IS DISTINCT FROM p_message_id OR part.telegram_date IS DISTINCT FROM p_date THEN RAISE EXCEPTION 'Conflicting receipt'; END IF;
   RETURN;
  END IF;
  IF p_message_id IS NULL OR p_message_id<=0 OR p_date IS NULL THEN RAISE EXCEPTION 'Invalid receipt'; END IF;
  UPDATE public.cf_publication_parts SET state='confirmed',message_id=p_message_id,telegram_date=p_date,recorded_at=clock_timestamp(),confirmation_source='manual' WHERE attempt_id=a.id AND ordinal=p_ordinal;
 ELSIF p_action='cancel_no_delivery' THEN
  IF EXISTS(SELECT 1 FROM public.cf_publication_parts WHERE attempt_id=a.id AND state='confirmed') THEN RAISE EXCEPTION 'Delivery exists; cannot cancel'; END IF;
  UPDATE public.cf_publication_attempts SET state='cancelled_no_delivery',finished_at=clock_timestamp(),review_note=p_note,reviewed_by=p_reviewer,reviewed_at=clock_timestamp(),
   review_log=review_log||jsonb_build_array(jsonb_build_object('action',p_action,'reviewer',p_reviewer,'note',p_note,'ordinal',p_ordinal,'message_id',p_message_id,'date',p_date,'reviewed_at',clock_timestamp())) WHERE id=a.id;
  RETURN;
 ELSE RAISE EXCEPTION 'Unknown review action'; END IF;
 UPDATE public.cf_publication_attempts SET review_note=p_note,reviewed_by=p_reviewer,reviewed_at=clock_timestamp(),
   review_log=review_log||jsonb_build_array(jsonb_build_object('action',p_action,'reviewer',p_reviewer,'note',p_note,'ordinal',p_ordinal,'message_id',p_message_id,'date',p_date,'reviewed_at',clock_timestamp())) WHERE id=a.id;
END $$;

-- Только новые cf_* функции; существующие функции и чужие права не затрагиваются.
DO $$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname IN ('cf_publication_chunks','cf_publication_plan','cf_publication_guard_rows','cf_guard_post_revision','cf_begin_publication','cf_lock_publication','cf_claim_publication_part','cf_record_publication_part','cf_review_publication','cf_finish_publication','cf_reconcile_publication') LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated',f.signature);
  EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role',f.signature);
 END LOOP;
END $$;
COMMIT;
