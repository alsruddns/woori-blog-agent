import { expect, test } from "playwright/test";

test("Visible automation polling preserves an unsaved policy reason", async ({ page }) => {
  await page.goto("/sources");
  const card=page.locator("fieldset").filter({has:page.getByText("Trend JA · ja",{exact:true})});
  const reason=card.getByLabel("변경 사유");
  await reason.fill("P096 unsaved direction must survive status refresh");
  await expect(card.getByText("원고 작성:",{exact:false})).toBeVisible();
  await page.waitForResponse(r=>r.url().includes("/api/publications/trends-auto-policy")&&r.status()===200);
  await expect(reason).toHaveValue("P096 unsaved direction must survive status refresh");
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test("Remote lookup error is distinct from confirmed deletion or LIVE", async ({ page }) => {
  let refreshed=false;
  await page.route("**/api/publications/post-publication-reviews?*",route=>route.fulfill({json:{total:1,items:[{
    id:"p096-isolated-job",publication_mode:"draft",review_status:"pending",review_notes:"",remote_url:null,
    remote_post_id:"1234567890",published_at:"2026-10-31T00:00:00Z",saved_at:"2026-10-31T00:00:00Z",
    remote_status:refreshed?"DRAFT":"NOT_FOUND",remote_check_error:refreshed?null:"not_found",
    title:"Isolated remote-state presentation",language_code:"ja",blog_name:"Isolated JA",
    blog_url:"https://example.invalid",open_item_count:0,high_count:0,review_items:[],claim_verification:[{verification_status:"unverified"}],
  }]}}));
  await page.route("**/api/publications/jobs/p096-isolated-job/sync-draft",route=>{refreshed=true;return route.fulfill({json:{remote_status:"DRAFT"}});});
  await page.goto("/publishing");
  await page.getByRole("tab",{name:"게시 후 보완",exact:true}).click();
  const card=page.locator("article.post-review-card");
  await expect(card.getByText("원격 조회 확인 필요",{exact:false})).toBeVisible();
  await expect(card.getByText("삭제로 단정하지 않음",{exact:false})).toBeVisible();
  await expect(card.getByRole("link",{name:"Blogger 글 열기"})).toHaveCount(0);
  await card.getByRole("button",{name:"Blogger Draft/LIVE 상태 재조회"}).click();
  await expect(card.getByText("Draft 모드 · 비공개 초안 저장 이력",{exact:true})).toBeVisible();
  await expect(card.getByText("검토 전",{exact:false})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
