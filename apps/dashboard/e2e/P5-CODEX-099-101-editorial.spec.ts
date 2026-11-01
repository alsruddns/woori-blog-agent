import { expect, test } from "playwright/test";
const version="00000000-0000-4000-8000-000000000001", evaluation="00000000-0000-4000-8000-000000000002", imported="00000000-0000-4000-8000-000000000003", older="00000000-0000-4000-8000-000000000004";
const stamp="2026-11-01T10:00:00Z";
const manuscript={evaluation_id:evaluation,id:evaluation,content_version_id:version,title:"Editorial integration fixture",body:"Summary Deck for the test article.\n\n## Background\n\nA repeated sentence for readers. A repeated sentence for readers.\n\n## Implications\n\nReader considerations.",language_code:"en",summary:"Reader guide.",keywords:[],sources:[],facts:[],checks:{},machine_passed:false,editorial_versions:[],review_actions_allowed:false};
test.beforeEach(async({page})=>{
 await page.route("**/api/**",async route=>{
  const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();
  const fulfill=(body:unknown)=>route.fulfill({json:body});
  if(path.endsWith('/editorial-intelligence/settings'))return fulfill({versions:[{id:1,weights:{news_value:25,freshness:20,reader_relevance:15,interest:15,article_potential:15,analysis_value:10},effective_slot:stamp}]});
  if(path.endsWith('/editorial-intelligence/aliases'))return fulfill({items:[]});
  if(path.endsWith('/editorial-intelligence/monitor'))return fulfill({selection:[],quality:[],trends_jobs:[],totals:{import_versions:2,evaluated:1}});
  if(path.includes('/editorial-intelligence/topics'))return fulfill({total:url.searchParams.get('q')?0:1,items:url.searchParams.get('q')?[]:[{id:version,query:'Interest rate policy',geo:'US',source_volume_label:'500+',score:76,decision:'selected',collection_slot:stamp,display_name:'Test English blog',language_code:'en',result:{components:{news_value:85,freshness:100},reasons:['Explicit region mapping and recent policy context.'],duplicate_matches:[]},jobs:null}]});
  if(path.includes('/editorial-intelligence/versions/'))return fulfill({link:{import_id:imported,import_version_id:version},reports:[{id:evaluation,import_version_id:version,content_version_id:version,engine_version:'trendjournal-quality/1',stage:'static',status:'completed',created_at:stamp,result:{scores:{caution:null,substance:null,analysis:null,seo:80,readability:50,localization:null,structure:75},overall_score:null,measured_score:70,measured_weight:30,evidence:{verified_claims:null,unverified_claims:1,source_count:0,source_original_examined:false},suggestions:[{id:'s1',category:'readability',field:'duplicate_sentence',location:'paragraph:2',original:'A repeated sentence for readers.',proposal:'A repeated sentence for readers.',reason:'Remove identical repeated wording.',expected_effect:'Mobile readability.',automatic:true,fact_check_required:false}]}}],events:[],versions:[{id:version,version_number:2,title:manuscript.title},{id:older,version_number:1,title:'Previous fixture title'}],selection:[],native_editorial_version:null});
  if(path.endsWith('/compare'))return fulfill({fields:{title:{diff:['--- before','+++ after','-Previous fixture title','+Editorial integration fixture']},body_markdown:{diff:['-Repeated paragraph','+Summary Deck and concise explanation']},seo_metadata:{diff:['-Old description','+Clear description']}}});
  if(path.endsWith('/suggestions'))return fulfill({action:'apply',new_version:{version_id:version}});
  if(path.endsWith('/trends/settings'))return fulfill({enabled:true,interval_minutes:10,regions:[],pending_interval_minutes:10,requested_window_hours:'0.17'});
  if(path.endsWith('/trend-editorial/blog-geos'))return fulfill({blogs:[],geos:['KR','US','JP'],mappings:[]});
  if(path.endsWith('/trend-editorial'))return fulfill({items:[],total:0,summary:{},geos:['US'],categories:[],blogs:[],blog_geo_mappings:[]});
  if(path.endsWith('/manuscripts'))return fulfill({items:[manuscript],total:1,page:1,page_size:25,languages:['en'],categories:[]});
  if(path.includes('/manuscripts/'))return fulfill(manuscript);
  if(path.endsWith('/editorial-preview'))return fulfill({title:manuscript.title,language_code:'en',post_html:'<p>Test Summary Deck</p>',labels:[],seo_metadata:{},seo_checks:[],renderer_version:'test',design_system_version:'test'});
  if(method!=='GET')return route.fulfill({status:409,json:{detail:'fixture_write_blocked'}});
  if(path.includes('/publications/'))return fulfill({blogs:[],policies:[],items:[],mode_policy:{emergency_stopped:true,blogger_api_restricted:true}});
  return fulfill({items:[],blogs:[],policies:[]});
 });
});

test('topic scores, filtering and weight validation at both viewport sizes',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/sources');
 const panel=page.getByRole('region',{name:'지능형 주제 선정'});
 await expect(panel.getByText('Interest rate policy',{exact:false})).toBeVisible();
 await expect(panel.getByText('500+',{exact:true})).toBeVisible();
 await panel.getByText('평가 가중치 설정',{exact:false}).click();
 await panel.getByLabel('뉴스 가치',{exact:true}).fill('30');
 await expect(panel.getByRole('button',{name:'다음 회차 가중치 저장'})).toBeDisabled();
 await panel.getByLabel('선정 검색어').fill('no matching topic');
 await expect(panel.getByText('조건에 맞는 선정 평가가 없습니다.',{exact:false})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 expect(errors).toEqual([]);
});

test('quality suggestions require exact-version confirmation and compare revisions',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/manuscripts');
 await page.getByRole('row',{name:/Editorial integration fixture 상세 보기/}).click();
 await page.getByRole('tab',{name:'품질·SEO',exact:true}).click();
 const panel=page.getByTestId('editorial-quality');
 await expect(panel.getByText('정적 평가만 완료',{exact:false})).toBeVisible();
 await expect(panel.getByText('종합 점수: 미평가',{exact:false})).toBeVisible();
 await panel.getByLabel('적용할 제안 선택').check();
 await expect(panel.getByRole('button',{name:'선택 제안을 새 버전으로 적용'})).toBeDisabled();
 await panel.getByLabel('선택한 수정안의 의미·사실',{exact:false}).check();
 await expect(panel.getByRole('button',{name:'선택 제안을 새 버전으로 적용'})).toBeEnabled();
 await panel.getByRole('button',{name:'버전 차이 보기'}).click();
 await expect(panel.locator('[data-kind=added]').first()).toBeVisible();
 await expect(panel.getByText('Summary Deck · 본문',{exact:true})).toBeVisible();
 await panel.getByRole('button',{name:'선택 제안을 새 버전으로 적용'}).click();
 await expect(panel.getByRole('status')).toContainText('새 Content Version');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 expect(errors).toEqual([]);
});

test('quality request failure is visible without an invented score',async({page})=>{
 await page.route('**/api/research/editorial-intelligence/versions/*',r=>r.fulfill({status:503,json:{error:'Evaluation temporarily unavailable'}}));
 await page.goto('/manuscripts');await page.getByRole('row',{name:/Editorial integration fixture 상세 보기/}).click();
 await page.getByRole('tab',{name:'품질·SEO',exact:true}).click();
 await expect(page.getByTestId('editorial-quality').getByRole('alert')).toContainText('Evaluation temporarily unavailable');
});
