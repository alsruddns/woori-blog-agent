import "./style.css";
import Link from "next/link";
export const metadata = {
  title: "Woori Blog Agent",
  description: "Local blog operations dashboard",
};
export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body><div className="app-shell"><header className="app-topbar"><Link href="/" className="brand">WOORI <span>CONTENT STUDIO</span></Link><nav aria-label="주 메뉴">
        <Link href="/">대시보드</Link><Link href="/sources">수집 자료</Link><Link href="/manuscripts">작성 원고</Link><Link href="/model-comparison">AI 원고 비교</Link><Link href="/publishing">발행 관리</Link><Link href="/operations/research#automation">자동화 관리</Link><Link href="/operations">운영·진단</Link>
      </nav></header>{children}</div></body>
    </html>
  );
}
