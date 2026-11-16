-- Human review resolves event identity proposals without rewriting observations or topic history.
CREATE TABLE trend_grouping_reviews (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 proposal_id uuid NOT NULL REFERENCES trend_grouping_proposals(id),
 decision text NOT NULL CHECK(decision IN ('same_event','different_event','insufficient_information')),
 event_group_id uuid,
 reviewer text NOT NULL CHECK(length(trim(reviewer)) BETWEEN 2 AND 120),
 rationale text NOT NULL CHECK(length(trim(rationale)) BETWEEN 5 AND 2000),
 idempotency_key text NOT NULL UNIQUE,
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK((decision='same_event' AND event_group_id IS NOT NULL) OR
       (decision<>'same_event' AND event_group_id IS NULL))
);
CREATE TRIGGER trend_group_review_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON trend_grouping_reviews
 FOR EACH STATEMENT EXECUTE FUNCTION deny_trend_research_mutation();
GRANT SELECT,INSERT ON trend_grouping_reviews TO woori_app;
INSERT INTO schema_migrations(version) VALUES(39);
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.trend_grouping_reviews.migrated','{"version":39,"decision_model":"append_only_human_review"}');
