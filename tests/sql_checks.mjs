// npm install --no-save @electric-sql/pglite in an isolated scratch directory.
// Set PGLITE_MODULE to that package's dist/index.js, then node tests/sql_checks.mjs.
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href : '@electric-sql/pglite');
const db = new PGlite();
const admin = '11111111-1111-4111-8111-111111111111';
const manager = '22222222-2222-4222-8222-222222222222';
const target = '33333333-3333-4333-8333-333333333333';
const call = async (actor, action, uid, email = null, ids = null, superadmin = null, active = null) =>
  (await db.query('select public.portal_manage_user($1,$2,$3,$4,$5,$6,$7) as data',
    [actor, action, uid, email, ids, superadmin, active])).rows[0].data;
try {
  await db.exec(await readFile(new URL('./user_management.sql', import.meta.url), 'utf8'));
  await db.exec(await readFile(new URL('../migrations/001_portal_manage_user.sql', import.meta.url), 'utf8'));
  let user = await call(admin, 'create', target, 'new@example.com', [1, 2, 2]);
  assert.deepEqual(user.permissions, ['USER_CREATE', 'USER_UPDATE']);
  assert.equal(user.is_first_login, true);
  assert.equal(user.is_active, true);
  await assert.rejects(call(manager, 'update', target, null, [4]), /FORBIDDEN/);
  await assert.rejects(call(manager, 'update', target, null, null, true), /FORBIDDEN/);
  await assert.rejects(call(manager, 'update', target, null, null, null, false), /FORBIDDEN/);
  await assert.rejects(call(manager, 'deactivate', target), /FORBIDDEN/);
  await assert.rejects(call(admin, 'deactivate', admin), /SELF_UPDATE_FORBIDDEN/);
  await assert.rejects(call(admin, 'update', target, 'changed@example.com', [999]), /INVALID_PERMISSION_IDS/);
  let saved = (await db.query('select email from profiles where id=$1', [target])).rows[0];
  assert.equal(saved.email, 'new@example.com');
  await db.exec(`create function fail_assignment() returns trigger language plpgsql as
    $$ begin raise exception 'SIMULATED_WRITE_FAILURE'; end $$;
    create trigger fail_assignment before insert on user_permissions
    for each row execute function fail_assignment();`);
  await assert.rejects(call(admin, 'update', target, 'changed@example.com', [4]), /SIMULATED_WRITE_FAILURE/);
  saved = (await db.query('select email from profiles where id=$1', [target])).rows[0];
  assert.equal(saved.email, 'new@example.com');
  assert.equal((await db.query('select count(*)::int as n from user_permissions where user_id=$1', [target])).rows[0].n, 2);
  await db.exec('drop trigger fail_assignment on user_permissions; drop function fail_assignment()');
  user = await call(admin, 'update', target, null, []);
  assert.deepEqual(user.permissions, []);
  user = await call(admin, 'deactivate', target);
  assert.equal(user.is_active, false);
  user = await call(admin, 'update', target, null, [4], null, true);
  assert.equal(user.is_active, true);
  assert.deepEqual(user.permissions, ['USER_VIEW']);
  await assert.rejects(call(manager, 'update', target, 'other@example.com'), /FORBIDDEN/);
  await assert.rejects(call(admin, 'update', target, 'ADMIN@example.com'), /EMAIL_ALREADY_EXISTS/);
  await db.exec(`set role authenticated`);
  await assert.rejects(call(admin, 'deactivate', target), /permission denied/);
  await db.exec('reset role; set role service_role');
  user = await call(admin, 'update', target, null, []);
  assert.deepEqual(user.permissions, []);
  console.log('SQL checks passed: permissions, atomic rejection, clearing, activity, role restrictions.');
} finally {
  await db.close();
}
