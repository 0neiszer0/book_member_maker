-- Reverts 20261101010000_local_password_login. Refuses while any member already
-- uses ID/password login, so real accounts are never dropped by accident.
begin;
set local lock_timeout = '5s';
do $$
begin
  if exists (select 1 from public.member_credentials) then
    raise exception 'member_credentials has rows; delete test accounts or convert back before rolling back';
  end if;
end $$;
drop table public.auth_failures;
drop table public.account_setup_tokens;
drop table public.signup_codes;
drop table public.member_credentials;
alter table public.members drop constraint members_auth_provider_check;
alter table public.members drop column auth_session_version, drop column auth_provider;
commit;
