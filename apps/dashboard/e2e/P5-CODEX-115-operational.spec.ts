import { expect, test } from "playwright/test";
import path from "node:path";

test.skip(process.env.WOORI_OPERATIONAL_VERIFY !== "1", "Read-only operational UI verification only");

test("pre-job failure history is legible and read-only", async ({ page }, info) => {
  const pageErrors: string[] = [];
  const writeRequests: string[] = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  await page.route("**/api/**", route => {
    if (route.request().method() !== "GET") {
      writeRequests.push(`${route.request().method()} ${route.request().url()}`);
      return route.abort("blockedbyclient");
    }
    return route.continue();
  });
  await page.addInitScript(() => localStorage.setItem("woori-theme", "dark"));
  await page.goto("/publishing");
  await page.getByRole("tab").nth(1).click();
  const monitor = page.locator(".publication-worker-monitor");
  await expect(monitor).toBeVisible();
  await monitor.locator("select").selectOption("archived_failure");
  await expect(monitor.getByRole("table")).toBeVisible();
  await expect(monitor).toContainText("96");
  await expect(monitor.locator("tbody tr")).toHaveCount(25);
  expect(new URL(page.url()).searchParams.get("section")).toBe("jobs");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(writeRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
  await page.screenshot({ path: path.resolve(`../../.runtime/P115-${info.project.name}.png`), fullPage: true });
});
