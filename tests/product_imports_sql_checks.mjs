import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';
const { PGlite } = await import(pathToFileURL(process.env.PGLITE_MODULE).href);
const db = new PGlite();
const admin='11111111-1111-4111-8111-111111111111', user='22222222-2222-4222-8222-222222222222';
const file='44444444-4444-4444-8444-444444444444', job='55555555-5555-4555-8555-555555555555';
try {
 await db.exec(await readFile(new URL('./user_management.sql',import.meta.url),'utf8'));
 await db.exec(`create schema storage;create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);create table storage.objects(bucket_id text);`);
 for (const name of ['007_portal_products','008_shared_uploads','009_product_import_preview'])
  await db.exec(await readFile(new URL(`../migrations/${name}.sql`,import.meta.url),'utf8'));
 const action=async(actor,op,id=job,data={})=>(await db.query('select portal_product_import_action($1,$2,$3,$4) as r',[actor,op,id,data])).rows[0].r;
 const worker=async(op,j=null,data={})=>(await db.query('select portal_product_import_worker($1,$2,$3,$4) as r',[op,j?.id??null,j?.lease_token??null,data])).rows[0].r;
 await db.query(`insert into portal_uploaded_files(id,purpose,object_path,original_name,content_type,size_bytes,sha256,created_by,status)
 values($1,'product_import','path','p.csv','text/csv',10,$2,$3,'ready')`,[file,'a'.repeat(64),admin]);
 const body={file_id:file,sheet_name:null};
 await assert.rejects(action(user,'create',job,body),/FORBIDDEN/);
 const created=await action(admin,'create',job,body);
 assert.equal(created.status,'queued');assert.ok(!('lease_token' in created));
 assert.equal((await action(admin,'create',job,body)).id,job);
 await assert.rejects(action(admin,'create',job,{...body,sheet_name:'Other'}),/IDEMPOTENCY_CONFLICT/);
 await assert.rejects(db.query("select portal_uploaded_file_action($1,'delete',$2)",[admin,file]),/FILE_IN_USE/);
 await assert.rejects(action(admin,'rows'),/IMPORT_NOT_READY/);
 await db.exec(`insert into permissions values(7,'PRODUCT_IMPORT');insert into user_permissions(user_id,permission_id) values('${user}',7);`);
 await assert.rejects(action(user,'get'),/IMPORT_NOT_FOUND/);
 const claimed=await worker('claim');assert.equal(claimed.attempts,1);
 assert.equal(await worker('claim'),null);
 await worker('heartbeat',claimed);
 await db.query("update portal_product_imports set lease_until=now()-interval '1 second' where id=$1",[job]);
 const reclaimed=await worker('claim');assert.equal(reclaimed.attempts,2);
 await assert.rejects(worker('finish',claimed,{rows:[]}),/IMPORT_LEASE_LOST/);
 await db.query(`insert into portal_products(product_code,product_name,is_active,created_by,updated_by) values('A','Old',false,$1,$1),('B','Same',true,$1,$1),('MISSING','Keep',true,$1,$1)`,[admin]);
 await worker('finish',reclaimed,{rows:[
  {source_row:5,product_code:'A',product_name:'New',occurrences:2},
  {source_row:6,product_code:'B',product_name:'Same'},
  {source_row:7,product_code:'C',product_name:'Create'},
  {source_row:8,product_code:'D',product_name:'Conflict',error_code:'CONFLICTING_PRODUCT_NAME'}],summary:{source_rows:5}});
 const ready=await action(admin,'get');
 assert.equal(ready.status,'preview_ready');assert.equal(ready.summary.has_errors,true);
 assert.equal(ready.summary.create,1);assert.equal(ready.summary.update,1);assert.equal(ready.summary.unchanged,1);
 const page=await action(admin,'rows',job,{page:1,page_size:2});
 assert.equal(page.items.length,2);assert.equal(page.pagination.total,4);assert.equal(page.pagination.has_next,true);
 assert.equal(page.items[0].existing.is_active,false);
 assert.equal((await action(admin,'rows',job,{action:'error'})).items.length,1);
 assert.equal((await db.query("select product_name from portal_products where product_code='A'")).rows[0].product_name,'Old');
 assert.equal((await db.query('select count(*)::int n from portal_products')).rows[0].n,3);
 // Access revoked while processing: no preview is published.
 const second='66666666-6666-4666-8666-666666666666';
 await action(admin,'create',second,body);const secondClaim=await worker('claim');
 await db.query('update profiles set "isActive"=false where id=$1',[admin]);
 assert.equal(await worker('finish',secondClaim,{rows:[{source_row:1,product_code:'X',product_name:'X'}]}),null);
 assert.equal((await db.query('select status from portal_product_imports where id=$1',[second])).rows[0].status,'failed');
 await db.query('update profiles set "isActive"=true where id=$1',[admin]);
 const pending=['77777777-7777-4777-8777-777777777771','77777777-7777-4777-8777-777777777772','77777777-7777-4777-8777-777777777773'];
 for(const id of pending) await action(admin,'create',id,body);
 await assert.rejects(action(admin,'create','77777777-7777-4777-8777-777777777774',body),/IMPORT_QUEUE_FULL/);
 const exhausted=await worker('claim');
 await db.query("update portal_product_imports set attempts=3,lease_until=now()-interval '1 second' where id=$1",[exhausted.id]);
 await worker('claim');
 assert.equal((await action(admin,'get',exhausted.id)).error_code,'IMPORT_RETRY_EXHAUSTED');
 await db.exec('set role authenticated');
 await assert.rejects(action(admin,'get'),/permission denied/);
 await assert.rejects(worker('claim'),/permission denied/);
 await assert.rejects(db.query('select * from portal_product_import_rows'),/permission denied/);
 console.log('Product import SQL passed: idempotency, ownership, lease recovery, stale worker, preview snapshot, pagination, file guard, revoked access, RLS; product catalog unchanged.');
} finally { await db.close(); }
