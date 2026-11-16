-- Trend-derived candidates, conservative grouping, scored reviews, and immutable research packages.
ALTER TABLE trend_observations
  ADD COLUMN source_language text;

CREATE TABLE trend_topics (
 id uuid PRIMARY KEY,
 normalized_key text NOT NULL,
 representative_geo text NOT NULL CHECK(representative_geo IN ('KR','US','JP','TW','HK','SG')),
 representative_query text NOT NULL,
 source_language text NOT NULL DEFAULT 'und',
 grouping_method text NOT NULL CHECK(grouping_method IN ('same_query_same_geo','single_observation')),
 grouping_confidence numeric(4,3) NOT NULL CHECK(grouping_confidence BETWEEN 0 AND 1),
 grouping_status text NOT NULL CHECK(grouping_status='exact_query_cluster_not_event_confirmed'),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(representative_geo,normalized_key)
);
CREATE TABLE trend_topic_memberships (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 topic_id uuid NOT NULL REFERENCES trend_topics(id),
 observation_id uuid NOT NULL REFERENCES trend_observations(id),
 grouping_rationale text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(topic_id,observation_id)
);
CREATE TABLE trend_grouping_proposals (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 observation_a uuid NOT NULL REFERENCES trend_observations(id),
 observation_b uuid NOT NULL REFERENCES trend_observations(id),
 method text NOT NULL CHECK(method IN ('same_query_cross_geo','lexical_similarity')),
 confidence numeric(4,3) NOT NULL CHECK(confidence BETWEEN 0 AND 1),
 rationale text NOT NULL,
 status text NOT NULL DEFAULT 'human_review_required' CHECK(status='human_review_required'),
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK(observation_a < observation_b),
 UNIQUE(observation_a,observation_b,method)
);
CREATE TABLE trend_scoring_configs (
 version integer PRIMARY KEY,
 weights jsonb NOT NULL,
 thresholds jsonb NOT NULL,
 rationale text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO trend_scoring_configs(version,weights,thresholds,rationale) VALUES
 (1,
  '{"source_interest_label":15,"freshness":15,"specificity":20,"reviewed_source_coverage":20,"independent_confirmation":20,"deduplication_risk":10}',
  '{"minimum_score":70,"minimum_verified_facts":3,"minimum_independent_sources":2,"human_review_always_required":true}',
  'Initial transparent rubric: source labels are evidence, never converted into rank or fabricated volume; reader value and analytical suitability remain human-reviewed. Broad exact queries, missing current reviewed sources, or absent verified facts are held.');
CREATE TABLE trend_topic_assessments (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 topic_id uuid NOT NULL REFERENCES trend_topics(id),
 config_version integer NOT NULL REFERENCES trend_scoring_configs(version),
 snapshot_sha256 text NOT NULL CHECK(snapshot_sha256 ~ '^[a-f0-9]{64}$'),
 score numeric(5,2) NOT NULL CHECK(score BETWEEN 0 AND 100),
 decision text NOT NULL CHECK(decision IN ('held','review_required')),
 signals jsonb NOT NULL,
 reasons text[] NOT NULL,
 human_review_required boolean NOT NULL DEFAULT true CHECK(human_review_required),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(topic_id,config_version,snapshot_sha256)
);
CREATE TABLE trend_topic_editorial_decisions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 topic_id uuid NOT NULL REFERENCES trend_topics(id),
 decision text NOT NULL CHECK(decision IN ('selected','excluded','hold')),
 reviewer text NOT NULL CHECK(length(trim(reviewer)) BETWEEN 2 AND 120),
 reason text NOT NULL CHECK(length(trim(reason)) BETWEEN 5 AND 2000),
 idempotency_key text NOT NULL UNIQUE,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE trend_topic_sources (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 topic_id uuid NOT NULL REFERENCES trend_topics(id),
 research_source_id uuid NOT NULL REFERENCES research_sources(id),
 link_reason text NOT NULL CHECK(length(trim(link_reason)) BETWEEN 5 AND 1000),
 linked_by text NOT NULL CHECK(length(trim(linked_by)) BETWEEN 2 AND 120),
 idempotency_key text NOT NULL UNIQUE,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(topic_id,research_source_id)
);
CREATE TABLE trend_source_independence_reviews (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 topic_source_id uuid NOT NULL REFERENCES trend_topic_sources(id),
 decision text NOT NULL CHECK(decision IN ('independent','same_underlying_source','uncertain')),
 reviewer text NOT NULL CHECK(length(trim(reviewer)) BETWEEN 2 AND 120),
 reason text NOT NULL CHECK(length(trim(reason)) BETWEEN 5 AND 2000),
 comparison_group text,
 idempotency_key text NOT NULL UNIQUE,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE trend_research_packages (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 topic_id uuid NOT NULL REFERENCES trend_topics(id),
 package_version integer NOT NULL CHECK(package_version > 0),
 status text NOT NULL CHECK(status IN ('insufficient_evidence','evidence_ready_for_human_review')),
 payload jsonb NOT NULL,
 payload_sha256 text NOT NULL CHECK(payload_sha256 ~ '^[a-f0-9]{64}$'),
 source_ids uuid[] NOT NULL DEFAULT '{}',
 fact_ids uuid[] NOT NULL DEFAULT '{}',
 verified_fact_count integer NOT NULL DEFAULT 0 CHECK(verified_fact_count >= 0),
 independent_source_count integer NOT NULL DEFAULT 0 CHECK(independent_source_count >= 0),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(topic_id,payload_sha256),
 UNIQUE(topic_id,package_version)
);

CREATE FUNCTION deny_trend_research_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'trend_research_records_are_append_only'; END $$;
CREATE TRIGGER trend_topics_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON trend_topics
 FOR EACH STATEMENT EXECUTE FUNCTION deny_trend_research_mutation();
CREATE TRIGGER trend_membership_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON trend_topic_memberships
 FOR EACH STATEMENT EXECUTE FUNCTION deny_trend_research_mutation();
CREATE TRIGGER trend_grouping_proposal_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON trend_grouping_proposals
 FOR EACH STATEMENT EXECUTE FUNCTION deny_trend_research_mutation();
CREATE TRIGGER trend_scoring_config_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON trend_scoring_configs
 FOR EACH STATEMENT EXECUTE FUNCTION deny_trend_research_mutation();
CREATE TRIGGER trend_assessment_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON trend_topic_assessments
 FOR EACH STATEMENT EXECUTE FUNCTION deny_trend_research_mutation();
CREATE TRIGGER trend_editorial_decision_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON trend_topic_editorial_decisions
 FOR EACH STATEMENT EXECUTE FUNCTION deny_trend_research_mutation();
CREATE TRIGGER trend_topic_source_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON trend_topic_sources
 FOR EACH STATEMENT EXECUTE FUNCTION deny_trend_research_mutation();
CREATE TRIGGER trend_independence_review_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON trend_source_independence_reviews
 FOR EACH STATEMENT EXECUTE FUNCTION deny_trend_research_mutation();
CREATE TRIGGER trend_package_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON trend_research_packages
 FOR EACH STATEMENT EXECUTE FUNCTION deny_trend_research_mutation();
GRANT SELECT,INSERT ON trend_topics,trend_topic_memberships,trend_grouping_proposals,
 trend_scoring_configs,trend_topic_assessments,trend_topic_editorial_decisions,
 trend_topic_sources,trend_source_independence_reviews,trend_research_packages TO woori_app;
INSERT INTO schema_migrations(version) VALUES(37);
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.trend_research_packages.migrated','{"version":37,"auto_selection":false,"human_review_required":true}');
