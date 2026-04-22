-- Create Supabase Storage bucket for source documents
-- Note: This uses the Supabase storage schema. If running outside Supabase,
-- create the bucket via the dashboard or CLI instead.

INSERT INTO storage.buckets (id, name, public)
VALUES ('sustainability-sources', 'sustainability-sources', true)
ON CONFLICT (id) DO NOTHING;
