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
 if(path[0]==="me")return json({username:user.displayName,csrf:""});
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

