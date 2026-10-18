import {env} from "cloudflare:workers";
import {getChatGPTUser} from "../../chatgpt-auth";
export const dynamic="force-dynamic";
const json=(value:unknown,status=200)=>Response.json(value,{status,headers:{"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"}});
const today=()=>new Date().toISOString().slice(0,10);
const fields=["phone","notes","gender","blood_type","height_cm","weight_kg","allergies","disabilities","eye_colour","tribe","medical_aid","medical_aid_number","address","emergency_contact"];
function date(value:unknown,label:string){if(typeof value!=="string"||!/^\d{4}-\d{2}-\d{2}$/.test(value)||isNaN(Date.parse(value))||new Date(value).toISOString().slice(0,10)!==value||value>today()||value<"1850-01-01")throw new Error(label+" must be a valid date, not in the future.");return value;}
function text(v:unknown,label:string,max=2000,required=false){if(v==null)v="";if(typeof v!=="string"||v.length>max)throw new Error(label+" is invalid or too long.");const s=v.trim();if(required&&!s)throw new Error(label+" is required.");return s;}
function patientBody(b:any){const out:any={name:text(b.name,"Full name",150,true),dob:date(b.dob,"Date of birth")};for(const key of fields)out[key]=text(b[key],key,2000);for(const [k,max] of [["height_cm",300],["weight_kg",700]] as const){if(out[k]&&(!Number.isFinite(Number(out[k]))||Number(out[k])<=0||Number(out[k])>max))throw new Error("Invalid "+k);}if(out.blood_type&&!["A+","A-","B+","B-","AB+","AB-","O+","O-"].includes(out.blood_type))throw new Error("Invalid blood type.");return out;}
function unpack(p:any){return {...JSON.parse(p.data),id:p.id,code:p.code,name:p.name,dob:p.dob,last_visit:p.last_visit,visit_count:p.visit_count,last_reason:p.last_reason};}
async function handle(req:Request,{params}:any){
 const user=await getChatGPTUser();if(!user)return json({error:"Sign in to access patient records."},401);
 const path=(await params).path||[], db=env.DB;
 if(req.method!=="GET"){const origin=req.headers.get("Origin");if(!origin||origin!==new URL(req.url).origin)return json({error:"Request origin not allowed"},403);if(!req.headers.get("content-type")?.includes("application/json"))return json({error:"JSON required"},415);}
 const auth=await adminAccess(req,path,user.userId,db);if(auth)return auth;
 if(path[0]==="me")return json({username:"Administrator",csrf:""});
 if(path[0]!=="patients")return json({error:"Not found"},404);
 try{
 if(path.length===1&&req.method==="GET"){
 const q=(new URL(req.url).searchParams.get("q")||"").trim().slice(0,150);
 const rows=await db.prepare("SELECT p.*, (SELECT MAX(date) FROM visits WHERE patient_id=p.id) last_visit, (SELECT COUNT(*) FROM visits WHERE patient_id=p.id) visit_count,(SELECT reason FROM visits WHERE patient_id=p.id ORDER BY date DESC,id DESC LIMIT 1) last_reason FROM patients p WHERE owner=? AND (instr(lower(name),lower(?))>0 OR instr(lower(code),lower(?))>0) ORDER BY name COLLATE NOCASE LIMIT 500").bind(user.userId,q,q).all();
 const stats=await db.prepare("SELECT (SELECT count(*) FROM patients WHERE owner=?) patients,(SELECT count(*) FROM visits v JOIN patients p ON p.id=v.patient_id WHERE p.owner=?) visits,(SELECT count(*) FROM visits v JOIN patients p ON p.id=v.patient_id WHERE p.owner=? AND v.date=?) today").bind(user.userId,user.userId,user.userId,today()).first();
 return json({patients:rows.results.map(unpack),stats});}
 const id=Number(path[1]);let existing:any;
 if(path.length>1){if(!Number.isSafeInteger(id)||id<1)return json({error:"Invalid record"},400);existing=await db.prepare("SELECT * FROM patients WHERE id=? AND owner=?").bind(id,user.userId).first();if(!existing)return json({error:"Patient not found"},404);}
 if(path.length===2&&req.method==="GET"){const visits=await db.prepare("SELECT * FROM visits WHERE patient_id=? ORDER BY date DESC,id DESC").bind(id).all();return json({patient:unpack(existing),visits:visits.results});}
 if(Number(req.headers.get("Content-Length")||0)>30000)return json({error:"Request too large"},413);
 const body=await req.json();
 if(path.length===1&&req.method==="POST"){
 const p=patientBody(body);let result:any;
 for(let n=0;n<8;n++){const bytes=crypto.getRandomValues(new Uint8Array(7));const chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789";const code=Array.from(bytes,v=>chars[v%chars.length]).join("");if(!/[A-Z]/.test(code)||!/[0-9]/.test(code))continue;
 try{result=await db.batch([db.prepare("INSERT INTO patients(owner,code,name,dob,data,created) VALUES(?,?,?,?,?,?)").bind(user.userId,code,p.name,p.dob,JSON.stringify(p),new Date().toISOString()),db.prepare("INSERT INTO audit(actor,action,record_id,at) VALUES(?,'create patient',last_insert_rowid(),?)").bind(user.userId,new Date().toISOString())]);break;}catch(e){if(!String(e).includes("UNIQUE"))throw e;}}
 if(!result)return json({error:"Unable to generate code; try again."},503);return json({id:result[0].meta.last_row_id},201);}
 if(path.length===2&&req.method==="PUT"){const p=patientBody(body);await db.batch([db.prepare("UPDATE patients SET name=?,dob=?,data=? WHERE id=? AND owner=?").bind(p.name,p.dob,JSON.stringify(p),id,user.userId),db.prepare("INSERT INTO audit(actor,action,record_id,at) VALUES(?,'update patient',?,?)").bind(user.userId,id,new Date().toISOString())]);return json({id});}
 if(path.length===3&&path[2]==="visits"&&req.method==="POST"){const d=date(body.date,"Visit date");if(d<existing.dob)throw new Error("A visit cannot precede the patient's birth.");await db.batch([db.prepare("INSERT INTO visits(patient_id,date,reason,medicine,notes) VALUES(?,?,?,?,?)").bind(id,d,text(body.reason,"Reason",2000,true),text(body.medicine,"Medicine",2000,true),text(body.notes,"Notes")),db.prepare("INSERT INTO audit(actor,action,record_id,at) VALUES(?,'record visit',?,?)").bind(user.userId,id,new Date().toISOString())]);return json({id},201);}
 return json({error:"Method not allowed"},405);
 }catch(e){if(e instanceof SyntaxError)return json({error:"Invalid JSON"},400);const msg=e instanceof Error?e.message:"Unable to process request";if(/D1|SQLITE|database/i.test(msg)){console.error("Patient database operation failed");return json({error:"Database temporarily unavailable. Please try again."},503);}return json({error:msg},400);}
}
export const GET=handle;export const POST=handle;export const PUT=handle;


const sessionCookie="__Host-promedics-admin";
async function digest(value:string){return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(value))),b=>b.toString(16).padStart(2,"0")).join("");}
async function adminAccess(req:Request,path:string[],owner:string,db:any){
 const token=(req.headers.get("Cookie")||"").split(";").map(s=>s.trim()).find(s=>s.startsWith(sessionCookie+"="))?.slice(sessionCookie.length+1)||"";
 const hash=await digest(token);
 const cookie=(value:string,age:number)=>sessionCookie+"="+value+"; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age="+age;
 const reply=(data:any,status:number,value:string,age:number)=>new Response(JSON.stringify(data),{status,headers:{"Content-Type":"application/json","Cache-Control":"no-store","Set-Cookie":cookie(value,age)}});
 if(path[0]==="logout"&&req.method==="POST"){await db.prepare("DELETE FROM admin_sessions WHERE token_hash=? AND owner=?").bind(hash,owner).run();return reply({ok:true},200,"",0);}
 if(path[0]==="login"&&req.method==="POST"){
  const failed=await db.prepare("SELECT count(*) n FROM audit WHERE actor=? AND action='failed admin login' AND at>?").bind(owner,new Date(Date.now()-15*60*1000).toISOString()).first();
  if(failed.n>=5)return json({error:"Too many login attempts. Please try again in 15 minutes."},429);
  let b;try{if(Number(req.headers.get("Content-Length")||0)>4096)return json({error:"Invalid login request"},400);b=await req.json();}catch{return json({error:"Invalid login request"},400);}
  const config=env as unknown as Record<string,any>;
  if(!config.PROMEDICS_ADMIN_USERNAME||!config.PROMEDICS_ADMIN_PASSWORD)return json({error:"Admin login is unavailable."},503);
  const expected=await digest(config.PROMEDICS_ADMIN_USERNAME+"\0"+config.PROMEDICS_ADMIN_PASSWORD);
  const actual=await digest(String(b.username||"").slice(0,100)+"\0"+String(b.password||"").slice(0,200));
  let diff=0;for(let i=0;i<expected.length;i++)diff|=expected.charCodeAt(i)^actual.charCodeAt(i);
  if(diff){await db.prepare("INSERT INTO audit(actor,action,record_id,at) VALUES(?,'failed admin login',0,?)").bind(owner,new Date().toISOString()).run();return json({error:"Incorrect username or password."},401);}
  const fresh=Array.from(crypto.getRandomValues(new Uint8Array(32)),b=>b.toString(16).padStart(2,"0")).join("");
  await db.batch([db.prepare("DELETE FROM admin_sessions WHERE expires<? OR (owner=? AND token_hash=?)").bind(Date.now(),owner,hash),db.prepare("INSERT INTO admin_sessions(token_hash,owner,expires) VALUES(?,?,?)").bind(await digest(fresh),owner,Date.now()+8*60*60*1000)]);
  return reply({username:"Administrator",csrf:""},200,fresh,8*60*60);
 }
 const session=token?await db.prepare("SELECT owner FROM admin_sessions WHERE token_hash=? AND owner=? AND expires>?").bind(hash,owner,Date.now()).first():null;
 if(!session)return json({error:"Please log in as an administrator."},401);
 return null;
}
