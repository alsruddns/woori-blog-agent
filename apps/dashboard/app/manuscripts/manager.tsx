"use client";

import Link from "next/link";
import { useState } from "react";
import { useSearchParams } from "next/navigation";
import ManuscriptWorkspace from "./workspace";
import { ExternalImportQueue } from "../imports/external-import-workspace";

type View = "written" | "external";

export default function ManuscriptManager() {
  const query = useSearchParams();
  const [view, setView] = useState<View>(() => query.get("view") === "external" ? "external" : "written");
  const selectView = (next: View) => {
    setView(next);
    const url = new URL(window.location.href);
    if (next === "written") url.searchParams.delete("view");
    else url.searchParams.set("view", next);
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  };

  return <>
    <div className="workspace-toolbar-row">
      <nav className="workspace-tabs" role="tablist" aria-label="원고 유형">
        <button role="tab" aria-selected={view === "written"} onClick={() => selectView("written")}>원고 목록</button>
        <button role="tab" aria-selected={view === "external"} onClick={() => selectView("external")}>가져온 원고</button>
      </nav>
      <Link className="primary-action" href="/imports">새 원고 가져오기</Link>
    </div>
    <p className="workspace-list-help">{view === "written"
      ? "내부 평가 및 저장된 원고의 최신 대표 버전입니다. 이전 버전은 상세의 변경 이력에서 확인할 수 있습니다."
      : "Codex 예약·수동 Import 등 가져온 원고와 현재 검토 상태입니다. 같은 계열은 최신 대표 원고만 표시하며 이전 버전은 상세 이력에 보존됩니다."}</p>
    {view === "written" ? <ManuscriptWorkspace /> : <ExternalImportQueue />}
  </>;
}
