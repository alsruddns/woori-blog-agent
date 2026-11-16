-- Additive research policy metadata and immutable completed-article evaluations.
ALTER TABLE collection_sources
 DROP CONSTRAINT collection_sources_adapter_check;
ALTER TABLE collection_sources ADD CONSTRAINT collection_sources_adapter_check
 CHECK(adapter IN ('fed_rss','wikidata','sec_edgar'));
ALTER TABLE collection_sources
 ADD COLUMN IF NOT EXISTS last_attempt_at timestamptz,
 ADD COLUMN IF NOT EXISTS last_successful_at timestamptz,
 ADD COLUMN IF NOT EXISTS terms_reviewed_at date,
 ADD COLUMN IF NOT EXISTS source_policy jsonb NOT NULL DEFAULT '{}'::jsonb;
UPDATE collection_sources SET
 last_successful_at=last_collected_at,
 terms_reviewed_at=DATE '2026-10-26',
 source_policy=jsonb_build_object(
   'pricing','No account or per-call fee identified for this reviewed public endpoint',
   'reuse','See provider terms URL; cite source and exclude third-party assets',
   'application_rate_limit','3 requests/minute; 24/hour process cap; one collection job/hour',
   'commercial_use','Reviewed for official public information only')
WHERE adapter='fed_rss' AND source_policy='{}'::jsonb;

INSERT INTO collection_sources(adapter,name,endpoint,terms_url,rights,active,interval_minutes,
 profile_id,auto_generate,terms_reviewed_at,source_policy)
SELECT 'sec_edgar','SEC EDGAR company submissions and XBRL facts',
 'https://data.sec.gov/submissions/',
 'https://www.sec.gov/about/webmaster-frequently-asked-questions',
 'SEC states government-created SEC site and EDGAR public filing content is free to access and reuse; cite the underlying filing and do not copy third-party assets.',
 true,1440,p.id,false,DATE '2026-10-26',
 '{"pricing":"Public data.sec.gov JSON endpoints; no API key or per-call fee identified","provider_rate_limit":"SEC fair access maximum 10 requests/second","application_rate_limit":"3 requests/minute; 24/hour process cap; one collection job/hour","commercial_use":"SEC says government-created SEC.gov and EDGAR public filing content may be reused; third-party filing exhibits/assets excluded","terms_url":"https://www.sec.gov/about/webmaster-frequently-asked-questions","terms_reviewed_at":"2026-10-26","data_scope":"Company submissions history and companyfacts XBRL only; latest 10-K/10-Q per configured CIK","automatic_generation":false}'::jsonb
FROM language_profiles p WHERE p.language_code='ko' AND p.target_country=''
AND NOT EXISTS(SELECT 1 FROM collection_sources WHERE adapter='sec_edgar');
INSERT INTO collection_topics(source_id,category_id,query)
SELECT s.id,c.id,'0000320193' FROM collection_sources s,categories c
WHERE s.adapter='sec_edgar' AND c.slug='stocks'
AND NOT EXISTS(SELECT 1 FROM collection_topics t WHERE t.source_id=s.id AND t.category_id=c.id);

CREATE TABLE article_quality_evaluations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 batch_id uuid NOT NULL, topic_key text NOT NULL, topic text NOT NULL,
 language_code text NOT NULL REFERENCES languages(code),
 content_version_id uuid REFERENCES content_versions(id),
 title text NOT NULL DEFAULT '', source_ids uuid[] NOT NULL CHECK(cardinality(source_ids)>0),
 fact_ids uuid[] NOT NULL CHECK(cardinality(fact_ids)>0),
 summary text NOT NULL DEFAULT '', model text NOT NULL, prompt_version text NOT NULL,
 metrics jsonb NOT NULL, checks jsonb NOT NULL,
 machine_passed boolean NOT NULL, human_review_required boolean NOT NULL DEFAULT true,
 error_category text,
 status text NOT NULL CHECK(status IN ('failed','quality_held','machine_passed_review_required')),
 publish_ready boolean NOT NULL DEFAULT false CHECK(NOT publish_ready),
 elapsed_ms integer NOT NULL CHECK(elapsed_ms>=0), ai_calls integer NOT NULL CHECK(ai_calls>=0),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(batch_id,topic_key,language_code)
);
CREATE TRIGGER article_quality_evaluations_immutable
 BEFORE UPDATE OR DELETE OR TRUNCATE ON article_quality_evaluations
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE INDEX article_quality_recent ON article_quality_evaluations(created_at DESC);
GRANT SELECT,INSERT ON article_quality_evaluations TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.full_article_evaluations.migrated','{"version":19}');
INSERT INTO schema_migrations(version) VALUES(19);
