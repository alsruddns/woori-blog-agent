import { expect, test } from "playwright/test";

test.skip(process.env.WOORI_OPERATIONAL_VERIFY !== "1", "Read-only operational UI check");

test("discard confirmation opens with the editable default reason", async ({ page }) => {
  await page.route("**/api/**", route => route.request().method() === "GET" ? route.continue() : route.abort("blockedbyclient"));
  await page.goto("/publishing");
  const discard = page.locator(".publication-row-actions button:last-child").first();
  await expect(discard).toBeVisible();
  await discard.click();
  const dialog = page.locator(".publication-discard-dialog").filter({ has: page.locator("textarea") });
  await expect(dialog).toBeVisible();
  const reason = dialog.locator("textarea");
  await expect(reason).toHaveValue("\uD3D0\uAE30\uCC98\uB9AC \uD558\uAE30\uB85C \uACB0\uC815\uD568");
  await reason.fill("\uC0AC\uC720\uB97C \uC6B4\uC601\uC790\uAC00 \uC218\uC815\uD588\uC2B5\uB2C8\uB2E4.");
  await expect(reason).toHaveValue("\uC0AC\uC720\uB97C \uC6B4\uC601\uC790\uAC00 \uC218\uC815\uD588\uC2B5\uB2C8\uB2E4.");
  await dialog.locator("button").first().click();
});
