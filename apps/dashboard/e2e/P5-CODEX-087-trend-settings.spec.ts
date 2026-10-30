import {expect,test} from "playwright/test";

test("collection controls and regional results render without page overflow",async({page},info)=>{
  await page.goto('/sources');
  await expect(page.getByRole('heading',{name:'Google Trends 수집 설정'})).toBeVisible();
  await expect(page.getByLabel('수집 주기')).toHaveValue('10');
  await expect(page.getByRole('button',{name:'설정 저장'})).toBeEnabled();
  await page.getByText('지역별 최근 수집 결과').click();
  await expect(page.getByText('AU ·',{exact:false}).first()).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:`.playwright-mcp/P5-CODEX-087-${info.project.name}.png`,fullPage:true});
});
