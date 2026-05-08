-- 004_improvements.sql
-- Schema/index improvements + bug fix
--
-- 적용 순서대로 Supabase SQL 콘솔에서 실행하세요.
-- 각 섹션은 독립적으로 실행 가능하며, 이미 적용된 항목은 IF NOT EXISTS로 안전하게 스킵됩니다.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1) [BUG FIX] bookclub_co_matrix 중복 정리 + UNIQUE 제약
--
-- 문제: pair_key에 UNIQUE 제약이 없어 app.py의 upsert가 실제로는 INSERT처럼
--       동작 → 같은 페어가 여러 row로 분산되어 만남 횟수 통계가 부정확.
-- 해결: ① 동일 pair_key의 count를 합산해 1개 row로 병합, last_met은 가장 최근값으로
--       ② pair_key에 UNIQUE 제약 추가 → 이후 upsert가 정상 동작
-- ----------------------------------------------------------------------------

-- 백업 (롤백 대비)
CREATE TABLE IF NOT EXISTS bookclub_co_matrix_backup_004 AS
    SELECT * FROM bookclub_co_matrix;

-- 임시 테이블에 병합 결과 저장
CREATE TEMP TABLE _co_matrix_merged AS
SELECT
    (array_agg(id ORDER BY last_met DESC NULLS LAST))[1] AS keep_id,
    pair_key,
    SUM(count)::bigint AS total_count,
    MAX(last_met) AS latest_met
FROM bookclub_co_matrix
GROUP BY pair_key;

-- 살릴 row만 남기고 나머지 삭제
DELETE FROM bookclub_co_matrix
WHERE id NOT IN (SELECT keep_id FROM _co_matrix_merged);

-- 살린 row의 count/last_met을 합산값으로 갱신
UPDATE bookclub_co_matrix bm
SET count = m.total_count,
    last_met = m.latest_met
FROM _co_matrix_merged m
WHERE bm.id = m.keep_id;

-- 이제 안전하게 UNIQUE 제약 추가
ALTER TABLE bookclub_co_matrix
    ADD CONSTRAINT bookclub_co_matrix_pair_key_unique UNIQUE (pair_key);

-- ----------------------------------------------------------------------------
-- 2) members 인덱스 — 자주 eq() 조회되는 컬럼
-- ----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS members_name_idx ON public.members (name);
CREATE INDEX IF NOT EXISTS members_student_id_idx ON public.members (student_id) WHERE student_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS members_social_id_idx ON public.members (social_id) WHERE social_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS members_active_status_idx ON public.members (is_active, account_status);

-- ----------------------------------------------------------------------------
-- 3) notifications 조회 최적화 (관리자 알림 목록)
-- ----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS notifications_status_created_idx
    ON public.notifications (status, created_at DESC);

-- ----------------------------------------------------------------------------
-- 4) topic_events 활성 필터 (공개 페이지에서 is_active=true 조회 빈번)
-- ----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS topic_events_active_date_idx
    ON public.topic_events (is_active, meeting_date DESC);

-- ----------------------------------------------------------------------------
-- 5) attendance 일자별 조회 (월별 통계 등)
--
-- 기존: (user_id, meeting_date) UNIQUE — user_id 선행 쿼리에 효과적
-- 추가: meeting_date 단독 인덱스 — 특정 날짜 전원 조회용
-- ----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS attendance_meeting_date_idx
    ON public.attendance (meeting_date);

-- ----------------------------------------------------------------------------
-- 6) history (세미나 진행 기록) date 인덱스
-- ----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS history_date_idx ON public.history (date DESC);

-- ============================================================================
-- 완료 후 확인:
-- SELECT pair_key, COUNT(*) FROM bookclub_co_matrix GROUP BY pair_key HAVING COUNT(*) > 1;
-- → 결과 0건이어야 정상
-- ============================================================================
