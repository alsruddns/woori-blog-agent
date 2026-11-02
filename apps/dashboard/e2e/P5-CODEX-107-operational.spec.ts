import { expect, test } from "playwright/test";

test.skip(process.env.WOORI_OPERATIONAL_VERIFY !== "1", "Read-only operational UI check");

test("P107 publication tabs, provenance, archive, and confirmation", async ({ page }, info) => {
  const errors: string[] = [];
  const jobs: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.url().includes("/api/publications/worker-jobs")) jobs.push(request.url()); });
  await page.addInitScript(() => localStorage.setItem("woori-theme", "dark"));
  await page.route("**/api/**", route => route.request().method() === "GET" ? route.continue() : route.abort("blockedbyclient"));
  await page.goto("/publishing");
  await expect(page.getByRole("tab", { name: "발행 관리", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", { name: "Job 관리", exact: true })).toHaveAttribute("aria-selected", "false");
  expect(jobs).toHaveLength(0);
  await expect(page.getByLabel("생성 출처")).toBeVisible();
  await expect(page.locator(".publication-origin").first()).toBeVisible();
  await page.getByLabel("생성 출처").selectOption("scheduled");
  await expect(page.locator(".publication-origin").first()).toContainText("Codex 예약");
  await page.locator(".publication-section .publication-row-actions button").first().click();
  await expect(page.getByRole("dialog", { name: "원고 폐기 확인" })).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "취소" }).click();
  await page.getByRole("tab", { name: "폐기 보관함" }).click();
  await expect(page.locator(".publication-section")).toContainText("폐기 보관함");
  await page.getByRole("tab", { name: "Job 관리", exact: true }).click();
  await expect(page.getByRole("tab", { name: "Job 관리", exact: true })).toHaveAttribute("aria-selected", "true");
  expect(jobs.length).toBeGreaterThan(0);
  expect(new URL(page.url()).searchParams.get("section")).toBe("jobs");
  await page.reload();
  await expect(page.getByRole("tab", { name: "Job 관리", exact: true })).toHaveAttribute("aria-selected", "true");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({ path: `../../docs/development/assets/P5-CODEX-107-${info.project.name}.png`, fullPage: true });
});
