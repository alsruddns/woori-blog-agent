import { expect, test } from "playwright/test";

test("grid manual publish opens an exact-version queue confirmation without opening the detail sheet", async ({ page }) => {
  const version = "11111111-1111-4111-8111-111111111111";
  const blog = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa";
  let submitted: Record<string, unknown> | null = null;
  const requests: Array<{url:string;method:string;status?:number}> = [];
  page.on("request",request=>{
    if(request.url().includes("content-imports/22222222-2222-4222-8222-222222222222")||request.url().includes("manual-live-requests"))
      requests.push({url:new URL(request.url()).pathname,method:request.method()});
  });
  page.on("response",response=>{
    const entry=[...requests].reverse().find(request=>request.url===new URL(response.url()).pathname&&request.status===undefined);
    if(entry)entry.status=response.status();
  });
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
  expect(requests).toEqual([
    {url:"/api/research/content-imports/22222222-2222-4222-8222-222222222222",method:"GET",status:200},
    {url:"/api/publications/manual-live-requests",method:"POST",status:201},
  ]);
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

test("manual preflight errors remain visible and held manuscripts cannot create a Job", async ({ page }) => {
  const version = "77777777-7777-4777-8777-777777777777";
  const blog = "cccccccc-cccc-4ccc-accc-cccccccccccc";
  let manualPosts = 0;
  await page.route("**/api/publications?*", route => route.fulfill({ json: {
    view: "auto_failure", items: [{ id: "failure-row", content_version_id: version,
      import_id: "88888888-8888-4888-8888-888888888888", title: "Unreviewed manuscript", language_code: "ja",
      blog_id: blog, blog_name: "Trend Journal JA", url: "https://example.blogspot.com", status: "auto_publication_failed",
      failure_stage: "eligibility", failure_reason_code: "global_publication_mode_mismatch", manual_publication_available: true }],
    candidates: [], jobs: [], page: 1, page_count: 1, total_count: 1, summary: {}, mode_policy: {
      migration_required: false, default_mode: "manual", settings: [], languages: [{ code: "ja", display_name: "日本語", active: true }],
      blogs: [{ id: blog, language_code: "ja", url: "https://example.blogspot.com", display_name: "Trend Journal JA", active: true }],
      emergency_stopped: false, operations_auto_approved: false, live_auto_enabled: false, real_writes_enabled: false,
    }, worker: null, queued_mock_jobs: 0, real_writes_enabled: false, publish_ready_enabled: false,
    adapter_available: "mock", auto_candidate_count: 0, auto_runtime_status: "idle",
  } }));
  await page.route("**/api/research/content-imports/88888888-8888-4888-8888-888888888888", route => route.fulfill({ status: 200, json: {
    publication: { targets: [{ id: blog, manual_publication: {
      eligible: false, request_available: true, content_version_id: version, title: "Unreviewed manuscript",
      body: "Claims awaiting source review.", blockers: ["evidence_fact_verification_missing", "human_review_pending", "publish_ready_disabled"],
      seo: { search_description_stored: true, blogger_api_supported: false, manual_entry_required: true,
        html_meta_description_verified: false, robots_indexing_status: "unverified", canonical_status: "unverified" },
    } }] },
  } }));
  await page.route("**/api/publications/manual-live-requests", async route => {
    manualPosts += 1;
    await route.fulfill({ status: 201, json: { id: "99999999-9999-4999-8999-999999999999" } });
  });
  await page.goto("/publishing?view=auto_failure");
  await page.getByRole("tab", { name: "자동발행실패" }).click();
  await page.getByRole("button", { name: "수동 발행" }).click();
  const dialog = page.getByRole("dialog", { name: "수동 발행 큐 등록 확인" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("주장과 연결된 검증 근거가 부족합니다.");
  await expect(dialog).toContainText("사람의 편집 검토가 완료되지 않았습니다.");
  await expect(dialog).toContainText("공개 발행 적격 상태가 아닙니다.");
  await expect(dialog).toContainText("API 미지원");
  await expect(dialog.getByRole("button", { name: "발행 큐 등록" })).toBeDisabled();
  expect(manualPosts).toBe(0);
});

test("manual preflight HTTP errors are shown inside the open confirmation dialog", async ({ page }) => {
  const blog = "dddddddd-dddd-4ddd-addd-dddddddddddd";
  await page.route("**/api/publications?*", route => route.fulfill({ json: {
    view: "review", items: [{ id: "review-error", content_version_id: "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa",
      import_id: "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb", title: "Preflight unavailable", language_code: "en",
      blog_id: blog, url: "https://example.blogspot.com", status: "review_needed" }], candidates: [], jobs: [], page: 1,
    page_count: 1, total_count: 1, summary: {}, mode_policy: { migration_required: false, default_mode: "manual",
      settings: [], languages: [], blogs: [], emergency_stopped: false, operations_auto_approved: false,
      live_auto_enabled: false, real_writes_enabled: false }, worker: null, queued_mock_jobs: 0,
    real_writes_enabled: false, publish_ready_enabled: false, adapter_available: "mock", auto_candidate_count: 0,
    auto_runtime_status: "idle",
  } }));
  await page.route("**/api/research/content-imports/bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb", route => route.fulfill({
    status: 503, json: { detail: "최신 발행 검사 서비스를 사용할 수 없습니다.", code: "publication_check_unavailable" },
  }));
  await page.goto("/publishing?view=review");
  await page.getByRole("tab", { name: "검토 필요" }).click();
  await page.getByRole("button", { name: "수동 발행" }).click();
  const dialog = page.getByRole("dialog", { name: "수동 발행 큐 등록 확인" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("최신 발행 검사 서비스를 사용할 수 없습니다.");
  await expect(dialog.getByRole("button", { name: "발행 큐 등록" })).toBeDisabled();
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
