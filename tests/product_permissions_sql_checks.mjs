import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';
const { PGlite } = await import(pathToFileURL(process.env.PGLITE_MODULE).href);
const db = new PGlite();
try {
 await db.exec(`create table permission_groups(id bigserial primary key,group_name text unique not null,description text);
 create table permissions(id bigserial primary key,group_id bigint references permission_groups,permission_code text unique not null,permission_name text not null);
 create table user_permissions(user_id uuid,permission_id bigint references permissions);
 insert into permission_groups(group_name,description) values ('EXISTING','Keep');
 insert into permissions(group_id,permission_code,permission_name) values (1,'PRODUCT_VIEW','Existing label');
 insert into user_permissions values ('11111111-1111-4111-8111-111111111111',1);`);
 const sql=await readFile(new URL('../migrations/006_product_permissions.sql',import.meta.url),'utf8');
 await db.exec(sql); await db.exec(sql);
 const rows=(await db.query('select permission_code,permission_name,group_id from permissions order by permission_code')).rows;
 assert.equal(rows.length,6);
 assert.equal(rows.find(r=>r.permission_code==='PRODUCT_VIEW').permission_name,'Existing label');
 assert.equal(rows.find(r=>r.permission_code==='PRODUCT_VIEW').group_id,1);
 assert.equal((await db.query('select * from user_permissions')).rows.length,1);
 assert.equal((await db.query("select * from permission_groups where group_name='PRODUCT'")).rows.length,1);
 console.log('Product permissions SQL passed: six codes, safe rerun, existing labels/groups/assignments preserved.');
} finally { await db.close(); }
