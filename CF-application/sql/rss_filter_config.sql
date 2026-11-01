-- CF-02C-012: подготовленная миграция версии правил; рабочая база НЕ изменена.
-- Старые конфигурации и 99 ссылок не переписываются. Используем прежний атомарный cf_filter_save.
BEGIN;
CREATE OR REPLACE FUNCTION public.cf_filter_rules_valid(r jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SECURITY INVOKER SET search_path='' AS $$
 SELECT coalesce(jsonb_typeof(r)='object' AND r->>'version' IN ('1','2')
 AND r->>'combine' IN ('all','any') AND jsonb_typeof(r->'match_forms')='boolean'
 AND jsonb_typeof(r->'auto_select')='boolean'
 AND (r->>'version'='1' OR (jsonb_typeof(r->'filter_enabled')='boolean' AND r->>'category_default' IN ('include','exclude') AND r->>'auto_select'='true'
 AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(CASE WHEN jsonb_typeof(r->'include_categories')='array' THEN r->'include_categories' ELSE '[]' END) a
 JOIN jsonb_array_elements_text(CASE WHEN jsonb_typeof(r->'exclude_categories')='array' THEN r->'exclude_categories' ELSE '[]' END) b
 ON translate(lower(normalize(trim(a.value),NFKC)),'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯё','абвгдеежзийклмнопрстуфхцчшщъыьэюяе')=translate(lower(normalize(trim(b.value),NFKC)),'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯё','абвгдеежзийклмнопрстуфхцчшщъыьэюяе'))))
 AND NOT EXISTS(SELECT 1 FROM unnest(ARRAY['include_categories','exclude_categories','include_words','exclude_words']) k
 WHERE jsonb_typeof(r->k) IS DISTINCT FROM 'array'
 OR jsonb_array_length(CASE WHEN jsonb_typeof(r->k)='array' THEN r->k ELSE '[]' END)>50
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(r->k)='array' THEN r->k ELSE '[]' END) v
 WHERE jsonb_typeof(v)<>'string' OR length(v#>>'{}') NOT BETWEEN 1 AND 100)),false)
$$;
CREATE OR REPLACE FUNCTION public.cf_filter_revision_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$ BEGIN
 IF OLD.filter_rules->>'version'='2' AND coalesce(NEW.filter_rules->>'version','')<>'2' THEN
  RAISE EXCEPTION 'Cannot downgrade filter rules version';
 END IF;
 IF NEW.filter_rules IS DISTINCT FROM OLD.filter_rules OR NEW.enabled IS DISTINCT FROM OLD.enabled THEN
  NEW.filter_revision=OLD.filter_revision+1;
 ELSIF NEW.filter_revision IS DISTINCT FROM OLD.filter_revision THEN
  RAISE EXCEPTION 'Filter revision is managed by trigger';
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION public.cf_filter_import(p_source uuid,p_location text,p_materials jsonb,p_plans jsonb)
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
  IF EXISTS(SELECT 1 FROM public.cf_project_sources WHERE source_id=p_source AND project_code=plan->>'project' AND filter_rules->>'version'='2')
  AND coalesce(plan->>'rules_version','')<>'2' THEN RAISE EXCEPTION 'Filter version 2 requires updated importer'; END IF;
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

REVOKE ALL ON FUNCTION public.cf_filter_rules_valid(jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.cf_filter_rules_valid(jsonb) TO service_role;
COMMIT;
