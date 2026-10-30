import { expect, test } from "playwright/test";

test("Trends publication policies stay scoped to explicitly mapped blogs", async ({ page }) => {
  await page.goto("/sources");
  const heading = page.getByRole("heading", { name: "Google Trends 자동 발행 정책" });
  await expect(heading).toBeVisible();
  await expect(page.getByText("정책을 불러오는 중입니다.")).toHaveCount(0);
  await expect(page.getByText("Trend JA · ja", { exact: true })).toBeVisible();
  await expect(page.getByText("Trend Journal EN · en", { exact: true })).toBeVisible();
  await expect(page.getByText("Trend KO · ko", { exact: true })).toBeVisible();
  const zh = page.locator("fieldset").filter({ has: page.getByText("Trend ZH · zh-CN", { exact: true }) });
  await expect(zh).toBeVisible();
  await expect(zh.getByText("연결된 수집 지역: 없음")).toBeVisible();
  await expect(zh.getByLabel("Trends 자동 발행 허용")).not.toBeChecked();
  await expect(zh.getByRole("button", { name: "정책 변경 기록" })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
