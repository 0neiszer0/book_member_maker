-- 029: 발제문은 1개 필수 + 선택 1개를 기본 한도로 허용한다.
ALTER TABLE public.topic_submissions
ALTER COLUMN topic_limit SET DEFAULT 2;

-- 과거 회차의 운영진 설정은 보존하고, 현재 접수 회차의 기존 기본값만 2로 올린다.
-- 이후 운영진은 개인별로 1~10 범위에서 다시 조정할 수 있다.
UPDATE public.topic_submissions AS submission
SET topic_limit = 2
FROM public.topic_events AS event
WHERE submission.event_id = event.id
  AND submission.topic_limit = 1
  AND event.is_active = TRUE
  AND event.meeting_date BETWEEN CURRENT_DATE - INTERVAL '7 days' AND CURRENT_DATE + INTERVAL '1 day';
