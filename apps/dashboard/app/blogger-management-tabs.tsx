import Link from "next/link";

export default function BloggerManagementTabs({
  active,
}: {
  active: "connections" | "language-policy";
}) {
  return (
    <nav className="blogger-management-tabs" aria-label="Blogger 관리">
      <Link href="/blogger" aria-current={active === "connections" ? "page" : undefined}>
        Blogger 연결 관리
      </Link>
      <Link href="/config" aria-current={active === "language-policy" ? "page" : undefined}>
        언어·정책 설정
      </Link>
    </nav>
  );
}
