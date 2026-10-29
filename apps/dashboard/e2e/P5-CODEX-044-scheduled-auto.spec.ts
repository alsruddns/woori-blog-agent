import { expect, test } from "playwright/test";

test("publishing exposes scheduled Auto controls and history without invoking writes", async ({ page }) => {
  const nonReadRequests: string[] = [];
  page.on("request", request => {
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) {
      nonReadRequests.push(`${request.method()} ${new URL(request.url()).pathname}`);
    }
  });

  await page.goto("/publishing");
  await expect(page.getByRole("heading", { name: "발행 관리" })).toBeVisible();
  await page.getByRole("tab", { name: "예약 Auto" }).click();
  await expect(page.getByRole("heading", { name: "예약 원고 자동 게시 관리" })).toBeVisible();
  const targetGroup = page.getByRole("group", { name: "예약 원고 자동 게시 대상" });
  await expect(targetGroup).toBeVisible();
  const targets = targetGroup.getByRole("checkbox");
  expect(await targets.count()).toBeGreaterThan(0);
  await targets.first().check();
  const readCheckButton = page.getByRole("button", { name: "선택 블로그 읽기 연결 확인" });
  await expect(readCheckButton).toBeEnabled();
  const enableButton = page.getByRole("button", { name: "선택 블로그 예약 Auto 승인·활성화" });
  const stopButton = page.getByRole("button", { name: "예약 원고 자동 게시 중지" });
  await expect(enableButton).toBeVisible();
  await expect(stopButton).toBeVisible();
  await expect(page.getByRole("heading", { name: "예약 Auto 승인 이력" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "첫 게시 승인·취소 이력" })).toBeVisible();
  const enabled = await page.getByText("예약 Auto 활성", { exact: true }).count();
  if (enabled) {
    await expect(enableButton).toBeDisabled();
    await expect(stopButton).toBeEnabled();
  } else {
    await expect(enableButton).toBeEnabled();
    await expect(stopButton).toBeDisabled();
  }
  expect(nonReadRequests).toEqual([]);
});
