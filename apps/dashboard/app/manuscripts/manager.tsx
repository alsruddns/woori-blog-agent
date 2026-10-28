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
        <button role="tab" aria-selected={view === "written"} onClick={() => selectView("written")}>작성 원고</button>
        <button role="tab" aria-selected={view === "external"} onClick={() => selectView("external")}>외부 검토 대기</button>
      </nav>
      <Link className="primary-action" href="/imports">원고 가져오기</Link>
    </div>
    {view === "written" ? <ManuscriptWorkspace /> : <ExternalImportQueue />}
  </>;
}
