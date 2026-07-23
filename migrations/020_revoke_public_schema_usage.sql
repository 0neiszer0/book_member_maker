-- PostgreSQL grants USAGE on the public schema through the PUBLIC pseudo-role.
-- Revoke that inherited access as well as the direct API-role grants.

BEGIN;

REVOKE ALL PRIVILEGES ON SCHEMA public FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA public TO service_role;

COMMIT;
