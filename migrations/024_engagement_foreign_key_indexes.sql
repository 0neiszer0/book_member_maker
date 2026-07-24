BEGIN;

CREATE INDEX book_catalog_created_by_idx ON public.book_catalog(created_by);
CREATE INDEX seminar_review_forms_created_by_idx ON public.seminar_review_forms(created_by);
CREATE INDEX brick_projects_coordinator_idx ON public.brick_projects(coordinator_id);
CREATE INDEX brick_recruitments_created_by_idx ON public.brick_recruitments(created_by);
CREATE INDEX brick_project_members_application_idx ON public.brick_project_members(application_id);
CREATE INDEX brick_review_forms_created_by_idx ON public.brick_review_forms(created_by);
CREATE INDEX brick_project_status_changed_by_idx ON public.brick_project_status_history(changed_by);

COMMIT;
