import { expect, test } from "playwright/test";

test("publication list shows Google Trends volume in its own column", async ({ page }) => {
  await page.route("**/api/publications?*", async (route) => {
    if (new URL(route.request().url()).searchParams.get("view") !== "review") {
      await route.continue();
      return;
    }
    await route.fulfill({
      json: {
        candidates: [],
        items: [{
          id: "fixture-version",
          content_version_id: "fixture-version",
          group_id: "fixture-group",
          title: "Fixture article title",
          language_code: "en",
          blog_id: "fixture-blog",
          blog_name: "Trend Journal EN",
          url: "https://example.invalid",
          topic: "Fixture research topic",
          status: "review_needed",
          origin_kind: "google_trends",
          trends_search_query: "fixture trend query",
          trends_search_country: "US",
          trends_search_volume_raw: "10K+",
          trends_search_volume_kind: "bucket_lower_bound",
        }],
        view: "review",
        summary: { queue: 0, review: 1, published: 0, held: 0, auto_failure: 0, discarded: 0 },
        total_count: 1,
        page: 1,
        page_size: 25,
        page_count: 1,
        jobs: [],
        worker: null,
        queued_mock_jobs: 0,
        real_writes_enabled: false,
        publish_ready_enabled: false,
        adapter_available: "fixture",
        mode_policy: {
          migration_required: false,
          default_mode: "manual",
          settings: [{ scope_type: "global", scope_key: "", configured_mode: "manual", daily_auto_limit: 100, minimum_interval_minutes: 15 }],
          languages: [{ code: "en", display_name: "English", active: true }],
          blogs: [{ id: "fixture-blog", language_code: "en", url: "https://example.invalid", display_name: "Trend Journal EN", active: true }],
          emergency_stopped: false,
          operations_auto_approved: false,
          live_auto_enabled: false,
          real_writes_enabled: false,
          scheduled_auto_policy: { enabled: false, policy_history: [], trends_lane_affected: false },
        },
        auto_candidate_count: 0,
        auto_runtime_status: "disabled",
        operational_limits: {
          timezone: "Asia/Seoul",
          global_daily: 100,
          language_daily: {},
          language_hourly: {},
          english_daily_policy: "remaining_global_capacity",
          global_publish_min_interval_minutes: 15,
        },
      },
    });
  });

  await page.goto("/publishing?view=discarded");
  await page.getByRole("tab", { name: /검토 필요/ }).click();

  const table = page.locator(".publication-section .publication-table-scroll").last();
  const volumeHeader = table.getByRole("columnheader", { name: "Google Trends 검색량" });
  if (await volumeHeader.isVisible()) await expect(volumeHeader).toBeVisible();

  const volumeCell = table.locator(".publication-trends-volume:has(strong)").first();
  const row = volumeCell.locator("xpath=ancestor::tr");
  await expect(volumeCell).toBeVisible();
  await expect(volumeCell.locator("strong")).toContainText(/\d/);
  await expect(volumeCell.locator("small")).toContainText("정확한 검색 횟수 아님");
  await expect(volumeCell.locator("strong")).toHaveText("10K+");
  await expect(row.locator("td").nth(1)).toContainText("fixture trend query");
  if (!(await volumeHeader.isVisible())) {
    await expect(volumeCell).toHaveAttribute("data-label", "Google Trends 검색량");
  }

  const volume = (await volumeCell.locator("strong").innerText()).trim();
  await expect(row.locator("td").nth(1)).not.toContainText(volume);
});
