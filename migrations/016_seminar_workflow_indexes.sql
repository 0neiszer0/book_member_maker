-- 016_seminar_workflow_indexes.sql
-- 통합 운영 화면에서 자주 조회하는 회원/기록 참조를 보강한다.

BEGIN;

CREATE INDEX IF NOT EXISTS seminar_absences_recorded_by_idx
    ON public.seminar_absences(recorded_by)
    WHERE recorded_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS seminar_absences_cancelled_by_idx
    ON public.seminar_absences(cancelled_by)
    WHERE cancelled_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS seminar_votes_member_idx
    ON public.seminar_votes(member_id);

COMMIT;
