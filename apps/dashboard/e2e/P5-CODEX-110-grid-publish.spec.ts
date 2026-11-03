import { expect, test } from "playwright/test";

test("grid manual publish opens an exact-version queue confirmation without opening the detail sheet", async ({ page }) => {
  const version = "11111111-1111-4111-8111-111111111111";
  const blog = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa";
  let submitted: Record<string, unknown> | null = null;
  await page.route("**/api/publications?*", route => route.fulfill({ json: {
    view: "queue", items: [{ id: "row-1", content_version_id: version, import_id: "22222222-2222-4222-8222-222222222222",
      title: "Grid manuscript", language_code: "en", blog_id: blog, blog_name: "Trend Journal EN", url: "https://example.blogspot.com",
      status: "queueable", manual_publication_available: true, origin_kind: "scheduled", created_at: "2026-11-03T00:00:00Z" }],
    candidates: [], jobs: [], page: 1, page_count: 1, total_count: 1, summary: {}, mode_policy: {
      migration_required: false, default_mode: "manual", settings: [], languages: [{ code: "en", display_name: "English", active: true }],
      blogs: [{ id: blog, language_code: "en", url: "https://example.blogspot.com", display_name: "Trend Journal EN", active: true }],
      emergency_stopped: false, operations_auto_approved: false, live_auto_enabled: false, real_writes_enabled: false,
    }, worker: null, queued_mock_jobs: 0, real_writes_enabled: false, publish_ready_enabled: false, adapter_available: "mock",
    auto_candidate_count: 0, auto_runtime_status: "idle",
  } }));
  await page.route("**/api/research/content-imports/22222222-2222-4222-8222-222222222222", route => route.fulfill({ json: {
    publication: { targets: [{ id: blog, manual_publication: { eligible: true, blockers: [], title: "Grid manuscript",
      body: "Reviewed body for this exact version.", content_version_id: version,
      title_sha256: "a".repeat(64), body_sha256: "b".repeat(64), html_sha256: "c".repeat(64) } }] },
  } }));
  await page.route("**/api/publications/manual-live-requests", async route => {
    submitted = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({ status: 201, json: { id: "33333333-3333-4333-8333-333333333333", duplicate: false, public_write_performed: false } });
  });

  await page.goto("/publishing");
  await page.getByRole("tab", { name: "발행 대기" }).click();
  await expect(page.getByRole("button", { name: "수동 발행" })).toBeVisible();
  await page.getByRole("button", { name: "수동 발행" }).click();
  const dialog = page.getByRole("dialog", { name: "수동 발행 큐 등록 확인" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(version);
  await expect(dialog).toContainText("LIVE 공개 (기본)");
  await expect(page.locator(".embedded-import-detail")).not.toContainText("Grid manuscript");
  const checks = dialog.locator("input[type=checkbox]");
  await checks.nth(0).check();
  await checks.nth(1).check();
  await checks.nth(2).check();
  await checks.nth(3).check();
  await dialog.getByRole("button", { name: "발행 큐 등록" }).click();
  await expect(page.getByRole("status").filter({ hasText: "발행 큐에 등록했습니다." })).toBeVisible();
  expect(submitted).toMatchObject({ content_version_id: version, blog_id: blog, publication_mode: "publish", reviewed_exact_content: true });
});

test("review-needed row can request manual publication even when summary preflight says unavailable", async ({ page }) => {
  const version = "44444444-4444-4444-8444-444444444444";
  const blog = "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb";
  let writes = 0;
  await page.route("**/api/publications?*", route => route.fulfill({ json: {
    view: "review", items: [{ id: "review-row", content_version_id: version, import_id: "55555555-5555-4555-8555-555555555555",
      title: "Review manuscript", language_code: "de", blog_id: blog, blog_name: "Trend Journal DE", url: "https://trend-journal-de.blogspot.com",
      status: "review_needed", manual_publication_available: false, origin_kind: "scheduled" }],
    candidates: [], jobs: [], page: 1, page_count: 1, total_count: 1, summary: { review: 1 }, mode_policy: {
      migration_required: false, default_mode: "manual", settings: [], languages: [{ code: "de", display_name: "Deutsch", active: true }],
      blogs: [{ id: blog, language_code: "de", url: "https://trend-journal-de.blogspot.com", display_name: "Trend Journal DE", active: true }],
      emergency_stopped: false, operations_auto_approved: false, live_auto_enabled: false, real_writes_enabled: false,
    }, worker: null, queued_mock_jobs: 0, real_writes_enabled: false, publish_ready_enabled: false, adapter_available: "mock",
    auto_candidate_count: 0, auto_runtime_status: "idle",
  } }));
  await page.route("**/api/research/content-imports/55555555-5555-4555-8555-555555555555", route => route.fulfill({ json: {
    publication: { targets: [{ id: blog, manual_publication: { eligible: true, blockers: [], title: "Review manuscript",
      body: "Reviewed exact-version content.", content_version_id: version,
      title_sha256: "d".repeat(64), body_sha256: "e".repeat(64), html_sha256: "f".repeat(64) } }] },
  } }));
  await page.route("**/api/publications/manual-live-requests", async route => {
    writes += 1;
    await route.fulfill({ status: 201, json: { id: "66666666-6666-4666-8666-666666666666", duplicate: false, public_write_performed: false } });
  });
  await page.route("**/api/publications/worker-jobs?*", route => route.fulfill({ json: {
    items: [], counts: {}, page: 1, page_count: 1, total: 0, worker_state: "stopped", as_of: "2026-11-03T00:00:00Z",
  } }));

  await page.goto("/publishing?view=review");
  await page.getByRole("tab", { name: "검토 필요" }).click();
  const button = page.getByRole("button", { name: "수동 발행" });
  await expect(button).toBeVisible();
  await button.click();
  const dialog = page.getByRole("dialog", { name: "수동 발행 큐 등록 확인" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(version);
  await expect(dialog).toContainText("LIVE 공개 (기본)");
  await expect(page.locator(".embedded-import-detail")).not.toContainText("Review manuscript");
  await dialog.getByRole("button", { name: "취소" }).click();
  await expect(dialog).not.toBeVisible();
  expect(writes).toBe(0);
});

test("job monitor renders Korean count units instead of literal Unicode escapes", async ({ page }) => {
  await page.route("**/api/publications?*", route => route.fulfill({ json: {
    view: "review", items: [], candidates: [], jobs: [], page: 1, page_count: 1, total_count: 0, summary: {}, mode_policy: {
      migration_required: false, default_mode: "manual", settings: [], languages: [], blogs: [],
      emergency_stopped: false, operations_auto_approved: false, live_auto_enabled: false, real_writes_enabled: false,
    }, worker: null, queued_mock_jobs: 0, real_writes_enabled: false, publish_ready_enabled: false, adapter_available: "mock",
    auto_candidate_count: 0, auto_runtime_status: "idle",
  } }));
  await page.route("**/api/publications/worker-jobs?*", route => route.fulfill({ json: {
    period_label: "최근 작업", as_of: "2026-11-03T00:00:00Z", counts: { running: 0, queued: 1234 }, items: [],
    pre_job_failure_summary: { current_record_count: 1234, unique_import_count: 1, unique_manuscript_count: 1,
      unique_content_version_count: 1, repeated_failure_event_count: 1233, active_unarchived_count: 1234, archived_count: 0,
      root_cause_counts: {}, safety_classification_counts: {}, failure_reason_code_counts: {}, older_than_24h_count: 0, older_than_72h_count: 0 },
    worker_state: "stopped", worker: null, global_publish_min_interval_minutes: 15, last_job: null, page: 1, page_count: 1, total: 1234,
  } }));
  await page.goto("/publishing");
  await page.getByRole("tab", { name: "Job 관리" }).click();
  await expect(page.getByText("1,234건").first()).toBeVisible();
  await expect(page.getByText(/\\uac74|\\uBD84/)).toHaveCount(0);
});
