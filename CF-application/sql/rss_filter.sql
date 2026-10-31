-- rss_filter.sql — правила связи источник ↔ проект и решения для новых материалов.
-- Только подготовка: рабочая миграция требует отдельного разрешения владельца.
BEGIN;
CREATE FUNCTION public.cf_filter_rules_valid(r jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
 SELECT coalesce(jsonb_typeof(r)='object' AND r->>'version'='1'
 AND r->>'combine' IN ('all','any') AND jsonb_typeof(r->'match_forms')='boolean'
 AND jsonb_typeof(r->'auto_select')='boolean'
 AND NOT EXISTS(SELECT 1 FROM unnest(ARRAY['include_categories','exclude_categories','include_words','exclude_words']) k
 WHERE jsonb_typeof(r->k) IS DISTINCT FROM 'array'
 OR jsonb_array_length(CASE WHEN jsonb_typeof(r->k)='array' THEN r->k ELSE '[]' END)>50
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(r->k)='array' THEN r->k ELSE '[]' END) v
 WHERE jsonb_typeof(v)<>'string' OR length(v#>>'{}') NOT BETWEEN 1 AND 100)),false)
$$;
ALTER TABLE public.cf_project_sources ADD COLUMN filter_rules jsonb,
 ADD COLUMN filter_revision bigint NOT NULL DEFAULT 0,
 ADD CONSTRAINT cf_filter_rules_check CHECK(filter_rules IS NULL OR public.cf_filter_rules_valid(filter_rules));
CREATE FUNCTION public.cf_filter_revision_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$ BEGIN
 IF NEW.filter_rules IS DISTINCT FROM OLD.filter_rules OR NEW.enabled IS DISTINCT FROM OLD.enabled THEN
  NEW.filter_revision=OLD.filter_revision+1;
 ELSIF NEW.filter_revision IS DISTINCT FROM OLD.filter_revision THEN
  RAISE EXCEPTION 'Filter revision is managed by trigger';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cf_filter_revision_trigger BEFORE UPDATE ON public.cf_project_sources
 FOR EACH ROW EXECUTE FUNCTION public.cf_filter_revision_guard();
CREATE TABLE public.cf_material_filter_results (
 project_code text NOT NULL REFERENCES public.cf_projects(code),
 source_id uuid NOT NULL REFERENCES public.cf_sources(id),
 material_id uuid NOT NULL REFERENCES public.cf_materials(id) ON DELETE CASCADE,
 filter_revision bigint NOT NULL,
 decision text NOT NULL CHECK(decision IN ('accepted','rejected','uncertain')),
 reasons jsonb NOT NULL CHECK(jsonb_typeof(reasons)='array' AND jsonb_array_length(reasons)>0),
 checked_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(project_code,material_id)
);
CREATE INDEX cf_filter_results_review_idx ON public.cf_material_filter_results(project_code,source_id,decision,checked_at DESC);
CREATE INDEX cf_filter_results_material_idx ON public.cf_material_filter_results(material_id);
ALTER TABLE public.cf_material_filter_results ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.cf_material_filter_results FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT ON public.cf_material_filter_results TO service_role;

CREATE FUNCTION public.cf_filter_save(p_source uuid,p_project text,p_revision bigint,p_rules jsonb)
RETURNS bigint LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE current public.cf_project_sources;
BEGIN
 IF NOT public.cf_filter_rules_valid(p_rules) THEN RAISE EXCEPTION 'Invalid rules'; END IF;
 SELECT * INTO STRICT current FROM public.cf_project_sources WHERE source_id=p_source AND project_code=p_project FOR UPDATE;
 IF current.filter_revision IS DISTINCT FROM p_revision THEN RAISE EXCEPTION 'Rules changed; reload before saving'; END IF;
 UPDATE public.cf_project_sources SET filter_rules=p_rules WHERE source_id=p_source AND project_code=p_project
 RETURNING filter_revision INTO p_revision;
 -- Сохранение правил не меняет материалы, результаты и существующие проектные ссылки.
 RETURN p_revision;
END $$;

-- Старый процесс не должен молча импортировать без обязательной классификации.
CREATE OR REPLACE FUNCTION public.cf_library_import(p_source uuid,p_location text,p_materials jsonb)
RETURNS integer LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE s public.cf_sources;n integer;
BEGIN
 SELECT * INTO STRICT s FROM public.cf_sources WHERE id=p_source FOR UPDATE;
 PERFORM 1 FROM public.cf_project_sources WHERE source_id=p_source ORDER BY project_code FOR UPDATE;
 IF EXISTS(SELECT 1 FROM public.cf_project_sources WHERE source_id=p_source AND enabled AND filter_rules->>'auto_select'='true') THEN
  RAISE EXCEPTION 'Configured filters require the new import path';
 END IF;
 IF s.kind<>'rss' OR s.location IS DISTINCT FROM p_location OR jsonb_typeof(p_materials)<>'array' OR jsonb_array_length(p_materials)>200 THEN RAISE EXCEPTION 'Invalid import'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_materials) x WHERE coalesce(x->>'url','')='' OR length(x->>'url')>4000) THEN RAISE EXCEPTION 'Invalid material'; END IF;
 INSERT INTO public.cf_materials(source_id,url,title,published_at,raw_data)
 SELECT p_source,x->>'url',x->>'title',nullif(x->>'published_at','')::timestamptz,coalesce(x->'raw_data','{}')
 FROM jsonb_array_elements(p_materials) x ON CONFLICT(source_id,url) DO NOTHING;
 GET DIAGNOSTICS n=ROW_COUNT;
 UPDATE public.cf_sources SET last_import_at=clock_timestamp(),last_import_count=n WHERE id=p_source;
 RETURN n;
END $$;

CREATE FUNCTION public.cf_filter_import(p_source uuid,p_location text,p_materials jsonb,p_plans jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE s public.cf_sources;actual jsonb;expected jsonb;plan jsonb;new_ids uuid[];new_count integer;selected_count integer;
BEGIN
 SELECT * INTO STRICT s FROM public.cf_sources WHERE id=p_source FOR UPDATE;
 IF s.kind<>'rss' OR s.location IS DISTINCT FROM p_location OR coalesce(jsonb_typeof(p_materials),'null')<>'array'
 OR jsonb_array_length(p_materials)>200 OR coalesce(jsonb_typeof(p_plans),'null')<>'array' THEN RAISE EXCEPTION 'Invalid import'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_materials) x WHERE coalesce(x->>'url','')='' OR length(x->>'url')>4000)
 OR (SELECT count(DISTINCT x->>'url') FROM jsonb_array_elements(p_materials) x)<>jsonb_array_length(p_materials) THEN RAISE EXCEPTION 'Invalid or duplicate URL'; END IF;
 -- Блокировка настроек и сравнение всех версий до любой записи.
 PERFORM 1 FROM public.cf_project_sources WHERE source_id=p_source ORDER BY project_code FOR UPDATE;
 SELECT coalesce(jsonb_agg(jsonb_build_object('project',project_code,'revision',filter_revision) ORDER BY project_code),'[]') INTO actual
 FROM public.cf_project_sources WHERE source_id=p_source AND enabled AND filter_rules IS NOT NULL AND filter_rules->>'auto_select'='true';
 SELECT coalesce(jsonb_agg(jsonb_build_object('project',x->>'project','revision',(x->>'revision')::bigint) ORDER BY x->>'project'),'[]') INTO expected
 FROM jsonb_array_elements(p_plans) x;
 IF actual IS DISTINCT FROM expected THEN RAISE EXCEPTION 'Filter configuration changed; no data saved'; END IF;
 FOR plan IN SELECT * FROM jsonb_array_elements(p_plans) LOOP
  IF jsonb_typeof(plan->'decisions') IS DISTINCT FROM 'array' OR jsonb_array_length(plan->'decisions')<>jsonb_array_length(p_materials)
  OR (SELECT count(DISTINCT x->>'url') FROM jsonb_array_elements(plan->'decisions') x)<>jsonb_array_length(p_materials)
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(plan->'decisions') x
    WHERE coalesce(x->>'state','') NOT IN ('accepted','rejected','uncertain') OR jsonb_typeof(x->'reasons') IS DISTINCT FROM 'array'
    OR jsonb_array_length(x->'reasons')=0
    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_materials) m WHERE m->>'url'=x->>'url')) THEN RAISE EXCEPTION 'Invalid decisions'; END IF;
 END LOOP;
 WITH added AS (
 INSERT INTO public.cf_materials(source_id,url,title,published_at,raw_data)
 SELECT p_source,x->>'url',x->>'title',nullif(x->>'published_at','')::timestamptz,coalesce(x->'raw_data','{}')
 FROM jsonb_array_elements(p_materials) x ON CONFLICT(source_id,url) DO NOTHING RETURNING id)
 SELECT coalesce(array_agg(id),'{}') INTO new_ids FROM added;
 new_count=cardinality(new_ids);
 INSERT INTO public.cf_material_filter_results(project_code,source_id,material_id,filter_revision,decision,reasons)
 SELECT p->>'project',p_source,m.id,(p->>'revision')::bigint,d->>'state',d->'reasons'
 FROM jsonb_array_elements(p_plans) p CROSS JOIN LATERAL jsonb_array_elements(p->'decisions') d
 JOIN public.cf_materials m ON m.source_id=p_source AND m.url=d->>'url' WHERE m.id=ANY(new_ids);
 INSERT INTO public.cf_project_materials(project_code,material_id)
 SELECT project_code,material_id FROM public.cf_material_filter_results
 WHERE material_id=ANY(new_ids) AND source_id=p_source AND decision='accepted' ON CONFLICT DO NOTHING;
 GET DIAGNOSTICS selected_count=ROW_COUNT;
 UPDATE public.cf_sources SET last_import_at=clock_timestamp(),last_import_count=new_count WHERE id=p_source;
 RETURN jsonb_build_object('saved',new_count,'selected',selected_count);
END $$;

-- Массовый старый отбор не обходит настроенный фильтр. Ручной выбор одной статьи сохраняется.
CREATE OR REPLACE FUNCTION public.cf_library_select(p_project text,p_material uuid DEFAULT NULL,p_source uuid DEFAULT NULL)
RETURNS integer LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE n integer;
BEGIN
 IF (p_material IS NULL)=(p_source IS NULL) THEN RAISE EXCEPTION 'Choose one selection mode'; END IF;
 IF p_source IS NOT NULL AND EXISTS(SELECT 1 FROM public.cf_project_sources WHERE project_code=p_project AND source_id=p_source AND filter_rules IS NOT NULL) THEN
  RAISE EXCEPTION 'Use filter preview; existing materials are not selected automatically';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM public.cf_projects WHERE code=p_project) THEN RAISE EXCEPTION 'Unknown project'; END IF;
 IF p_material IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.cf_materials WHERE id=p_material) THEN RAISE EXCEPTION 'Unknown material'; END IF;
 INSERT INTO public.cf_project_materials(project_code,material_id)
 SELECT p_project,m.id FROM public.cf_materials m
 WHERE (p_material IS NOT NULL AND m.id=p_material) OR
 (p_source IS NOT NULL AND m.source_id=p_source AND EXISTS(SELECT 1 FROM public.cf_project_sources ps
 WHERE ps.project_code=p_project AND ps.source_id=m.source_id AND ps.enabled
 AND (ps.keyword='' OR strpos(lower(coalesce(m.title,'')),lower(ps.keyword))>0))) ON CONFLICT DO NOTHING;
 GET DIAGNOSTICS n=ROW_COUNT;RETURN n;
END $$;
CREATE OR REPLACE FUNCTION public.cf_library_cleanup_preview(p_before timestamptz,p_limit integer DEFAULT 50)
RETURNS TABLE(id uuid,title text,imported_at timestamptz) LANGUAGE sql STABLE SECURITY INVOKER SET search_path='' AS $$
 SELECT m.id,m.title,m.imported_at FROM public.cf_materials m WHERE m.imported_at<p_before AND NOT m.protected
 AND NOT EXISTS(SELECT 1 FROM public.cf_project_materials pm WHERE pm.material_id=m.id)
 AND NOT EXISTS(SELECT 1 FROM public.cf_posts p WHERE p.material_id=m.id)
 AND NOT EXISTS(SELECT 1 FROM public.cf_material_filter_results r WHERE r.material_id=m.id AND r.decision='uncertain')
 ORDER BY m.imported_at,m.id LIMIT least(greatest(p_limit,1),100)
$$;
REVOKE ALL ON FUNCTION public.cf_filter_rules_valid(jsonb),public.cf_filter_revision_guard(),public.cf_filter_save(uuid,text,bigint,jsonb),public.cf_filter_import(uuid,text,jsonb,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.cf_filter_rules_valid(jsonb),public.cf_filter_revision_guard(),public.cf_filter_save(uuid,text,bigint,jsonb),public.cf_filter_import(uuid,text,jsonb,jsonb) TO service_role;
COMMIT;
