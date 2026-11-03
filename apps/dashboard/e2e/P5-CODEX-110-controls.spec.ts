import { expect, test } from "playwright/test";

test("automation reason defaults and global interval use the same audited confirmation flow", async ({ page }) => {
  const settings = {
    revision: 1, updated_at: "2026-11-03T00:00:00Z",
    trends_collection_enabled: true, auto_manuscript_enabled: true, auto_publishing_enabled: false,
    trends_auto_publishing_enabled: false, scheduled_auto_publishing_enabled: false,
    manual_publishing_enabled: true, emergency_stop: false, blogger_api_restricted: false,
    interval_minutes: 30, global_publish_min_interval_minutes: 15, global_daily_live_publish_limit: 100, auto_mode: "draft", auto_blog_ids: [],
    google_account_report: "unverified", read_check_result: {},
  };
  const writes: Record<string, unknown>[] = [];
  await page.route("**/api/automation-controls**", async route => {
    const request = route.request();
    if (request.method() === "PUT") {
      const body = request.postDataJSON() as Record<string, unknown>;
      writes.push(body);
      if (body.expected_revision !== settings.revision) return route.fulfill({ status: 409, json: { detail: "revision_conflict" } });
      Object.assign(settings, Object.fromEntries(Object.entries(body).filter(([key]) => key in settings)));
      settings.revision++;
      return route.fulfill({ json: { saved: true, revision: settings.revision, application: "pending_worker_ack" } });
    }
    return route.fulfill({ json: {
      settings,
      effective: Object.fromEntries(["trends_collection_enabled","auto_manuscript_enabled","auto_publishing_enabled","manual_publishing_enabled","trends_auto_publishing_enabled","scheduled_auto_publishing_enabled"].map(key => [key,"정상"])),
      workers: ["research_worker","publication_worker"].map((service_name,index) => ({ service_name, process_id: 500 + index, policy_applied: true, applied_revision: settings.revision, policy_seen_at: "2026-11-03T00:00:00Z" })),
      history: [], blogs: [], recent: { region_count: 11, last_collection: null, last_import: null, last_authoring: null, authoring_queued: 0, authoring_running: 0 },
      eligible_jobs: 0, last_publication: null,
    } });
  });

  await page.goto("/operations/automation");
  const reason = page.locator("input[placeholder='운영 목적을 10자 이상 입력']");
  await expect(reason).toHaveValue("운영 목적을 위해 설정을 변경함");
  await page.getByRole("switch", { name: "일일 예약 원고 자동 발행" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator("input[data-testid='automation-reason']")).toHaveValue("운영 목적을 위해 설정을 변경함");
  await dialog.getByRole("checkbox", { name: "대상과 적용 범위를 확인했습니다." }).check();
  await dialog.getByRole("button", { name: "확인 후 적용" }).click();
  expect(writes.at(-1)).toMatchObject({ scheduled_auto_publishing_enabled: true, reason: "운영 목적을 위해 설정을 변경함" });

  await page.locator("input[data-testid='global-interval']").fill("60");
  await page.getByRole("button", { name: "발행 간격 변경" }).click();
  await expect(dialog.locator("input[data-testid='automation-reason']")).toHaveValue("운영 목적을 위해 설정을 변경함");
  await dialog.getByRole("checkbox", { name: "대상과 적용 범위를 확인했습니다." }).check();
  await dialog.getByRole("button", { name: "확인 후 적용" }).click();
  expect(writes.at(-1)).toMatchObject({ global_publish_min_interval_minutes: 60, reason: "운영 목적을 위해 설정을 변경함" });
  await expect(page.locator("input[data-testid='global-interval']")).toHaveValue("60");

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
