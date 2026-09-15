#!/usr/bin/env python3
"""Generate analytics database for HTTP-serving optimization task."""

import sqlite3
import random
import hashlib
import json
import os

SEED = 42
random.seed(SEED)

DB_PATH = '/app/analytics.db'


def generate():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.executescript('''
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            plan_type TEXT NOT NULL,
            company TEXT,
            country TEXT NOT NULL
        );

        CREATE TABLE pages (
            id INTEGER PRIMARY KEY,
            url TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            word_count INTEGER,
            published_at INTEGER NOT NULL
        );

        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            event_type TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            page_url TEXT NOT NULL,
            referrer TEXT,
            device_type TEXT NOT NULL,
            country TEXT NOT NULL,
            duration_ms INTEGER,
            revenue_cents INTEGER DEFAULT 0,
            metadata TEXT
        );
    ''')

    # --- Generate users ---
    plans = ['free', 'basic', 'pro', 'enterprise']
    countries = [
        'US', 'GB', 'DE', 'FR', 'JP', 'CA', 'AU', 'BR', 'IN', 'KR',
        'MX', 'IT', 'ES', 'NL', 'SE', 'NO', 'FI', 'DK', 'PL', 'CZ',
    ]
    companies = [
        'Acme Corp', 'Globex', 'Initech', 'Umbrella', 'Cyberdyne',
        'Weyland', 'Soylent', 'Stark Industries', 'Wayne Enterprises',
        'Oscorp', None, None, None,
    ]
    base_time = 1696118400  # Oct 1, 2023

    users = []
    for i in range(5000):
        created = base_time + random.randint(0, 5000000)
        plan = random.choices(plans, weights=[50, 25, 15, 10])[0]
        country = random.choice(countries)
        company = random.choice(companies)
        email = f"user{i}@example.com"
        users.append((i + 1, email, created, plan, company, country))
    cur.executemany('INSERT INTO users VALUES (?,?,?,?,?,?)', users)

    # --- Generate pages ---
    page_titles = {
        'blog': [
            'Getting Started with Analytics', 'Advanced Dashboard Guide',
            'Understanding User Behavior', 'Optimizing Conversion Funnels',
            'AB Testing Best Practices', 'Data-Driven Decision Making',
            'Tracking Mobile Users', 'Real-time Analytics Overview',
            'Privacy-First Analytics', 'Custom Event Tracking Guide',
            'Building Reports That Matter', 'Cohort Analysis Explained',
            'Attribution Modeling Deep Dive', 'Session Recording Tips',
            'Heatmap Analysis Tutorial',
        ],
        'docs': [
            'API Reference Overview', 'JavaScript SDK Documentation',
            'Python SDK Getting Started', 'REST API Authentication',
            'Webhook Configuration Guide', 'Data Export Documentation',
            'Custom Dimensions Setup', 'Goal Tracking Configuration',
            'Ecommerce Tracking Setup', 'Cross-Domain Tracking Guide',
            'Server-Side Integration', 'Mobile SDK Reference',
            'Data Retention Policies', 'GDPR Compliance Guide',
            'Rate Limiting Documentation',
        ],
        'product': [
            'Analytics Dashboard', 'Real-time Monitor', 'Funnel Builder',
            'Cohort Explorer', 'User Profiles', 'Custom Reports',
            'AB Testing Platform', 'Heatmaps Tool', 'Session Recordings',
            'Feature Flags',
        ],
        'marketing': [
            'Enterprise Analytics Solution', 'Pricing Plans',
            'Customer Success Stories', 'Compare Analytics Platforms',
            'Security and Compliance', 'About Our Company',
            'Contact Sales Team', 'Partner Program',
            'Careers at Analytics Co', 'Press and Media Kit',
        ],
    }

    pages = []
    page_id = 1
    all_urls = []
    for cat, titles in page_titles.items():
        for title in titles:
            slug = title.lower().replace(' ', '-').replace("'", '')
            url = f"/{cat}/{slug}"
            word_count = random.randint(200, 5000)
            published = base_time - random.randint(0, 10000000)
            pages.append((page_id, url, title, cat, word_count, published))
            all_urls.append(url)
            page_id += 1
    cur.executemany('INSERT INTO pages VALUES (?,?,?,?,?,?)', pages)

    # --- Generate events from sessions ---
    event_types = ['pageview', 'click', 'scroll', 'purchase', 'signup']
    devices = ['desktop', 'mobile', 'tablet']
    referrers = [
        'https://google.com', 'https://bing.com', 'https://twitter.com',
        'https://facebook.com', 'https://linkedin.com', 'https://reddit.com',
        'https://hackernews.com', 'https://producthunt.com',
        None, None, None, None, None,
    ]
    browsers = ['Chrome', 'Firefox', 'Safari', 'Edge']
    oses = ['Windows', 'macOS', 'Linux', 'iOS', 'Android']
    widths = [1920, 1440, 1366, 375, 768]

    events = []
    event_id = 1
    session_weights = [30, 20, 15, 10, 8, 5, 4, 3, 2, 1, 0.5, 0.3, 0.2, 0.1, 0.05]

    for _ in range(50000):
        user_id = random.randint(1, 5000)
        session_id = hashlib.md5(
            f"{user_id}-{random.random()}".encode()
        ).hexdigest()[:16]
        device = random.choices(devices, weights=[50, 40, 10])[0]
        country = random.choice(countries)
        referrer = random.choice(referrers)
        session_start = base_time + random.randint(0, 6000000)
        n_events = random.choices(range(1, 16), weights=session_weights)[0]

        for j in range(n_events):
            if j == 0:
                etype = 'pageview'
            else:
                etype = random.choices(
                    event_types, weights=[60, 20, 10, 5, 5]
                )[0]
            ts = session_start + j * random.randint(5, 300)
            page_url = random.choice(all_urls)
            duration = random.randint(100, 120000) if etype == 'pageview' else None
            revenue = random.randint(500, 50000) if etype == 'purchase' else 0
            metadata = json.dumps({
                'browser': random.choice(browsers),
                'os': random.choice(oses),
                'screen_width': random.choice(widths),
            })
            events.append((
                event_id, etype, ts, user_id, session_id, page_url,
                referrer, device, country, duration, revenue, metadata,
            ))
            event_id += 1

    batch_size = 10000
    for i in range(0, len(events), batch_size):
        cur.executemany(
            'INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            events[i:i + batch_size],
        )
    conn.commit()

    # --- Add deliberately suboptimal indexes ---
    # These are the kind of naive indexes a developer might create,
    # but they don't provide covering-index access for the analytical queries.
    cur.executescript('''
        CREATE INDEX idx_events_type ON events(event_type);
        CREATE INDEX idx_events_timestamp ON events(timestamp);
        CREATE INDEX idx_events_user ON events(user_id);
    ''')
    conn.commit()

    # Print stats
    for tbl in ['events', 'users', 'pages']:
        cur.execute(f'SELECT COUNT(*) FROM {tbl}')
        print(f"{tbl}: {cur.fetchone()[0]} rows")
    conn.close()
    size_mb = os.path.getsize(DB_PATH) / 1024 / 1024
    print(f"Database size: {size_mb:.1f} MB")


if __name__ == '__main__':
    generate()
