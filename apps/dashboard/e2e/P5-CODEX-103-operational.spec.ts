import { test,expect } from 'playwright/test';
test.skip(process.env.WOORI_OPERATIONAL_VERIFY!=='1','Explicit read-only operational verification required');

test('actual persisted settings and worker application are visible',async({page},info)=>{
  const errors:string[]=[]; page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>localStorage.setItem('woori-theme','dark'));
  await page.route('**/api/**',route=>route.request().method()==='GET'?route.continue():route.abort('blockedbyclient'));
  await page.goto('/operations/automation');
  for(const [name,value] of [['Google Trends 수집','true'],['Codex 자동 원고 작성','true'],['Blogger 자동 발행','false'],['Blogger 수동 발행','true'],['Blogger 긴급 정지','false']]){
    await expect(page.getByRole('switch',{name,exact:true})).toHaveAttribute('aria-checked',value);
  }
  await expect(page.getByText('사용자가 제한 해제 확인',{exact:false})).toBeVisible();
  await expect(page.getByText('실제 쓰기 가능 여부: 미검증',{exact:true})).toBeVisible();
  await expect(page.getByText('Worker 적용 확인',{exact:false}).filter({hasText:'PID'})).toHaveCount(2);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({path:`../../docs/development/assets/P5-CODEX-103-live-${info.project.name}.png`,fullPage:true});
});
