import "./style.css";
import DashboardNavigation from "./navigation";
export const metadata = {
  title: "Woori Blog Agent",
  description: "Local blog operations dashboard",
};
export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body><div className="app-shell"><DashboardNavigation />{children}</div></body>
    </html>
  );
}
