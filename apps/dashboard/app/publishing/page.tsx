import Link from "next/link";
import { API_BASE, headers } from "../../lib/server";
import PublicationManager, { type PublicationData } from "./publication-manager";

export const dynamic = "force-dynamic";

export default async function Page() {
  let data: PublicationData | null = null;
  try {
    if (process.env.ADMIN_TOKEN) {
      const response = await fetch(`${API_BASE}/admin/publications`, {
        headers: headers(), cache: "no-store", signal: AbortSignal.timeout(5000),
      });
      if (response.ok) data = await response.json() as PublicationData;
    }
  } catch {}
  return <main>
    <header><Link href="/">WOORI / OPERATIONS</Link><Link href="/blogger">Blogger read-only</Link></header>
    <h1>Publication requests</h1>
    <aside role="status">Simulation only. Real Blogger POST, PUT, PATCH, and DELETE are disabled. No human-review approval or publish-ready override is available here.</aside>
    {data ? <PublicationManager initial={data} /> : <p role="alert">Local API unavailable or not authenticated.</p>}
  </main>;
}
