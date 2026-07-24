BEGIN;

-- Split future uploads so only book covers can be fetched by Kakao/Notion
-- crawlers; review photos stay private and are never written to Render's disk.
-- The transitional engagement-images bucket is retained to avoid any
-- destructive storage operation during deployment.
INSERT INTO storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
VALUES
    ('book-covers', 'book-covers', true, 1048576, ARRAY['image/webp']),
    ('engagement-photos', 'engagement-photos', false, 1048576, ARRAY['image/webp'])
ON CONFLICT (id) DO UPDATE
SET public = EXCLUDED.public,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;

COMMIT;
