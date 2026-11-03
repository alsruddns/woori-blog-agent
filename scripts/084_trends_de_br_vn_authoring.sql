-- Expand Google Trends collection and authoring to operator-registered DE/BR/VN.
-- This migration grants no Blogger publication authority and creates no Jobs.
ALTER TABLE trend_collection_runs DROP CONSTRAINT trend_collection_runs_geo_check;
ALTER TABLE trend_collection_runs ADD CONSTRAINT trend_collection_runs_geo_check
 CHECK (geo IN ('KR','US','JP','TW','HK','SG','GB','CA','AU','IN','PH','DE','BR','VN'));

ALTER TABLE trend_collection_attempts DROP CONSTRAINT trend_collection_attempts_geo_check;
ALTER TABLE trend_collection_attempts ADD CONSTRAINT trend_collection_attempts_geo_check
 CHECK (geo IN ('KR','US','JP','TW','HK','SG','GB','CA','AU','IN','PH','DE','BR','VN'));

ALTER TABLE trend_observations DROP CONSTRAINT trend_observations_geo_check;
ALTER TABLE trend_observations ADD CONSTRAINT trend_observations_geo_check
 CHECK (geo IN ('KR','US','JP','TW','HK','SG','GB','CA','AU','IN','PH','DE','BR','VN'));

ALTER TABLE trend_topics DROP CONSTRAINT trend_topics_representative_geo_check;
ALTER TABLE trend_topics ADD CONSTRAINT trend_topics_representative_geo_check
 CHECK (representative_geo IN ('KR','US','JP','TW','HK','SG','GB','CA','AU','IN','PH','DE','BR','VN'));

ALTER TABLE trend_blog_geo_authoring DROP CONSTRAINT trend_blog_geo_authoring_geo_check;
ALTER TABLE trend_blog_geo_authoring ADD CONSTRAINT trend_blog_geo_authoring_geo_check
 CHECK (geo IN ('KR','US','JP','TW','HK','SG','GB','CA','AU','IN','PH','DE','BR','VN'));
ALTER TABLE trend_blog_geo_authoring DROP CONSTRAINT trend_blog_geo_authoring_processing_order_check;
ALTER TABLE trend_blog_geo_authoring ADD CONSTRAINT trend_blog_geo_authoring_processing_order_check
 CHECK (processing_order BETWEEN 1 AND 14);

-- Exact owner-requested source-to-blog authoring mappings. Existing settings are
-- preserved; publication policy rows and Publishing Jobs are not created. A
-- test or older install may not yet have the operator-created blog rows; absent
-- rows remain unconfigured and are reported rather than guessed or fabricated.
WITH expected(geo,language_code,blog_id,host) AS (VALUES
 ('DE','de','5857406989226346280','trend-journal-de'),
 ('BR','pt-BR','2780805325207451782','trend-journal-br'),
 ('VN','vi','2392412558893856604','trend-journal-vn')
)
INSERT INTO trend_blog_geo_authoring(blog_id,geo,enabled,processing_order)
SELECT b.id,e.geo,true,1
FROM expected e JOIN blogger_blogs b ON b.blog_id=e.blog_id AND b.language_code=e.language_code
JOIN languages l ON l.code=b.language_code AND l.active
JOIN language_profiles p ON p.language_code=b.language_code AND p.target_country=e.geo
WHERE b.active AND b.url='https://' || e.host || '.blogspot.com'
  AND NOT EXISTS (SELECT 1 FROM trend_blog_geo_authoring current WHERE current.geo=e.geo AND current.enabled)
ON CONFLICT(blog_id,geo) DO NOTHING;

WITH expected(geo,language_code,blog_id,host) AS (VALUES
 ('DE','de','5857406989226346280','trend-journal-de'),
 ('BR','pt-BR','2780805325207451782','trend-journal-br'),
 ('VN','vi','2392412558893856604','trend-journal-vn')
), actual AS (
 SELECT e.geo,e.language_code,e.blog_id
 FROM expected e JOIN blogger_blogs b ON b.blog_id=e.blog_id AND b.language_code=e.language_code
 JOIN languages l ON l.code=b.language_code AND l.active
 JOIN trend_blog_geo_authoring m ON m.blog_id=b.id AND m.geo=e.geo AND m.enabled
 WHERE b.active AND b.url='https://' || e.host || '.blogspot.com'
)
INSERT INTO audit_events(event_type,payload)
SELECT 'trend.authoring.geo_mappings_changed', jsonb_build_object(
 'work_id','P5-CODEX-118', 'actor','operator: explicit P5-CODEX-118 request',
 'configured_mappings',COALESCE((SELECT jsonb_agg(jsonb_build_object('geo',geo,'language_code',language_code,'blog_id',blog_id)) FROM actual),'[]'::jsonb),
 'missing_mappings',(SELECT count(*) FROM expected e WHERE NOT EXISTS (
   SELECT 1 FROM actual a WHERE a.geo=e.geo AND a.blog_id=e.blog_id)),
 'publication_authority_changed',false);

INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.trends_de_br_vn_authoring.migrated',
  '{"version":84,"new_geos":["DE","BR","VN"],"existing_observations_preserved":true,"publication_authority":false,"publishing_jobs_created":false}');
INSERT INTO schema_migrations(version) VALUES(84);
