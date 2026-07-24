BEGIN;

-- Retain the transitional bucket without exposing any objects it might contain.
UPDATE storage.buckets
SET public = false
WHERE id = 'engagement-images';

COMMIT;
