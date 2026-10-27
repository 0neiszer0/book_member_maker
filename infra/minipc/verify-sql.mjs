import {PGlite} from '@electric-sql/pglite';
import fs from 'node:fs/promises';
const root=new URL('../../',import.meta.url);
const db=new PGlite();
try {
  await db.exec('create role anon; create role authenticated; create role service_role;');
  const baseline=await fs.readFile(new URL('supabase/migrations/20260501000000_legacy_schema_baseline.sql',root),'utf8');
  for(const table of ['members','notifications']) {
    const start=baseline.indexOf(`create table public.${table} (`);
    const end=baseline.indexOf('\n);',start)+3;
    await db.exec(baseline.slice(start,end));
  }
  const files=await fs.readdir(new URL('supabase/migrations/',root));
  const migration=files.find(f=>f.endsWith('_minipc_account_security.sql'));
  await db.exec(await fs.readFile(new URL('supabase/migrations/'+migration,root),'utf8'));
  await db.exec(await fs.readFile(new URL('testing/minipc_account_security.sql',root),'utf8'));
  console.log('PASS: disposable PostgreSQL account requests, admin protection and RPC privileges');
} finally {await db.close();}

