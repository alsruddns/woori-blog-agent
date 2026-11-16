-- Durable language-independent facts and append-only, explicitly approved terminology.
ALTER TABLE research_sources ADD COLUMN source_language text NOT NULL DEFAULT 'und';
ALTER TABLE glossary_entries ADD COLUMN source_language text NOT NULL DEFAULT 'und';
ALTER TABLE glossary_entries ADD COLUMN target_language text;
ALTER TABLE glossary_entries ADD COLUMN official_translation boolean NOT NULL DEFAULT false;
ALTER TABLE glossary_entries ADD COLUMN translation_source text;
ALTER TABLE glossary_entries ADD COLUMN approved boolean NOT NULL DEFAULT false;
UPDATE glossary_entries g SET target_language=p.language_code
 FROM language_profiles p WHERE p.id=g.profile_id AND g.target_language IS NULL;
ALTER TABLE glossary_entries ALTER COLUMN target_language SET NOT NULL;
ALTER TABLE glossary_entries ADD CONSTRAINT glossary_translation_proof
 CHECK(NOT approved OR (official_translation AND translation_source IS NOT NULL AND length(translation_source)>5));

CREATE TABLE glossary_entry_revisions (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 entry_id uuid NOT NULL REFERENCES glossary_entries(id), revision integer NOT NULL CHECK(revision>0),
 profile_id uuid NOT NULL REFERENCES language_profiles(id), source_term text NOT NULL,
 source_language text NOT NULL, target_language text NOT NULL, localized_term text NOT NULL,
 official_translation boolean NOT NULL, translation_source text, approved boolean NOT NULL,
 notes text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(entry_id,revision),
 CHECK(NOT approved OR (official_translation AND translation_source IS NOT NULL AND length(translation_source)>5))
);
CREATE FUNCTION append_glossary_revision() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE next_revision integer;
BEGIN
 SELECT coalesce(max(revision),0)+1 INTO next_revision FROM glossary_entry_revisions WHERE entry_id=NEW.id;
 INSERT INTO glossary_entry_revisions(entry_id,revision,profile_id,source_term,source_language,target_language,
   localized_term,official_translation,translation_source,approved,notes)
 VALUES(NEW.id,next_revision,NEW.profile_id,NEW.source_term,NEW.source_language,NEW.target_language,
   NEW.localized_term,NEW.official_translation,NEW.translation_source,NEW.approved,NEW.notes);
 RETURN NEW;
END; $$;
CREATE TRIGGER glossary_revision_append AFTER INSERT OR UPDATE ON glossary_entries
 FOR EACH ROW EXECUTE FUNCTION append_glossary_revision();
CREATE TRIGGER glossary_revision_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON glossary_entry_revisions
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();

CREATE TABLE evidence_facts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), fact_key text NOT NULL,
 source_id uuid NOT NULL REFERENCES research_sources(id), source_language text NOT NULL,
 source_excerpt text NOT NULL, entity_ids text[] NOT NULL DEFAULT '{}',
 numeric_values jsonb NOT NULL DEFAULT '[]', date_values jsonb NOT NULL DEFAULT '[]',
 citation_ids uuid[] NOT NULL, verification_status text NOT NULL CHECK(verification_status IN ('source_span_verified','needs_review','rejected')),
 extractor_version text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(source_id,fact_key,extractor_version), CHECK(cardinality(citation_ids)>0)
);
CREATE TRIGGER evidence_facts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON evidence_facts
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TABLE localization_evaluations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_id uuid NOT NULL REFERENCES research_sources(id),
 fact_id uuid NOT NULL REFERENCES evidence_facts(id), target_language text NOT NULL REFERENCES languages(code),
 output_snapshot jsonb NOT NULL, metrics jsonb NOT NULL, checks jsonb NOT NULL,
 machine_passed boolean NOT NULL, human_review_required boolean NOT NULL DEFAULT true,
 publish_ready boolean NOT NULL DEFAULT false CHECK(NOT publish_ready),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER localization_evaluations_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON localization_evaluations
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
GRANT SELECT,INSERT ON glossary_entry_revisions,evidence_facts,localization_evaluations TO woori_app;
GRANT USAGE,SELECT ON SEQUENCE glossary_entry_revisions_id_seq TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES('schema.evidence_localization.migrated','{"version":16}');
INSERT INTO schema_migrations(version) VALUES(16);
