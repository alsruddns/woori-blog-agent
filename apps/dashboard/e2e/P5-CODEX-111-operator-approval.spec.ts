import { expect, test } from "playwright/test";

test("operator approval is separately confirmed, audited and remains blocked by independent policies", async ({ page }) => {
  const state: Record<string, unknown> = {
    revision: 16,
    updated_at: "2026-11-03T01:00:00Z",
    trends_collection_enabled: true,
    auto_manuscript_enabled: true,
    auto_publishing_enabled: true,
    trends_auto_publishing_enabled: true,
    scheduled_auto_publishing_enabled: true,
    automatic_publication_operator_approved: false,
    automatic_publication_approval_actor: null,
    automatic_publication_approval_reason: null,
    automatic_publication_approval_changed_at: null,
    manual_publishing_enabled: true,
    emergency_stop: false,
    blogger_api_restricted: false,
    configured_mode: "manual",
    operations_auto_approved: false,
    blogger_write_mode: "manual_only",
    interval_minutes: 30,
    global_publish_min_interval_minutes: 15,
    global_daily_live_publish_limit: 100,
    auto_mode: "publish",
    auto_blog_ids: ["aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"],
    google_account_report: "unverified",
    read_check_result: {},
  };
  const writes: Record<string, unknown>[] = [];
  const workers = ["research_worker", "publication_worker"].map((service_name, index) => ({
    service_name,
    process_id: 800 + index,
    policy_applied: true,
    applied_revision: state.revision,
    engine_version: "automation-controls/3",
    policy_seen_at: "2026-11-03T01:00:00Z",
  }));
  await page.route("**/api/automation-controls**", async route => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      writes.push(body);
      if (body.expected_revision !== state.revision) return route.fulfill({ status: 409, json: { detail: "revision_conflict" } });
      Object.assign(state, Object.fromEntries(Object.entries(body).filter(([key]) => key in state)));
      state.revision = Number(state.revision) + 1;
      workers.forEach(worker => { worker.applied_revision = Number(state.revision); });
      return route.fulfill({ json: { saved: true, revision: state.revision, application: "pending_worker_ack" } });
    }
    const approved = state.automatic_publication_operator_approved === true;
    return route.fulfill({ json: {
      settings: state,
      automatic_publication_approval: {
        approved,
        effective: false,
        worker_applied: true,
        blockers: ["legacy_publication_operations_approval_unavailable", "blogger_write_mode_not_public_write_approved"],
        pending_auto_jobs: 3,
        legacy_operations_auto_approved: false,
        configured_mode: "manual",
        blogger_write_mode: "manual_only",
        external_cost_policy_approved: false,
        external_public_write_approved: false,
        scope: {},
        actor: state.automatic_publication_approval_actor,
        reason: state.automatic_publication_approval_reason,
        changed_at: state.automatic_publication_approval_changed_at,
      },
      effective: {
        trends_collection_enabled: "정상", auto_manuscript_enabled: "정상", auto_publishing_enabled: "정상",
        manual_publishing_enabled: "정상", trends_auto_publishing_enabled: "정상",
        scheduled_auto_publishing_enabled: "정상",
        automatic_publication_operator_approved: approved
          ? "운영 승인 ON — 다른 정책 조건으로 발행 차단"
          : "자동 발행 운영 승인 OFF — 자동 발행 중지",
      },
      workers,
      history: [],
      blogs: [{ id: "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa", display_name: "Trend Journal EN", language_code: "en" }],
      recent: { region_count: 11, last_collection: null, last_import: null, last_authoring: null, authoring_queued: 0, authoring_running: 0 },
      eligible_jobs: 0,
      last_publication: null,
    } });
  });

  const unexpectedWrites: string[] = [];
  page.on("request", request => {
    if (/\/api\/blogger(?:\/|$)/.test(request.url()) && !request.url().includes("oauth")) unexpectedWrites.push(request.method());
  });
  await page.goto("/operations/automation");
  const toggle = page.getByRole("switch", { name: "자동 발행 운영 허용" });
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(page.getByText("자동 발행 운영 승인 OFF — 자동 발행 중지")).toBeVisible();
  await page.getByLabel("변경 사유", { exact: true }).fill("승인 UI 격리 테스트용 변경 사유");

  await toggle.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("전체 자동 발행: ON");
  await expect(dialog).toContainText("Trends 자동 발행: ON");
  await expect(dialog).toContainText("예약 자동 발행: ON");
  await expect(dialog).toContainText("글로벌 최소 간격: 15분");
  await expect(dialog).toContainText("일일 LIVE 상한: 100건");
  await expect(dialog).toContainText("기존 자동 대기 Job: 3건");
  await expect(dialog).toContainText("Blogger 외부 쓰기 권한");
  await expect(dialog.getByRole("button", { name: "확인 후 적용" })).toBeDisabled();
  await dialog.getByRole("checkbox", { name: "표시된 운영 승인 범위와 기존 Job 보호 정책을 확인했습니다." }).check();
  await dialog.getByRole("button", { name: "확인 후 적용" }).click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await expect(page.getByText("운영 승인 ON — 다른 정책 조건으로 발행 차단")).toBeVisible();
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({
    automatic_publication_operator_approved: true,
    confirm_operator_auto_approval: true,
    expected_revision: 16,
    actor: "관리자",
    reason: "승인 UI 격리 테스트용 변경 사유",
  });

  await toggle.click();
  await dialog.getByRole("checkbox", { name: "표시된 운영 승인 범위와 기존 Job 보호 정책을 확인했습니다." }).check();
  await dialog.getByRole("button", { name: "확인 후 적용" }).click();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  expect(writes).toHaveLength(2);
  expect(writes[1]).toMatchObject({ automatic_publication_operator_approved: false, expected_revision: 17 });
  expect(unexpectedWrites).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
