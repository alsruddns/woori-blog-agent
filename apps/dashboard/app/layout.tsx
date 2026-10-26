import "./style.css";
export const metadata = {
  title: "Woori Blog Agent",
  description: "Local blog operations dashboard",
};
export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
