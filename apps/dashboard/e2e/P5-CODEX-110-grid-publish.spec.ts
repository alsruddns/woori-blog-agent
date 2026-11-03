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
