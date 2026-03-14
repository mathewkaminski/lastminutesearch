-- migrations/007_add_base_domain_to_scrape_queue.sql
-- Add base_domain column to scrape_queue for consistent domain grouping

ALTER TABLE public.scrape_queue
  ADD COLUMN IF NOT EXISTS base_domain TEXT;

-- Backfill: strip www. and subdomains from url netloc
UPDATE scrape_queue
SET base_domain = LOWER(
  CASE
    WHEN (regexp_match(
      CASE
        WHEN substring(url from '://([^/:]+)') LIKE 'www.%'
        THEN substring(substring(url from '://([^/:]+)') from 5)
        ELSE substring(url from '://([^/:]+)')
      END,
      '([^.]+\.[^.]+)$'
    ))[1] IS NOT NULL
    THEN (regexp_match(
      CASE
        WHEN substring(url from '://([^/:]+)') LIKE 'www.%'
        THEN substring(substring(url from '://([^/:]+)') from 5)
        ELSE substring(url from '://([^/:]+)')
      END,
      '([^.]+\.[^.]+)$'
    ))[1]
    ELSE CASE
      WHEN substring(url from '://([^/:]+)') LIKE 'www.%'
      THEN substring(substring(url from '://([^/:]+)') from 5)
      ELSE substring(url from '://([^/:]+)')
    END
  END
);

CREATE INDEX IF NOT EXISTS idx_scrape_queue_base_domain ON scrape_queue(base_domain);
