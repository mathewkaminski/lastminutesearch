-- migrations/009_normalize_page_snapshots_domain.sql
-- Normalize existing page_snapshots.domain to strip www. and subdomains

UPDATE page_snapshots
SET domain = LOWER(
  CASE
    WHEN (regexp_match(
      CASE
        WHEN domain LIKE 'www.%' THEN substring(domain from 5)
        ELSE domain
      END,
      '([^.]+\.[^.]+)$'
    ))[1] IS NOT NULL
    THEN (regexp_match(
      CASE
        WHEN domain LIKE 'www.%' THEN substring(domain from 5)
        ELSE domain
      END,
      '([^.]+\.[^.]+)$'
    ))[1]
    ELSE CASE
      WHEN domain LIKE 'www.%' THEN substring(domain from 5)
      ELSE domain
    END
  END
)
WHERE domain LIKE 'www.%'
   OR domain != LOWER(domain);
