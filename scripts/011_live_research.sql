ALTER TABLE generation_settings ADD COLUMN engine text NOT NULL DEFAULT 'ollama' CHECK(engine IN ('ollama','llamacpp'));
ALTER TABLE generation_settings DROP CONSTRAINT generation_settings_timeout_seconds_check;
ALTER TABLE generation_settings ADD CHECK(timeout_seconds BETWEEN 5 AND 180);
ALTER TABLE generation_results DROP CONSTRAINT generation_results_state_check;
ALTER TABLE generation_results ADD CHECK(state IN ('mock_draft','human_review_required','quality_held'));
CREATE TABLE collection_sources (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), adapter text UNIQUE NOT NULL CHECK(adapter IN ('fed_rss','wikidata')),
 name text NOT NULL, endpoint text NOT NULL, terms_url text NOT NULL, rights text NOT NULL,
 active boolean NOT NULL DEFAULT true, interval_minutes integer NOT NULL DEFAULT 60 CHECK(interval_minutes>=60),
 last_collected_at timestamptz, last_error text,
 next_run_at timestamptz NOT NULL DEFAULT now(), scheduled boolean NOT NULL DEFAULT false,
 profile_id uuid REFERENCES language_profiles(id), auto_generate boolean NOT NULL DEFAULT false);
CREATE TABLE collection_topics (
 source_id uuid NOT NULL REFERENCES collection_sources(id), category_id uuid NOT NULL REFERENCES categories(id),
 query text NOT NULL, PRIMARY KEY(source_id,category_id));
ALTER TABLE job_runs DROP CONSTRAINT job_runs_task_kind_check;
ALTER TABLE job_runs ADD CHECK(task_kind IN ('diagnostic','content','collection'));
CREATE TABLE collection_jobs (
 run_id uuid PRIMARY KEY REFERENCES job_runs(id), source_id uuid NOT NULL REFERENCES collection_sources(id),
 profile_id uuid NOT NULL REFERENCES language_profiles(id), auto_generate boolean NOT NULL DEFAULT false);
CREATE TABLE collection_items (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_id uuid NOT NULL REFERENCES collection_sources(id),
 external_id text NOT NULL, keyword_id uuid NOT NULL REFERENCES keyword_candidates(id),
 research_source_id uuid NOT NULL REFERENCES research_sources(id), payload_hash text NOT NULL,
 collected_at timestamptz NOT NULL DEFAULT now(), UNIQUE(source_id,external_id,payload_hash));
CREATE TABLE model_measurements (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), model text NOT NULL, revision text NOT NULL,
 language_code text NOT NULL REFERENCES languages(code), material_hash text NOT NULL,
 status text NOT NULL CHECK(status IN ('succeeded','failed')), sample jsonb, checks jsonb NOT NULL,
 metrics jsonb NOT NULL, error_category text, created_at timestamptz NOT NULL DEFAULT now());
CREATE TRIGGER collection_item_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON collection_items FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER model_measurement_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON model_measurements FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER collection_source_audit AFTER INSERT OR UPDATE ON collection_sources FOR EACH ROW EXECUTE FUNCTION audit_configuration();
GRANT SELECT,INSERT,UPDATE ON collection_sources TO woori_app;
GRANT SELECT,INSERT ON collection_topics,collection_jobs,collection_items,model_measurements TO woori_app;
INSERT INTO collection_sources(adapter,name,endpoint,terms_url,rights) VALUES
 ('fed_rss','Federal Reserve Board press releases','https://www.federalreserve.gov/feeds/press_all.xml','https://www.federalreserve.gov/disclaimer.htm','Board-authored text public domain unless indicated; cite Board; exclude third-party material'),
 ('wikidata','Wikidata structured topic metadata','https://www.wikidata.org/w/api.php','https://www.wikidata.org/wiki/Wikidata:Licensing','CC0 structured entity metadata; community-curated, not primary factual verification');
INSERT INTO collection_topics SELECT s.id,c.id,'press releases' FROM collection_sources s,categories c WHERE s.adapter='fed_rss' AND c.slug='finance';
INSERT INTO collection_topics SELECT s.id,c.id,CASE c.slug
 WHEN 'finance' THEN 'finance' WHEN 'stocks' THEN 'stock market' WHEN 'crypto' THEN 'cryptocurrency'
 WHEN 'k-pop' THEN 'K-pop' WHEN 'k-beauty' THEN 'cosmetics' WHEN 'korea-travel' THEN 'Gyeongbokgung'
 WHEN 'korea-food' THEN 'Korean cuisine' END FROM collection_sources s,categories c
 WHERE s.adapter='wikidata' AND c.slug IN ('finance','stocks','crypto','k-pop','k-beauty','korea-travel','korea-food');
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO woori_app;
INSERT INTO schema_migrations(version) VALUES(11);
INSERT INTO audit_events(event_type,payload) VALUES('schema.live_research.migrated','{"version":11}');
