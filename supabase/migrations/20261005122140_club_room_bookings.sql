-- One room; public visitors only use the Flask API, never these tables directly.
create table public.club_room_bookings (
    id uuid primary key,
    kind text not null check (kind in ('regular', 'meeting')),
    starts_at timestamptz not null,
    ends_at timestamptz not null,
    representative text not null check (length(btrim(representative)) between 1 and 80),
    participants text[] not null check (cardinality(participants) between 1 and 200),
    purpose text not null default '' check (length(purpose) <= 1000),
    edit_digest text not null check (edit_digest ~ '^[0-9a-f]{64}$'),
    request_fingerprint text not null,
    created_by bigint references public.members(id) on delete set null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    cancelled_at timestamptz,
    version integer not null default 1,
    check (ends_at > starts_at),
    check (extract(minute from starts_at at time zone 'Asia/Seoul') = 0
       and extract(second from starts_at at time zone 'Asia/Seoul') = 0
       and extract(minute from ends_at at time zone 'Asia/Seoul') = 0
       and extract(second from ends_at at time zone 'Asia/Seoul') = 0)
);
create index club_room_schedule_idx on public.club_room_bookings(starts_at, ends_at) where cancelled_at is null;
create index club_room_rate_idx on public.club_room_bookings(request_fingerprint, created_at);

create table public.club_room_booking_audit (
    id bigint generated always as identity primary key,
    booking_id uuid not null references public.club_room_bookings(id),
    action text not null,
    actor_id bigint references public.members(id) on delete set null,
    changed_at timestamptz not null default now(),
    before_data jsonb,
    after_data jsonb not null
);
alter table public.club_room_bookings enable row level security;
alter table public.club_room_booking_audit enable row level security;
revoke all on public.club_room_bookings, public.club_room_booking_audit from public, anon, authenticated;
grant select, insert, update on public.club_room_bookings to service_role;
grant select, insert on public.club_room_booking_audit to service_role;
grant usage, select on sequence public.club_room_booking_audit_id_seq to service_role;

-- Every create/update/cancel goes through one transaction. A meeting may coexist
-- with existing bookings, but any later new/moved regular booking is rejected.
create function public.club_room_mutate(
    p_action text, p_id uuid, p_payload jsonb, p_digest text,
    p_actor bigint, p_fingerprint text, p_ack boolean, p_version integer
) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare
    old_row public.club_room_bookings%rowtype;
    saved public.club_room_bookings%rowtype;
    is_staff boolean := false;
    new_start timestamptz;
    new_end timestamptz;
    new_kind text;
    names text[];
    conflicts jsonb;
    schedule_changed boolean;
begin
    -- ponytail: one room, one transaction lock; split by room if more rooms are added.
    perform pg_catalog.pg_advisory_xact_lock(7215042026);
    if p_actor is not null then
        select exists(select 1 from public.members where id = p_actor
            and role in ('admin', 'officer') and is_active is not false
            and account_status = 'active' and member_status is distinct from 'inactive') into is_staff;
        if not is_staff then return jsonb_build_object('status', 'forbidden'); end if;
    end if;
    if p_action not in ('create', 'update', 'cancel') then
        return jsonb_build_object('status', 'invalid');
    end if;
    select * into old_row from public.club_room_bookings where id = p_id;
    if old_row.id is not null then
        if (old_row.kind = 'meeting' and not is_staff)
           or (not is_staff and old_row.edit_digest is distinct from p_digest) then
            return jsonb_build_object('status', 'forbidden');
        end if;
        -- Retrying a lost response must not create a second reservation.
        if p_action = 'create' then
            if old_row.edit_digest is distinct from p_digest then
                return jsonb_build_object('status', 'forbidden');
            end if;
            return jsonb_build_object('status', 'success', 'booking', to_jsonb(old_row) - 'edit_digest' - 'request_fingerprint');
        end if;
        if old_row.cancelled_at is not null then
            if p_action = 'cancel' then
                return jsonb_build_object('status', 'success', 'booking', to_jsonb(old_row) - 'edit_digest' - 'request_fingerprint');
            end if;
            return jsonb_build_object('status', 'cancelled');
        end if;
        if old_row.version is distinct from p_version then return jsonb_build_object('status', 'stale'); end if;
    elsif p_action <> 'create' then
        return jsonb_build_object('status', 'forbidden');
    end if;

    if p_action = 'cancel' then
        update public.club_room_bookings set cancelled_at = now(), updated_at = now(), version = version + 1
            where id = p_id returning * into saved;
    else
        new_start := (p_payload->>'starts_at')::timestamptz;
        new_end := (p_payload->>'ends_at')::timestamptz;
        new_kind := p_payload->>'kind';
        if new_kind is null or new_kind not in ('regular', 'meeting')
           or new_start is null or new_end is null or new_end <= new_start
           or date_trunc('hour', new_start) <> new_start or date_trunc('hour', new_end) <> new_end
           or (old_row.id is not null and old_row.kind <> new_kind) then
            return jsonb_build_object('status', 'invalid');
        end if;
        if new_kind = 'meeting' and not is_staff then return jsonb_build_object('status', 'forbidden'); end if;
        schedule_changed := old_row.id is null or old_row.starts_at <> new_start or old_row.ends_at <> new_end;
        if new_end <= now() or (schedule_changed and new_start < date_trunc('hour', now())) then
            return jsonb_build_object('status', 'past');
        end if;
        names := array(select jsonb_array_elements_text(p_payload->'participants'));
        if cardinality(names) not between 1 and 200
           or exists(select 1 from unnest(names) n where length(btrim(n)) not between 1 and 80)
           or not ((p_payload->>'representative') = any(names)) then
            return jsonb_build_object('status', 'invalid');
        end if;
        if not is_staff and p_action = 'create' and (
            select count(*) from public.club_room_bookings
            where request_fingerprint = p_fingerprint and created_at > now() - interval '10 minutes'
        ) >= 20 then return jsonb_build_object('status', 'rate_limited'); end if;

        if schedule_changed then
            if new_kind = 'regular' and exists(select 1 from public.club_room_bookings
                where id <> p_id and cancelled_at is null and kind = 'meeting'
                  and starts_at < new_end and ends_at > new_start) then
                return jsonb_build_object('status', 'blocked');
            end if;
            select jsonb_agg(jsonb_build_object('starts_at', starts_at, 'ends_at', ends_at,
                'representative', representative, 'kind', kind) order by starts_at) into conflicts
                from public.club_room_bookings where id <> p_id and cancelled_at is null
                  and starts_at < new_end and ends_at > new_start;
            if conflicts is not null and p_ack is not true then
                return jsonb_build_object('status', 'overlap', 'conflicts', conflicts);
            end if;
        end if;
        if p_action = 'create' then
            insert into public.club_room_bookings(id, kind, starts_at, ends_at, representative,
                participants, purpose, edit_digest, request_fingerprint, created_by)
            values(p_id, new_kind, new_start, new_end, p_payload->>'representative', names,
                coalesce(p_payload->>'purpose', ''), p_digest, p_fingerprint, p_actor) returning * into saved;
        else
            update public.club_room_bookings set starts_at = new_start, ends_at = new_end,
                representative = p_payload->>'representative', participants = names,
                purpose = coalesce(p_payload->>'purpose', ''), updated_at = now(), version = version + 1
                where id = p_id returning * into saved;
        end if;
    end if;
    insert into public.club_room_booking_audit(booking_id, action, actor_id, before_data, after_data)
        values(p_id, p_action, p_actor,
            case when old_row.id is not null then to_jsonb(old_row) - 'edit_digest' - 'request_fingerprint' end,
            to_jsonb(saved) - 'edit_digest' - 'request_fingerprint');
    return jsonb_build_object('status', 'success', 'booking', to_jsonb(saved) - 'edit_digest' - 'request_fingerprint');
end;
$$;
revoke all on function public.club_room_mutate(text, uuid, jsonb, text, bigint, text, boolean, integer) from public, anon, authenticated;
grant execute on function public.club_room_mutate(text, uuid, jsonb, text, bigint, text, boolean, integer) to service_role;
