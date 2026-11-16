import { test, expect } from "playwright/test";

test.skip(process.env.WOORI_OPERATIONAL_VERIFY !== "1", "Explicit read-only operational verification required");

test("P104 persisted origin switches and applied publishing engine", async ({ page }, info) => {
  test.setTimeout(60000);
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem("woori-theme", "dark"));
  await page.route("**/api/**", route => route.request().method() === "GET" ? route.continue() : route.abort("blockedbyclient"));
  await page.goto("/operations/automation");
  const expected: [string, string][] = [["Google Trends 수집", "true"], ["Codex 자동 원고 작성", "true"], ["Blogger 자동 발행", "true"], ["Google Trends 원고 자동 발행", "true"], ["일일 예약 원고 자동 발행", "true"], ["자동 발행 운영 허용", "false"], ["Blogger 수동 발행", "true"], ["Blogger 긴급 정지", "false"]];
  await expect(page.getByRole("switch")).toHaveCount(8);
  for (const [name, value] of expected) await expect(page.getByRole("switch", { name, exact: true })).toHaveAttribute("aria-checked", value);
  await expect(page.getByText("Worker 적용 확인", { exact: false }).filter({ hasText: "PID" })).toHaveCount(2, { timeout: 45000 });
  await expect(page.getByText("실제 쓰기 가능 여부: 미검증", { exact: true })).toBeVisible();
  const response = await page.evaluate(async () => {
    const result = await fetch("/api/automation-controls", { cache: "no-store" });
    return { status: result.status, data: await result.json() };
  });
  expect(response.status).toBe(200);
  const data = response.data;
  expect(data.api_engine_version).toBe("automation-controls/3");
  expect(data.workers.find((w: { service_name: string }) => w.service_name === "publication_worker")).toMatchObject({ engine_version: "automation-controls/3", policy_applied: true });
  expect(data.eligible_jobs).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({ path: `../../docs/development/assets/P5-CODEX-104-live-${info.project.name}.png`, fullPage: true });
});
