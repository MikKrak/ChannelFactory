-- library.sql — расширение существующих источников и материалов, без удаления данных.
-- Применять к рабочей базе только после отдельного согласования владельцем.
BEGIN;
CREATE TABLE public.cf_projects (
 code text PRIMARY KEY CHECK(code ~ '^[a-z][a-z0-9_-]{0,39}$'),
 name text NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 200)
);
INSERT INTO public.cf_projects VALUES('cccp','СССР — Свой сад своими руками');
ALTER TABLE public.cf_sources
 ADD COLUMN kind text NOT NULL DEFAULT 'rss' CHECK(kind IN ('rss','website','database','api','file','other')),
 ADD COLUMN location text NOT NULL DEFAULT '',
 ADD COLUMN description text NOT NULL DEFAULT '',
 ADD COLUMN last_import_at timestamptz,
 ADD COLUMN last_import_count integer CHECK(last_import_count>=0);
UPDATE public.cf_sources SET location=coalesce(feed_url,site_url,'');
CREATE UNIQUE INDEX cf_sources_kind_location_unique ON public.cf_sources(kind,btrim(location)) WHERE location<>'';
ALTER TABLE public.cf_materials ADD COLUMN protected boolean NOT NULL DEFAULT false;
CREATE TABLE public.cf_project_sources (
 project_code text NOT NULL REFERENCES public.cf_projects(code),
 source_id uuid NOT NULL REFERENCES public.cf_sources(id),
 enabled boolean NOT NULL DEFAULT true,
 keyword text NOT NULL DEFAULT '' CHECK(length(keyword)<=200),
 notes text NOT NULL DEFAULT '' CHECK(length(notes)<=2000),
 PRIMARY KEY(project_code,source_id)
);
CREATE INDEX cf_project_sources_source_idx ON public.cf_project_sources(source_id);
CREATE TABLE public.cf_project_materials (
 project_code text NOT NULL REFERENCES public.cf_projects(code),
 material_id uuid NOT NULL REFERENCES public.cf_materials(id) ON DELETE RESTRICT,
 selected_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(project_code,material_id)
);
CREATE INDEX cf_project_materials_material_idx ON public.cf_project_materials(material_id);
-- Существующие записи установки принадлежат единственному действующему проекту.
INSERT INTO public.cf_project_sources(project_code,source_id) SELECT 'cccp',id FROM public.cf_sources;
INSERT INTO public.cf_project_materials(project_code,material_id) SELECT 'cccp',id FROM public.cf_materials;

CREATE FUNCTION public.cf_library_save_source(p_id uuid,p_name text,p_kind text,p_location text,p_description text,p_project text DEFAULT NULL)
RETURNS uuid LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
BEGIN
 IF p_id IS NULL OR length(btrim(p_name)) NOT BETWEEN 1 AND 200 OR length(p_location)>2000 OR length(p_description)>4000 THEN
  RAISE EXCEPTION 'Invalid source';
 END IF;
 -- Создание и подключение к проекту — одна транзакция, повтор с тем же id безопасен.
 INSERT INTO public.cf_sources(id,code,name,kind,location,description,feed_url)
 VALUES(p_id,'source_'||replace(p_id::text,'-',''),btrim(p_name),p_kind,btrim(p_location),p_description,CASE WHEN p_kind='rss' THEN p_location END)
 ON CONFLICT(id) DO UPDATE SET name=excluded.name,kind=excluded.kind,location=excluded.location,
 description=excluded.description,feed_url=excluded.feed_url;
 IF p_project IS NOT NULL THEN
  INSERT INTO public.cf_project_sources(project_code,source_id) VALUES(p_project,p_id) ON CONFLICT DO NOTHING;
 END IF;
 RETURN p_id;
END $$;

CREATE FUNCTION public.cf_library_import(p_source uuid,p_location text,p_materials jsonb)
RETURNS integer LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE s public.cf_sources; n integer;
BEGIN
 SELECT * INTO STRICT s FROM public.cf_sources WHERE id=p_source FOR UPDATE;
 IF s.kind<>'rss' OR s.location IS DISTINCT FROM p_location OR jsonb_typeof(p_materials)<>'array'
    OR jsonb_array_length(p_materials)>200 THEN RAISE EXCEPTION 'Source changed or invalid import'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_materials) x WHERE jsonb_typeof(x)<>'object' OR coalesce(x->>'url','')='' OR length(x->>'url')>4000) THEN
  RAISE EXCEPTION 'Invalid material';
 END IF;
 INSERT INTO public.cf_materials(source_id,url,title,published_at,raw_data)
 SELECT p_source,x->>'url',x->>'title',nullif(x->>'published_at','')::timestamptz,coalesce(x->'raw_data','{}')
 FROM jsonb_array_elements(p_materials) x ON CONFLICT(source_id,url) DO NOTHING;
 GET DIAGNOSTICS n=ROW_COUNT;
 -- Повтор RSS не перезаписывает отредактированный материал и не отбирает его в проект.
 UPDATE public.cf_sources SET last_import_at=clock_timestamp(),last_import_count=n WHERE id=p_source;
 RETURN n;
END $$;

CREATE FUNCTION public.cf_library_select(p_project text,p_material uuid DEFAULT NULL,p_source uuid DEFAULT NULL)
RETURNS integer LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE n integer;
BEGIN
 IF (p_material IS NULL)=(p_source IS NULL) THEN RAISE EXCEPTION 'Choose one selection mode'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.cf_projects WHERE code=p_project) THEN RAISE EXCEPTION 'Unknown project'; END IF;
 IF p_material IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.cf_materials WHERE id=p_material) THEN RAISE EXCEPTION 'Unknown material'; END IF;
 INSERT INTO public.cf_project_materials(project_code,material_id)
 SELECT p_project,m.id FROM public.cf_materials m
 WHERE (p_material IS NOT NULL AND m.id=p_material) OR
 (p_source IS NOT NULL AND m.source_id=p_source AND EXISTS(
 SELECT 1 FROM public.cf_project_sources ps WHERE ps.project_code=p_project AND ps.source_id=m.source_id AND ps.enabled
 AND (ps.keyword='' OR strpos(lower(coalesce(m.title,'')),lower(ps.keyword))>0)))
 ON CONFLICT DO NOTHING;
 GET DIAGNOSTICS n=ROW_COUNT; RETURN n;
END $$;

-- Только просмотр: функция не содержит DELETE, маршрута удаления в этой версии нет.
CREATE FUNCTION public.cf_library_cleanup_preview(p_before timestamptz,p_limit integer DEFAULT 50)
RETURNS TABLE(id uuid,title text,imported_at timestamptz) LANGUAGE sql STABLE SECURITY INVOKER SET search_path='' AS $$
 SELECT m.id,m.title,m.imported_at FROM public.cf_materials m
 WHERE m.imported_at<p_before AND NOT m.protected
 AND NOT EXISTS(SELECT 1 FROM public.cf_project_materials pm WHERE pm.material_id=m.id)
 AND NOT EXISTS(SELECT 1 FROM public.cf_posts p WHERE p.material_id=m.id)
 ORDER BY m.imported_at,m.id LIMIT least(greatest(p_limit,1),100)
$$;
CREATE INDEX cf_posts_material_lookup_idx ON public.cf_posts(material_id);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['cf_projects','cf_project_sources','cf_project_materials'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated',t);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON public.%I TO service_role',t);
 END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.cf_library_save_source(uuid,text,text,text,text,text),public.cf_library_import(uuid,text,jsonb),public.cf_library_select(text,uuid,uuid),public.cf_library_cleanup_preview(timestamptz,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.cf_library_save_source(uuid,text,text,text,text,text),public.cf_library_import(uuid,text,jsonb),public.cf_library_select(text,uuid,uuid),public.cf_library_cleanup_preview(timestamptz,integer) TO service_role;
-- Существующие RLS и права cf_sources/cf_materials сохраняются, service_role используется только сервером.
COMMIT;
