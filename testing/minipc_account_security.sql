-- Synthetic fixtures only, run in a disposable PostgreSQL database.
insert into public.members(id,name,student_id,role,is_active,member_status,account_status,social_id) values
 (1,'admin','1001','admin',true,'active','active','fake-admin'),
 (2,'officer','1002','officer',true,'active','active','fake-officer'),
 (3,'member','1003','member',true,'active','active',null),
 (4,'admin-two','1004','admin',true,'active','active',null),
 (5,'member-two','1005','member',true,'active','active',null);
do $$
declare r jsonb; nid bigint; original jsonb;
begin
 select to_jsonb(m) into original from public.members m where id=3;
 r := public.account_request_mutate('request',null,null,'member','1003','fake-new');
 assert (r->>'accepted')::boolean, 'request accepted';
 assert original=(select to_jsonb(m) from public.members m where id=3), 'request must not mutate member';
 r := public.account_request_mutate('request',null,null,'member','1003','fake-new');
 assert (select count(*) from public.notifications where related_member_id=3)=1, 'duplicate reused';
 r := public.account_request_mutate('request',null,null,'member','1003','fake-other');
 assert not (r->>'accepted')::boolean, 'competing request rejected';
 select id into nid from public.notifications where related_member_id=3;
 r := public.account_request_mutate('deny',2,nid);
 assert (r->>'accepted')::boolean, 'denial accepted';
 assert original=(select to_jsonb(m) from public.members m where id=3), 'denial must not mutate member';
 r := public.account_request_mutate('request',null,null,'member','1003','fake-new');
 select id into nid from public.notifications where related_member_id=3 and status='pending';
 r := public.account_request_mutate('approve',2,nid);
 assert (r->>'accepted')::boolean, 'officer approves ordinary member';
 assert (select social_id='fake-new' and role='member' from public.members where id=3), 'only requested identity linked';
 r := public.account_request_mutate('approve',2,nid);
 assert not (r->>'accepted')::boolean, 'repeat approval rejected';
 r := public.account_request_mutate('request',null,null,'admin-two','1004','fake-admin-two');
 select id into nid from public.notifications where related_member_id=4 and status='pending';
 r := public.account_request_mutate('approve',2,nid);
 assert not (r->>'accepted')::boolean, 'officer cannot approve admin';
 r := public.account_request_mutate('approve',1,nid);
 assert (r->>'accepted')::boolean, 'admin can approve admin';
 r := public.account_request_mutate('request',null,null,'member-two','1005','fake-block');
 select id into nid from public.notifications where related_member_id=5 and status='pending';
 update public.members set is_active=false where id=5;
 r := public.account_request_mutate('approve',1,nid);
 assert not (r->>'accepted')::boolean, 'disabled member cannot be reactivated';
 update public.members set is_active=true where id=5;
 update public.notifications set details=details-'pending_social_id' where id=nid;
 r := public.account_request_mutate('deny',1,nid);
 assert not (r->>'accepted')::boolean, 'legacy request requires manual review';
 insert into public.notifications(type,related_member_id) values('new_user_request',1) returning id into nid;
 r := public.account_request_mutate('deny',1,nid);
 assert not (r->>'accepted')::boolean, 'old signup cannot delete admin';
 r := public.protected_member_mutate(2,1,'delete');
 assert not (r->>'accepted')::boolean, 'cannot delete admin';
 r := public.protected_member_mutate(1,1,'status','{"member_status":"dormant"}');
 assert not (r->>'accepted')::boolean, 'cannot disable self via dormant';
 r := public.protected_member_mutate(2,1,'edit','{"role":"member"}');
 assert not (r->>'accepted')::boolean, 'officer cannot demote admin';
 r := public.protected_member_mutate(2,3,'edit','{"role":"admin"}');
 assert not (r->>'accepted')::boolean, 'officer cannot promote admin';
 r := public.protected_member_mutate(1,4,'status','{"member_status":"inactive"}');
 assert (r->>'accepted')::boolean, 'other admin can be disabled with one remaining';
 r := public.protected_member_mutate(4,1,'status','{"member_status":"inactive"}');
 assert not (r->>'accepted')::boolean, 'stale disabled admin cannot remove remaining admin';
 r := public.protected_member_mutate(2,3,'status','{"member_status":"dormant"}');
 assert (r->>'accepted')::boolean, 'ordinary officer management preserved';
 assert not has_function_privilege('anon','public.account_request_mutate(text,bigint,bigint,text,text,text)','execute');
 assert not has_function_privilege('authenticated','public.protected_member_mutate(bigint,bigint,text,jsonb)','execute');
 assert has_function_privilege('service_role','public.account_request_mutate(text,bigint,bigint,text,text,text)','execute');
end $$;
