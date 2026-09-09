// Isolated PGlite database. Does not contact Supabase.
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
const { PGlite } = await import(process.env.PGLITE_MODULE ? pathToFileURL(process.env.PGLITE_MODULE).href : '@electric-sql/pglite');
const db = new PGlite();
const admin='11111111-1111-4111-8111-111111111111', member='22222222-2222-4222-8222-222222222222';
const call = async (action,data,actor=admin) => (await db.query(
 'select public.portal_documents_write($1,$2,$3::jsonb) as data',[actor,action,JSON.stringify(data)])).rows[0].data;
try {
 await db.exec(await readFile(new URL('./user_management.sql',import.meta.url),'utf8'));
 await db.exec(`create schema storage;
 create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);
 create table storage.objects(id uuid default gen_random_uuid(),bucket_id text);
 alter table storage.objects enable row level security;
 grant usage on schema storage to anon,authenticated;
 grant select on storage.objects to anon,authenticated;
 create policy existing_broad_policy on storage.objects for select to anon,authenticated using(true);
 insert into storage.objects(bucket_id) values ('portal_documents'),('team_bucket');`);
 await db.exec(await readFile(new URL('../migrations/002_portal_documents.sql',import.meta.url),'utf8'));
 const task=(await db.query('select id from portal_document_tasks')).rows[0].id;
 const type=(await db.query('select id from portal_document_types limit 1')).rows[0].id;
 await assert.rejects(call('create_request',{task_id:task,title:'Forbidden'},member),/FORBIDDEN/);
 await db.exec(`insert into permissions(id,permission_code) values (5,'DOC_CREATE');
 insert into user_permissions(user_id,permission_id) values ('${member}',5);`);
 const memberReq=await call('create_request',{task_id:task,title:'Member request'},member);
 assert.equal(memberReq.created_by,member);
 await assert.rejects(call('update_request',{request_id:memberReq.id,title:'No update right'},member),/FORBIDDEN/);
 await db.exec(`update profiles set "isActive"=false where id='${member}'`);
 await assert.rejects(call('create_request',{task_id:task,title:'Inactive'},member),/FORBIDDEN/);
 const req=await call('create_request',{task_id:task,title:'Test'});
 assert.equal(req.template_id,null);
 const doc=await call('create_document',{request_id:req.id,document_type_id:type,title:'Contract'});
 const data={request_id:req.id,document_id:doc.id,file_id:randomUUID(),sort_order:1,
 original_name:'test.png',content_type:'image/png',size_bytes:100,sha256:'a'.repeat(64)};
 let file=await call('reserve_file',data);
 assert.equal(file.status,'uploading');
 assert.equal((await call('reserve_file',data)).id,file.id);
 await assert.rejects(call('reserve_file',{...data,sha256:'b'.repeat(64)}),/IDEMPOTENCY_CONFLICT/);
 const req2=await call('create_request',{task_id:task,title:'Other'});
 await assert.rejects(call('reserve_file',{...data,request_id:req2.id}),/DOCUMENT_NOT_FOUND/);
 file=await call('complete_file',data); assert.equal(file.status,'ready');
 assert.equal((await call('reorder_file',{...data,sort_order:3})).sort_order,3);
 file=await call('delete_file',data); assert.equal(file.status,'deleted');
 await assert.rejects(call('complete_file',data),/FILE_DELETED/);
 await assert.rejects(call('reserve_file',data),/FILE_DELETED/);
 // Failed linking must roll back the inserted metadata row.
 const invalid={...data,file_id:randomUUID(),sort_order:0};
 await assert.rejects(call('reserve_file',invalid),/check constraint/);
 assert.equal((await db.query('select count(*)::int as n from portal_files where id=$1',[invalid.file_id])).rows[0].n,0);
 for(let i=0;i<30;i++) await call('reserve_file',{...data,file_id:randomUUID(),sort_order:i+1});
 await assert.rejects(call('reserve_file',{...data,file_id:randomUUID()}),/FILE_LIMIT/);
 await call('update_request',{request_id:req.id,status:'archived'});
 await assert.rejects(call('create_document',{request_id:req.id,document_type_id:type,title:'No'}),/REQUEST_ARCHIVED/);
 await db.exec('set role authenticated');
 assert.deepEqual((await db.query('select bucket_id from storage.objects')).rows,[{bucket_id:'team_bucket'}]);
 await assert.rejects(db.query('select * from public.portal_files'),/permission denied/);
 await assert.rejects(call('create_request',{task_id:task,title:'No'}),/permission denied/);
 await db.exec('reset role');
 await db.exec(await readFile(new URL('../migrations/003_document_search.sql',import.meta.url),'utf8'));
 const search=async(type,text)=>(await db.query('select id from portal_search_document_requests($1,$2)',[type,text])).rows;
 assert.deepEqual(await search(type,'contract'),[{id:req.id}]);
 assert.deepEqual(await search(type,'TEST'),[{id:req.id}]);
 assert.equal((await search(null,'Member')).length,1);
 assert.equal((await search(randomUUID(),'')).length,0);
 assert.equal((await search(null,'%')).length,0);
 assert.equal((await search(null,"' OR true --")).length,0);
 assert.equal((await search(null,'   ')).length,3);
 const otherType=(await db.query('select id from portal_document_types where id<>$1 limit 1',[type])).rows[0].id;
 await call('create_document',{request_id:req2.id,document_type_id:type,title:'First'});
 await call('create_document',{request_id:req2.id,document_type_id:type,title:'First copy'});
 await call('create_document',{request_id:req2.id,document_type_id:otherType,title:'Invoice'});
 assert.equal((await search(type,'First')).length,1); // no duplicate requests
 assert.equal((await search(type,'Invoice')).length,0); // same document must match
 assert.equal((await db.query('select count(*)::int n from portal_search_document_requests($1,$2)',[type,''])).rows[0].n,2);
 assert.equal((await db.query('select id from portal_search_document_requests($1,$2) order by created_at desc,id limit 1 offset 1',[type,''])).rows.length,1);
 await db.exec('set role authenticated');
 await assert.rejects(search(null,''),/permission denied/);
 await db.exec('reset role');
 console.log('Documents SQL passed: creation, retries, mismatch, rollback, limits, archive, RLS, shared bucket isolation.');
} finally { await db.close(); }
