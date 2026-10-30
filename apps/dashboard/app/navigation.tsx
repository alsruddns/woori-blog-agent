"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

type Theme = "light" | "dark" | "system";
const subscribePreferences = (callback: () => void) => {
  window.addEventListener("storage", callback);
  window.addEventListener("woori-preferences", callback);
  return () => { window.removeEventListener("storage", callback); window.removeEventListener("woori-preferences", callback); };
};
const getThemePreference = (): Theme => {
  const value = localStorage.getItem("woori-theme");
  return value === "light" || value === "dark" || value === "system" ? value : "system";
};
const getCollapsedPreference = () => localStorage.getItem("woori-sidebar-collapsed") === "true";
const savePreference = (key: string, value: string) => { localStorage.setItem(key, value); window.dispatchEvent(new Event("woori-preferences")); };
const links = [
  { href: "/", label: "대시보드", group: "워크스페이스", icon: "home" },
  { href: "/sources", label: "수집 자료", group: "콘텐츠", icon: "sources" },
  { href: "/manuscripts", label: "원고 관리", group: "콘텐츠", icon: "draft" },
  { href: "/keyword-authoring", label: "키워드 원고 작성", group: "콘텐츠", icon: "draft" },
  { href: "/publishing", label: "발행 관리", group: "게시", icon: "publish" },
  { href: "/blogger", label: "Blogger 연결", group: "게시", icon: "blogger" },
  { href: "/operations/research", label: "자동화 관리", group: "게시", icon: "automation" },
  { href: "/operations", label: "운영 진단", group: "시스템", icon: "settings" },
];

function Icon({ name }: { name: string }) {
  const paths: Record<string, string> = {
    home: "M3 10.5 12 3l9 7.5M5.5 9v11h13V9M9 20v-6h6v6",
    sources: "M4 5h16M4 12h10M4 19h7M17 11l3 3-3 3",
    draft: "M5 3h10l4 4v14H5zM14 3v5h5M8 13h8M8 17h6",
    publish: "M4 12h12m-4-4 4 4-4 4M5 5h14v14H5z",
    blogger: "M8 7h8a4 4 0 0 1 0 8h-3m3 2H8a4 4 0 0 1 0-8h3m-2 4h6",
    automation: "M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1m0-12.8-2.1 2.1m-8.6 8.6-2.1 2.1M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
    settings: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-1.8 3.1-.2-.1a1.8 1.8 0 0 0-1.9.3l-.1.1h-3.6l-.1-.2a1.8 1.8 0 0 0-1.5-1.2 1.8 1.8 0 0 0-1.8.9l-.1.2-3.1-1.8.1-.2a1.8 1.8 0 0 0-.3-1.9l-.1-.1v-3.6l.2-.1a1.8 1.8 0 0 0 .3-1.9l-.1-.2 1.8-3.1.2.1a1.8 1.8 0 0 0 1.9-.3l.1-.1h3.6l.1.2a1.8 1.8 0 0 0 1.9.3l.2-.1 3.1 1.8-.1.2a1.8 1.8 0 0 0 .3 1.9l.1.1v3.6z",
  };
  return <svg aria-hidden="true" viewBox="0 0 24 24" className="nav-icon" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d={paths[name] ?? paths.home} /></svg>;
}

export default function DashboardNavigation({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const collapsed = useSyncExternalStore(subscribePreferences, getCollapsedPreference, () => false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const theme = useSyncExternalStore(subscribePreferences, getThemePreference, () => "system" as Theme);
  const mobileMenuRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => document.documentElement.dataset.theme = theme === "system" ? (media.matches ? "dark" : "light") : theme;
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);

  useEffect(() => {
    if (!mobileOpen) return;
    const prior = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setMobileOpen(false); mobileMenuRef.current?.focus(); return; }
      if (event.key === "Tab") {
        const focusable = document.querySelectorAll<HTMLElement>(".app-sidebar.is-mobile-open a[href],.app-sidebar.is-mobile-open button:not(:disabled),.app-sidebar.is-mobile-open select:not(:disabled)");
        if (!focusable.length) return;
        const first = focusable[0]; const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.querySelector<HTMLElement>(".app-sidebar.is-mobile-open a[href]")?.focus();
    window.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = prior; window.removeEventListener("keydown", onKey); };
  }, [mobileOpen]);

  const active = (href: string) => href === "/"
    ? pathname === "/"
    : href === "/operations"
      ? pathname === "/operations" || pathname === "/model-comparison"
      : pathname === href || pathname.startsWith(`${href}/`) || (href === "/manuscripts" && pathname === "/imports");

  return <>
    <aside id="dashboard-sidebar" className={`app-sidebar ${collapsed ? "is-collapsed" : ""} ${mobileOpen ? "is-mobile-open" : ""}`} aria-label="주 메뉴" role={mobileOpen ? "dialog" : undefined} aria-modal={mobileOpen ? true : undefined}>
      <Link href="/" className="brand" aria-label="Woori Content Studio 홈"><span className="brand-mark">W</span><span className="brand-copy"><strong>WOORI</strong><small>CONTENT STUDIO</small></span></Link>
      <nav className="sidebar-nav" aria-label="주 메뉴">
        {(["워크스페이스", "콘텐츠", "게시", "시스템"] as const).map(group => <div className="nav-group" key={group}>
          <p className="nav-group-label">{group}</p>
          {links.filter(link => link.group === group).map(link => <Link key={link.href} href={link.href} onClick={() => setMobileOpen(false)} className={active(link.href) ? "is-active" : ""} aria-current={active(link.href) ? "page" : undefined} title={collapsed ? link.label : undefined}>
            <Icon name={link.icon} /><span>{link.label}</span>
          </Link>)}
        </div>)}
      </nav>
      <div className="sidebar-footer"><span className="sidebar-status-dot" /><span className="sidebar-footer-label">로컬 운영 환경</span><small>API · DB 연결 상태는 진단에서 확인</small></div>
    </aside>
    {mobileOpen && <button className="sidebar-backdrop" aria-label="메뉴 닫기" onClick={() => setMobileOpen(false)} />}
    <div className="app-main-column">
      <header className="app-header">
        <div className="header-leading">
          <button ref={mobileMenuRef} className="icon-button mobile-menu-button" aria-label="메뉴 열기" aria-expanded={mobileOpen} aria-controls="dashboard-sidebar" onClick={() => setMobileOpen(true)}>☰</button>
          <button className="icon-button sidebar-toggle" aria-label={collapsed ? "사이드바 펼치기" : "사이드바 접기"} onClick={() => savePreference("woori-sidebar-collapsed", String(!collapsed))}>☰</button>
          <div className="header-context"><span>WOORI CONTENT STUDIO</span><strong>{links.find(link => active(link.href))?.label ?? "운영 콘솔"}</strong></div>
        </div>
        <div className="header-actions">
          <label className="theme-control"><span>테마</span><select aria-label="화면 테마" value={theme} onChange={event => savePreference("woori-theme", event.target.value)}><option value="light">라이트</option><option value="dark">다크</option><option value="system">시스템</option></select></label>
          <Link className="header-diagnostic-link" href="/operations">운영 상태</Link>
        </div>
      </header>
      <div className="app-content">{children}</div>
    </div>
  </>;
}
