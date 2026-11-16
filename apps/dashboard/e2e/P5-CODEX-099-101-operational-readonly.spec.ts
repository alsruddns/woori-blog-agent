import { expect, test } from "playwright/test";
import path from "node:path";
test.skip(process.env.WOORI_OPERATIONAL_VERIFY!=="1","Explicit read-only operational verification only");
test.beforeEach(async({page})=>{
  await page.addInitScript(()=>localStorage.setItem('woori-theme','dark'));
  // Candidate services read existing ops data. No editorial action, provider
  // request or publishing mutation is permitted by this verification.
  await page.route('**/api/**',route=>route.request().method()==='GET'||route.request().url().endsWith('/editorial-preview')?route.continue():route.abort());
});
test('current operational selection results and protected configuration',async({page},info)=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/sources');
  const panel=page.getByRole('region',{name:'지능형 주제 선정'});
  await expect(panel.getByRole('heading',{name:'지능형 주제 선정'})).toBeVisible();
  await expect(panel.locator('tbody tr').first()).toBeVisible();
  await expect(panel).toContainText('사실 검증이나 게시 승인이 아닙니다');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await panel.scrollIntoViewIfNeeded();
  await page.screenshot({path:path.resolve(`../../docs/development/assets/P5-CODEX-099-101-sources-${info.project.name}.png`)});
  expect(errors).toEqual([]);
});
test('stored English manuscript report is visible without modifying the original',async({page},info)=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/imports?open_import_id=71ab62c6-071c-4c67-a5a0-54fa8c3f68ef');
  await page.getByRole('tab',{name:'품질·SEO',exact:true}).click();
  const panel=page.getByTestId('editorial-quality');
  await expect(panel).toContainText('trendjournal-quality/3');
  await expect(panel).toContainText('독립 검증 Claim 미확인');
  await expect(panel.getByRole('button',{name:'선택 제안을 새 버전으로 적용'})).toBeDisabled();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await panel.getByText('종합 점수:',{exact:false}).scrollIntoViewIfNeeded();
  await page.screenshot({path:path.resolve(`../../docs/development/assets/P5-CODEX-099-101-quality-${info.project.name}.png`)});
  expect(errors).toEqual([]);
});
