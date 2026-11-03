import "./style.css";
import AuthoringOnlyNotice from "./authoring-only-notice";
import DashboardNavigation from "./navigation";
export const metadata = {
  title: "Woori Blog Agent",
  description: "Local blog operations dashboard",
};
export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <body>
        <div className="app-shell"><DashboardNavigation><AuthoringOnlyNotice />{children}</DashboardNavigation></div>
      </body>
    </html>
  );
}
