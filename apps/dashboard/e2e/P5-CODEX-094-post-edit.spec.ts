import { expect, test } from "playwright/test";

test("Trends post-edit policy is explicit and does not auto-approve", async ({ page }) => {
  await page.goto("/sources");
  await expect(page.getByText("기본 안전·중복·쓰기 간격", { exact: false }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "현재 연결·기존 LIVE 쓰기 이력 확인" })).toHaveCount(4);
  await expect(page.getByText("공개 승인 없이 비공개 초안을 저장합니다.", { exact: false }).first()).toBeVisible();
  await page.getByRole("radio", { name: "즉시 공개 발행 · 관리자 승인", exact: true }).first().check();
  await expect(page.getByText("관리자 자동 공개 승인 필요", { exact: false }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("Published review displays actual claim and human-review state", async ({ page }) => {
  await page.goto("/publishing");
  const response = page.waitForResponse(r => r.url().includes("/api/publications/post-publication-reviews?"));
  await page.getByRole("tab", { name: "게시 후 보완", exact: true }).click();
  const result = await response;
  expect(result.status()).toBe(200);
  const data = await result.json();
  expect(data.total).toBeGreaterThan(0);
  await expect(page.getByText("검토 상태:", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("Blogger 수정 여부를 자동 확인한 결과는 아닙니다.", { exact: false }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
