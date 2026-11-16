"use client";
import { useEffect,useState } from 'react';
type Policy={trends_collection_enabled:boolean;auto_manuscript_enabled:boolean;auto_publishing_enabled:boolean;manual_publishing_enabled:boolean;emergency_stop:boolean;blogger_api_restricted:boolean};

export default function AuthoringOnlyNotice() {
  const [policy,setPolicy]=useState<Policy|null>(null);
  useEffect(()=>{
    let active=true;
    const load=async()=>{try{const response=await fetch('/api/automation-controls',{cache:'no-store'});const data=await response.json();if(active)setPolicy(response.ok&&typeof data.settings?.auto_publishing_enabled==='boolean'?data.settings:null);}catch{if(active)setPolicy(null);}};
    void load();const timer=setInterval(()=>void load(),15000);window.addEventListener('woori-automation-policy-changed',load);return()=>{active=false;clearInterval(timer);window.removeEventListener('woori-automation-policy-changed',load);};
  },[]);
  return <section role="status" className="workspace-panel" data-testid="authoring-only-notice">
    <strong>{policy?`Trends ${policy.trends_collection_enabled?'ON':'OFF'} / 자동 원고 ${policy.auto_manuscript_enabled?'ON':'OFF'} / Blogger 자동 발행 ${policy.auto_publishing_enabled?'ON':'OFF'} / 수동 발행 ${policy.manual_publishing_enabled?'ON':'OFF'}`:'운영 설정 확인 대기 · 실행 허용 상태는 아직 확인되지 않았습니다.'}</strong>
    <p>{policy?.emergency_stop?'긴급 정지가 활성화되어 모든 Blogger 쓰기가 차단됩니다. ':''}{policy?.blogger_api_restricted?'프로젝트의 Google API 제한 게이트가 활성화되어 있습니다. ':''}수집·작성·발행 설정과 실제 Worker 적용 상태는 운영 제어센터에서 확인하세요. 기존 원고와 Job은 보존되며 수동 공개에는 정확한 버전의 최종 확인이 필요합니다.</p>
    <a href="/operations/automation">자동화 운영 제어센터</a>{' · '}
    <a href="https://www.blogger.com/" target="_blank" rel="noopener noreferrer">Blogger 관리자에서 직접 검토·게시</a>
  </section>;
}
