import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';
const { PGlite } = await import(pathToFileURL(process.env.PGLITE_MODULE).href);
const db = new PGlite();
const user='11111111-1111-4111-8111-111111111111';
try {
 await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
 create table profiles(id uuid primary key); insert into profiles values ('${user}');`);
 await db.exec(await readFile(new URL('../migrations/007_portal_products.sql',import.meta.url),'utf8'));
 const insert=async(code,name)=>(await db.query('insert into portal_products(product_code,product_name,created_by,updated_by) values($1,$2,$3,$3) returning *',[code,name,user])).rows[0];
 const p=await insert('PRODUCT-001','Product one'); assert.equal(p.is_active,true);
 await assert.rejects(insert('PRODUCT-001','Duplicate'),/unique/);
 await assert.rejects(insert('  ','Empty'),/check/);
 await assert.rejects(insert('PRODUCT-002','  '),/check/);
 const changed=(await db.query("update portal_products set product_name='New name',is_active=false,updated_at='2000-01-01' where id=$1 returning *",[p.id])).rows[0];
 assert.equal(changed.id,p.id); assert.equal(changed.is_active,false);
 assert.notEqual(String(changed.updated_at),'2000-01-01T00:00:00.000Z');
 for(const role of ['anon','authenticated']) {
  await db.exec(`set role ${role}`);
  await assert.rejects(db.query('select * from portal_products'),/permission denied/);
  await db.exec('reset role');
 }
 await db.exec('set role service_role');
 assert.equal((await db.query('select * from portal_products')).rows.length,1);
 await assert.rejects(db.query('delete from portal_products'),/permission denied/);
 await db.exec('reset role');
 console.log('Products schema SQL passed: uniqueness, validation, audit timestamp, identity preservation, access controls.');
} finally { await db.close(); }
