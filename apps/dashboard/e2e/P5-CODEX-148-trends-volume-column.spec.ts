import { expect, test } from "playwright/test";

test("publication list shows Google Trends volume in its own column", async ({ page }) => {
  await page.route("**/api/publications?*", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("view") !== "review") {
      await route.continue();
      return;
    }

    const response = await route.fetch();
    const data = await response.json();
    data.view = "review";
    data.total_count = 1;
    data.page_count = 1;
    data.summary.review = 1;
    data.items = [{
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
    }];
    await route.fulfill({ response, json: data });
  });

  await page.goto("/publishing?view=discarded");
  await page.getByRole("tab", { name: /검토 필요/ }).click();

  const table = page.locator(".publication-section .publication-table-scroll").last();
  await expect(table.getByRole("columnheader", { name: "Google Trends 검색량" })).toBeVisible();
  const row = table.locator("tbody tr").first();
  await expect(row.locator(".publication-trends-volume strong")).toHaveText("10K+");
  await expect(row.locator(".publication-trends-volume")).toHaveAttribute(
    "data-label",
    "Google Trends 검색량",
  );
  const titleCell = row.locator("td").nth(1);
  await expect(titleCell).toContainText("fixture trend query");
  await expect(titleCell).not.toContainText("10K+");
});
