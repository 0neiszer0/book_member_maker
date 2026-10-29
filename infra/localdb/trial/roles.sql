-- Derived from Supabase self-hosted/v0.8.3 docker/volumes/db/roles.sql.
-- Only fresh synthetic DB credentials; nothing from the production host.
\set pgpass `echo "$POSTGRES_PASSWORD"`
ALTER USER authenticator WITH PASSWORD :'pgpass';
ALTER USER supabase_storage_admin WITH PASSWORD :'pgpass';
