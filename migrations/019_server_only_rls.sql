-- The Flask application is the only database client.
-- Kakao/session authorization is enforced by Flask, while Supabase is accessed
-- with SUPABASE_SERVICE_KEY exclusively from the server.

BEGIN;

-- Do not expose the public schema to browser API roles.
REVOKE ALL PRIVILEGES ON SCHEMA public FROM anon, authenticated;
GRANT USAGE ON SCHEMA public TO service_role;

-- Every application and retained legacy table is server-only.
-- RLS without browser policies is deliberate defense in depth.
DO $$
DECLARE
    target record;
BEGIN
    FOR target IN
        SELECT n.nspname AS schema_name, c.relname AS table_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'p')
        ORDER BY c.relname
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',
            target.schema_name,
            target.table_name
        );
        EXECUTE format(
            'REVOKE ALL PRIVILEGES ON TABLE %I.%I FROM anon, authenticated',
            target.schema_name,
            target.table_name
        );
        EXECUTE format(
            'REVOKE TRUNCATE, REFERENCES, TRIGGER ON TABLE %I.%I FROM service_role',
            target.schema_name,
            target.table_name
        );
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I.%I TO service_role',
            target.schema_name,
            target.table_name
        );
    END LOOP;
END
$$;

-- Remove obsolete browser policies. Re-granting table access in a future
-- browser client must always be accompanied by newly reviewed, identity-aware
-- policies.
DO $$
DECLARE
    target record;
BEGIN
    FOR target IN
        SELECT schemaname, tablename, policyname
        FROM pg_policies
        WHERE schemaname = 'public'
        ORDER BY tablename, policyname
    LOOP
        EXECUTE format(
            'DROP POLICY %I ON %I.%I',
            target.policyname,
            target.schemaname,
            target.tablename
        );
    END LOOP;
END
$$;

-- Serial/identity values are generated only for server-side writes.
DO $$
DECLARE
    target record;
BEGIN
    FOR target IN
        SELECT n.nspname AS schema_name, c.relname AS sequence_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'S'
        ORDER BY c.relname
    LOOP
        EXECUTE format(
            'REVOKE ALL PRIVILEGES ON SEQUENCE %I.%I FROM anon, authenticated, service_role',
            target.schema_name,
            target.sequence_name
        );
        EXECUTE format(
            'GRANT USAGE, SELECT ON SEQUENCE %I.%I TO service_role',
            target.schema_name,
            target.sequence_name
        );
    END LOOP;
END
$$;

-- Public functions are callable only through the Flask service client.
ALTER FUNCTION public.increment_demerit(integer, integer) SET search_path = '';
ALTER FUNCTION public.decrement_demerit(integer, integer) SET search_path = '';

REVOKE ALL PRIVILEGES
    ON FUNCTION public.increment_demerit(integer, integer)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL PRIVILEGES
    ON FUNCTION public.decrement_demerit(integer, integer)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL PRIVILEGES
    ON FUNCTION public.claim_monday_seminar_seat(uuid, bigint)
    FROM PUBLIC, anon, authenticated;

GRANT EXECUTE
    ON FUNCTION public.increment_demerit(integer, integer)
    TO service_role;
GRANT EXECUTE
    ON FUNCTION public.decrement_demerit(integer, integer)
    TO service_role;
GRANT EXECUTE
    ON FUNCTION public.claim_monday_seminar_seat(uuid, bigint)
    TO service_role;

-- Secure-by-default privileges for objects created by future migrations.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL PRIVILEGES ON TABLES FROM anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO service_role;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL PRIVILEGES ON SEQUENCES FROM anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO service_role;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO service_role;

COMMIT;
