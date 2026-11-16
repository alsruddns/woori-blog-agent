import { NextRequest,NextResponse } from "next/server";
import { API_BASE,headers,localRequest } from "../../../../lib/server";

async function proxy(request:NextRequest,context:{params:Promise<{path?:string[]}>}) {
  if(!localRequest(request,true))return NextResponse.json({error:"Invalid origin"},{status:403});
  const path=(await context.params).path??[];const suffix=path.join("/");
  const allowed=request.method==="GET" && ["","capabilities"].includes(suffix)
    ||request.method==="POST" && (suffix===""||/^[a-f0-9-]{36}\/(cancel|retry)$/.test(suffix));
  if(!allowed)return NextResponse.json({error:"Unsupported authoring route"},{status:404});
  try {
    const result=await fetch(`${API_BASE}/admin/keyword-authoring${suffix?"/"+suffix:""}`,{
      method:request.method,headers:headers(),body:request.method==="POST"?await request.text():undefined,
      cache:"no-store",signal:AbortSignal.timeout(15000)});
    return NextResponse.json(await result.json(),{status:result.status,headers:{"Cache-Control":"no-store"}});
  }catch{return NextResponse.json({error:"Local authoring API unavailable"},{status:503});}
}
export const GET=proxy;
export const POST=proxy;
