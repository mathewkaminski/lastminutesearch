-- migrations/008_add_base_domain_to_discovered_links.sql
-- Add base_domain column to discovered_links for consistent domain grouping

ALTER TABLE public.discovered_links
  ADD COLUMN IF NOT EXISTS base_domain TEXT;

-- Backfill from source_url
UPDATE discovered_links
SET base_domain = LOWER(
  CASE
    WHEN (regexp_match(
      CASE
        WHEN substring(source_url from '://([^/:]+)') LIKE 'www.%'
        THEN substring(substring(source_url from '://([^/:]+)') from 5)
        ELSE substring(source_url from '://([^/:]+)')
      END,
      '([^.]+\.[^.]+)$'
    ))[1] IS NOT NULL
    THEN (regexp_match(
      CASE
        WHEN substring(source_url from '://([^/:]+)') LIKE 'www.%'
        THEN substring(substring(source_url from '://([^/:]+)') from 5)
        ELSE substring(source_url from '://([^/:]+)')
      END,
      '([^.]+\.[^.]+)$'
    ))[1]
    ELSE CASE
      WHEN substring(source_url from '://([^/:]+)') LIKE 'www.%'
      THEN substring(substring(source_url from '://([^/:]+)') from 5)
      ELSE substring(source_url from '://([^/:]+)')
    END
  END
);

CREATE INDEX IF NOT EXISTS idx_discovered_links_base_domain ON discovered_links(base_domain);
