-- Create scrape_detail table for storing MEDIUM_DETAIL and SCHEDULE URLs
-- discovered during crawl, for later processing (merge, team count verification).
CREATE TABLE scrape_detail (
    detail_id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    scrape_id UUID REFERENCES scrape_queue(scrape_id),
    url TEXT NOT NULL,
    page_type TEXT NOT NULL,
    parent_url TEXT,
    yaml_content TEXT,
    full_text TEXT,
    status TEXT DEFAULT 'PENDING',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_scrape_detail_scrape_id ON scrape_detail(scrape_id);
CREATE INDEX idx_scrape_detail_status ON scrape_detail(status);
