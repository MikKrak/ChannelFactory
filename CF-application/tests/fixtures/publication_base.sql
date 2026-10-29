-- Только синтетическая база из tests/test_publication_sql.py; не рабочая миграция.
DO $$ BEGIN
 IF current_database()<>'cf_publication_test'
   OR current_setting('data_directory')<>'/private/tmp/cf-publication-pg-20261029' THEN
  RAISE EXCEPTION 'Refusing to reset any non-test database';
 END IF;
END $$;
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
CREATE TABLE public.cf_materials(id uuid primary key default gen_random_uuid());
CREATE TABLE public.cf_posts(
 id uuid primary key default gen_random_uuid(),
 material_id uuid references public.cf_materials(id) on delete set null,
 title text not null default '', blocks jsonb not null default '[]',
 status text not null default 'draft' check(status in ('draft','ready','published')),
 created_at timestamptz not null default now(),updated_at timestamptz not null default now(),published_at timestamptz
);
CREATE FUNCTION public.cf_posts_set_updated_at() returns trigger language plpgsql as $$ BEGIN NEW.updated_at=now(); RETURN NEW; END $$;
CREATE TRIGGER cf_posts_updated_at_trigger BEFORE UPDATE ON public.cf_posts FOR EACH ROW EXECUTE FUNCTION public.cf_posts_set_updated_at();
CREATE UNIQUE INDEX cf_posts_one_draft_per_material ON public.cf_posts(material_id) WHERE status='draft' AND material_id IS NOT NULL;
ALTER TABLE public.cf_posts ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE ON public.cf_posts TO service_role;
