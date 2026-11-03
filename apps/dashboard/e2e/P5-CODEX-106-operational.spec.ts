import { expect, test } from "playwright/test";

test.skip(process.env.WOORI_OPERATIONAL_VERIFY !== "1", "Read-only operational check only");

test("P106 live settings and Worker revisions", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem("woori-theme", "dark"));
  await page.route("**/api/**", route => route.request().method() === "GET" ? route.continue() : route.abort("blockedbyclient"));
  await page.goto("/operations/automation");
  const expected: [string, string][] = [
    ["Google Trends 수집", "true"],
    ["Codex 자동 원고 작성", "true"],
    ["Blogger 자동 발행", "true"],
    ["Google Trends 원고 자동 발행", "true"],
    ["일일 예약 원고 자동 발행", "true"],
    ["Blogger 수동 발행", "true"],
    ["Blogger 긴급 정지", "false"],
  ];
  await expect(page.getByRole("switch")).toHaveCount(expected.length);
  for (const [name, value] of expected) {
    await expect(page.getByRole("switch", { name, exact: true })).toHaveAttribute("aria-checked", value);
  }
  const response = await page.evaluate(async () => {
    const result = await fetch("/api/automation-controls", { cache: "no-store" });
    return { status: result.status, data: await result.json() };
  });
  expect(response.status).toBe(200);
  const snapshot = response.data;
  expect(snapshot.settings).toMatchObject({
    auto_mode: "publish", emergency_stop: false, blogger_api_restricted: false,
    auto_publishing_enabled: true, trends_auto_publishing_enabled: false,
    scheduled_auto_publishing_enabled: true,
  });
  expect(snapshot.settings.auto_blog_ids).toHaveLength(4);
  for (const service of ["research_worker", "publication_worker"]) {
    expect(snapshot.workers.find((worker: { service_name: string }) => worker.service_name === service)).toMatchObject({
      applied_revision: snapshot.settings.revision, policy_applied: true, engine_version: "automation-controls/3",
    });
  }
  await expect(page.getByText("저장된 방식: LIVE", { exact: false })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({ path: `../../docs/development/assets/P5-CODEX-106-live-${info.project.name}.png`, fullPage: true });
});
