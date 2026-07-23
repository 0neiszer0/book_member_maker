# Supabase RLS and API permissions

## Current trust boundary

The browser never creates a Supabase client and never receives a Supabase key.
Users sign in with Kakao, and Flask authorizes each request with its server-side
session. Database and Storage operations are performed by Flask with
`SUPABASE_SERVICE_KEY`.

This means Supabase Auth roles do not represent the application's members:

- `anon`: no `public` schema access
- `authenticated`: no `public` schema access
- `service_role`: server-only CRUD access
- `postgres`: migrations and dashboard administration

Do not put `SUPABASE_SERVICE_KEY` in templates, JavaScript, logs, or a public
environment-variable prefix.

## RLS policy

All tables in the exposed `public` schema have RLS enabled. They intentionally
have no policies for `anon` or `authenticated`, because the application does not
use browser-to-Supabase access. Table grants are also revoked from both roles so
that grants and RLS provide two independent barriers.

The private `board-uploads` Storage bucket is accessed only by the Flask service
client. Downloads use short-lived signed URLs.

## Adding database objects

Objects created by the `postgres` migration role are server-only by default:

- tables: `SELECT`, `INSERT`, `UPDATE`, `DELETE` for `service_role`
- sequences: `USAGE`, `SELECT` for `service_role`
- functions: `EXECUTE` for `service_role`
- no privileges for `anon` or `authenticated`

Every new table in `public` must still explicitly enable RLS in its migration:

```sql
ALTER TABLE public.example ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.example FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.example TO service_role;
```

Every new RPC must set an empty search path, schema-qualify referenced objects,
and revoke browser execution:

```sql
ALTER FUNCTION public.example_rpc(uuid) SET search_path = '';
REVOKE ALL ON FUNCTION public.example_rpc(uuid)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.example_rpc(uuid) TO service_role;
```

## If direct browser access is introduced later

Do not simply grant `authenticated` access. First migrate user identities to
Supabase Auth, define how `auth.uid()` maps to `members`, then add narrowly
scoped policies and grants for each operation. Flask authorization cannot
protect a direct Data API request.

## Audit query

After a schema migration, verify that all exposed tables have RLS and no browser
grants:

```sql
SELECT
    c.relname,
    c.relrowsecurity AS rls_enabled,
    (
        has_table_privilege('anon', c.oid, 'SELECT')
        OR has_table_privilege('anon', c.oid, 'INSERT')
        OR has_table_privilege('anon', c.oid, 'UPDATE')
        OR has_table_privilege('anon', c.oid, 'DELETE')
    ) AS anon_access,
    (
        has_table_privilege('authenticated', c.oid, 'SELECT')
        OR has_table_privilege('authenticated', c.oid, 'INSERT')
        OR has_table_privilege('authenticated', c.oid, 'UPDATE')
        OR has_table_privilege('authenticated', c.oid, 'DELETE')
    ) AS authenticated_access
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p')
ORDER BY c.relname;
```

Also run Supabase Security Advisor after every production migration.
