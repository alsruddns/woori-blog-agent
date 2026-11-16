"use client";

import { useState } from "react";

export default function ManuscriptCopy({ title, body, description, html }: { title: string; body: string; description: string; html: string }) {
  const [message, setMessage] = useState("");
  async function copy(label: string, value: string) {
    try { await navigator.clipboard.writeText(value); setMessage(`${label} 복사 완료`); }
    catch { setMessage("복사하지 못했습니다. 입력란에서 직접 선택해 복사하세요."); }
  }
  return <div className="import-actions">
    {([["원고 전체", `${title}\n\n${body}`], ["제목", title], ["본문", body], ["검색 설명", description], ["HTML", html]] as const).map(([label, value]) =>
      <button key={label} type="button" className="secondary-button" disabled={!value} onClick={() => void copy(label, value)}>{label} 복사</button>)}
    <span role="status">{message}</span>
  </div>;
}
