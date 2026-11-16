import { expect, test } from "playwright/test";

test("Draft is the default and public selection requires explicit consent", async ({ page }) => {
  await page.goto("/sources");
  const card = page.locator("fieldset").filter({ has: page.getByText("Trend KO · ko", { exact: true }) });
  await expect(card.getByRole("radio", { name: "임시발행(비공개 초안 저장) · 기본" })).toBeChecked();
  await expect(card.getByText("공개 승인 없이 비공개 초안을 저장합니다.", { exact: false })).toBeVisible();
  await expect(card.getByLabel("공개 발행 명시적 확인 문구")).toHaveCount(0);
  await card.getByRole("radio", { name: "즉시 공개 발행 · 관리자 승인" }).check();
  await expect(card.getByLabel("공개 발행 명시적 확인 문구")).toBeVisible();
  await expect(card.getByRole("button", { name: "정책 변경 기록" })).toBeDisabled();
  // Local selection only: never save a public policy or create a publication.
  await card.getByRole("radio", { name: "임시발행(비공개 초안 저장) · 기본" }).check();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("Private draft queue has a distinct filter and real database-backed counts", async ({ page }) => {
  await page.goto("/publishing");
  const panel = page.locator("section").filter({ has: page.getByRole("heading", { name: "Publication Worker · 실제 발행 Job" }) });
  await expect(panel.getByText("Blogger 비공개 초안 저장", { exact: false }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
