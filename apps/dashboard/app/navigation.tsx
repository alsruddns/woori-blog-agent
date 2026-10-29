"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "대시보드", section: "/" },
  { href: "/sources", label: "수집 자료", section: "/sources" },
  { href: "/manuscripts", label: "원고 관리", section: "/manuscripts" },
  { href: "/publishing", label: "발행 관리", section: "/publishing" },
  { href: "/operations/research", label: "자동화 관리", section: "/operations/research" },
  { href: "/operations", label: "운영 진단", section: "/operations" },
];

export default function DashboardNavigation() {
  const pathname = usePathname();
  return <header className="app-topbar">
    <Link href="/" className="brand" aria-label="Woori Content Studio 홈">WOORI <span>CONTENT STUDIO</span></Link>
    <nav aria-label="주 메뉴" className="primary-navigation">
      {links.map(link => {
        const active = link.section === "/" ? pathname === "/" : pathname === link.section || (link.section !== "/operations" && pathname.startsWith(`${link.section}/`)) || (link.section === "/manuscripts" && pathname === "/imports") || (link.section === "/operations" && pathname === "/model-comparison");
        return <Link key={link.href} href={link.href} aria-current={active ? "page" : undefined}>{link.label}</Link>;
      })}
    </nav>
  </header>;
}
