"""Select a truthful import contract for a resolver-verified Desktop run."""

from __future__ import annotations

from typing import Any


def select_authoring_contract(invocation: dict[str, Any]) -> dict[str, str]:
    """Describe the envelope contract without treating it as execution proof.

    Callers must obtain ``invocation`` from the local resolver. Handoff still
    re-resolves the current Desktop turn before it accepts an envelope.
    """
    mode = invocation.get("execution_mode")
    trigger = invocation.get("trigger")
    automation_id = invocation.get("automation_id")
    session_id = invocation.get("session_id")
    if not all(isinstance(value, str) and value for value in (automation_id, session_id)):
        raise ValueError("automation_authoring_identity_incomplete")

    if mode == "scheduled" and trigger == "automation_cron_scheduled":
        required = ("occurrence_id", "scheduled_slot", "occurrence_id_source")
        if any(not isinstance(invocation.get(key), str) or not invocation[key] for key in required):
            raise ValueError("scheduled_authoring_identity_incomplete")
        return {
            "execution_origin": "scheduled",
            "envelope_schema": "woori-scheduled-content-import/1.0",
            "generation_method": "chatgpt_scheduled_export",
            "origin_field": "scheduled_origin",
            "run_id": invocation["occurrence_id"],
        }

    if mode == "manual" and trigger == "automation_cron_run_now":
        origin = invocation.get("manual_origin")
        run_id = invocation.get("manual_run_id")
        if (
            not isinstance(origin, dict)
            or not isinstance(run_id, str)
            or not run_id
            or origin.get("execution_mode") != "manual"
            or origin.get("automation_id") != automation_id
            or origin.get("session_id") != session_id
            or origin.get("manual_run_id") != run_id
            or origin.get("turn_trigger") != trigger
        ):
            raise ValueError("manual_authoring_identity_incomplete")
        return {
            "execution_origin": "automation_run_now",
            "envelope_schema": "woori-manual-automation-content-import/1.0",
            "generation_method": "manual_codex_import",
            "origin_field": "manual_origin",
            "run_id": run_id,
        }

    raise ValueError("automation_authoring_contract_not_available_for_invocation")
