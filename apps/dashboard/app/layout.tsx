import "./style.css";
import AuthoringOnlyNotice from "./authoring-only-notice";
import DashboardNavigation from "./navigation";
import Script from "next/script";
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
        <Script id="woori-theme-init" strategy="beforeInteractive">
          {`try{var t=localStorage.getItem('woori-theme')||'system';var d=t==='system'?matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light':t;document.documentElement.dataset.theme=d}catch(e){document.documentElement.dataset.theme='light'}`}
        </Script>
        <div className="app-shell"><DashboardNavigation><AuthoringOnlyNotice />{children}</DashboardNavigation></div>
      </body>
    </html>
  );
}
