-- P5-CODEX-111: explicit operator approval is separate from Blogger write authority.
-- A new installation and every existing installation start fail-closed.
ALTER TABLE automation_controls
  ADD COLUMN automatic_publication_operator_approved boolean NOT NULL DEFAULT false,
  ADD COLUMN automatic_publication_approval_actor text,
  ADD COLUMN automatic_publication_approval_reason text,
  ADD COLUMN automatic_publication_approval_changed_at timestamptz,
  ADD COLUMN automatic_publication_approval_scope jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD CONSTRAINT automation_controls_operator_approval_metadata_check CHECK (
    NOT automatic_publication_operator_approved OR (
      automatic_publication_approval_actor IS NOT NULL
      AND length(btrim(automatic_publication_approval_actor)) >= 2
      AND automatic_publication_approval_reason IS NOT NULL
      AND length(btrim(automatic_publication_approval_reason)) >= 10
      AND automatic_publication_approval_changed_at IS NOT NULL
    )
  );

INSERT INTO audit_events(event_type,payload)
VALUES ('schema.p5_codex_111_operator_approval.migrated',
  '{"version":83,"automatic_publication_operator_approved":false,"legacy_operations_auto_approved_unchanged":true,"external_write_policy_unchanged":true}');
INSERT INTO schema_migrations(version) VALUES(83);
