import { expect, test } from "playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

const screenshots = path.resolve(__dirname, "../../../docs/development/assets");

test("operations home reports observed automation status without promising live publishing", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", message => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.goto("/");
  await expect(page.locator("main.ops-home")).toBeVisible();
  await expect(page.locator(".ops-stat-grid .ops-stat-card")).toHaveCount(4);
  await expect(page.locator(".ops-schedule-card")).toHaveCount(4);
  await expect(page.locator('a[href="/operations/research#automation"]')).toHaveCount(2);
  expect(await page.locator(".ops-status-blocked").count()).toBeGreaterThan(0);
  expect(await page.locator(".ops-status-neutral").count()).toBeGreaterThan(0);

  for (const width of [320, 390, 768, 1280, 1920]) {
    await page.setViewportSize({ width, height: width < 500 ? 844 : 1000 });
    await expect(page.locator("main.ops-home")).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      `operations home overflows at ${width}px`,
    ).toBe(true);
    if (width === 390 || width === 1280) {
      mkdirSync(screenshots, { recursive: true });
      await page.screenshot({ path: path.join(screenshots, `P5-CODEX-014-home-${width}.png`), fullPage: true });
    }
  }
  expect(consoleErrors).toEqual([]);
});
