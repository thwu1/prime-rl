#!/usr/bin/env python3
"""Generate synthetic acquisition data for conversion rate forensics task."""
import random
import math
import sqlite3
import csv
import os
from datetime import date, timedelta

random.seed(20240315)

BASE_DATE = date(2023, 1, 1)
ANALYSIS_DATE = date(2024, 3, 15)
SIGNUP_DAYS = (date(2024, 3, 1) - BASE_DATE).days  # 425
TOTAL_DAYS = (ANALYSIS_DATE - BASE_DATE).days       # 439

CHANNELS = {
    "organic":     {"c": 0.32, "scale": 45.0, "k": 1.3,  "cost_cents": 0,    "n": 2500},
    "paid_search": {"c": 0.22, "scale": 30.0, "k": 0.85, "cost_cents": 4500, "n": 2000},
    "social":      {"c": 0.12, "scale": 80.0, "k": 1.6,  "cost_cents": 1500, "n": 2500},
    "referral":    {"c": 0.40, "scale": 20.0, "k": 1.0,  "cost_cents": 2500, "n": 1500},
    "email":       {"c": 0.28, "scale": 35.0, "k": 0.75, "cost_cents": 800,  "n": 2200},
}

REGIONS = ["us-east", "us-west", "eu-west", "eu-east", "apac"]

os.makedirs("/app/data", exist_ok=True)

conn = sqlite3.connect("/app/data/acquisition.db")
cur = conn.cursor()

cur.execute("""CREATE TABLE users (
    user_id INTEGER PRIMARY KEY,
    signup_date TEXT NOT NULL,
    channel TEXT NOT NULL,
    region TEXT NOT NULL
)""")

cur.execute("""CREATE TABLE milestone_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    event_date TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
)""")

user_id = 1
for ch_name, params in CHANNELS.items():
    for _ in range(params["n"]):
        signup_day = random.randint(0, SIGNUP_DAYS - 1)
        signup_dt = BASE_DATE + timedelta(days=signup_day)
        obs_window = TOTAL_DAYS - signup_day
        region = REGIONS[random.randint(0, len(REGIONS) - 1)]

        cur.execute("INSERT INTO users VALUES (?,?,?,?)",
                    (user_id, signup_dt.isoformat(), ch_name, region))

        cur.execute(
            "INSERT INTO milestone_events (user_id, event_type, event_date) VALUES (?,?,?)",
            (user_id, "signup", signup_dt.isoformat()))

        if random.random() < 0.7:
            act_dt = signup_dt + timedelta(days=random.randint(1, 3))
            cur.execute(
                "INSERT INTO milestone_events (user_id, event_type, event_date) VALUES (?,?,?)",
                (user_id, "activation", act_dt.isoformat()))

        will_convert = random.random() < params["c"]
        if will_convert:
            u = random.random()
            while u <= 0:
                u = random.random()
            conv_time = params["scale"] * (-math.log(u)) ** (1.0 / params["k"])

            if conv_time <= obs_window:
                conv_day = signup_day + max(1, int(conv_time))
                conv_dt = BASE_DATE + timedelta(days=conv_day)
                cur.execute(
                    "INSERT INTO milestone_events (user_id, event_type, event_date) VALUES (?,?,?)",
                    (user_id, "conversion", conv_dt.isoformat()))

                if random.random() < 0.02:
                    dup_dt = conv_dt + timedelta(days=random.randint(0, 2))
                    cur.execute(
                        "INSERT INTO milestone_events (user_id, event_type, event_date) VALUES (?,?,?)",
                        (user_id, "conversion", dup_dt.isoformat()))

                if random.random() < 0.01:
                    bad_dt = signup_dt - timedelta(days=random.randint(1, 2))
                    cur.execute(
                        "INSERT INTO milestone_events (user_id, event_type, event_date) VALUES (?,?,?)",
                        (user_id, "conversion", bad_dt.isoformat()))

        if ch_name == "referral" and random.random() < 0.3:
            ref_day = signup_day + random.randint(5, 30)
            if ref_day < TOTAL_DAYS:
                ref_dt = BASE_DATE + timedelta(days=ref_day)
                cur.execute(
                    "INSERT INTO milestone_events (user_id, event_type, event_date) VALUES (?,?,?)",
                    (user_id, "referral_sent", ref_dt.isoformat()))

        user_id += 1

with open("/app/data/channel_costs.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["channel", "cost_per_user_cents", "monthly_budget_usd"])
    for ch_name, params in CHANNELS.items():
        budget = 0 if params["cost_cents"] == 0 else random.randint(5000, 50000)
        writer.writerow([ch_name, params["cost_cents"], budget])

cur.execute("""CREATE VIEW dashboard_metrics AS
SELECT
    u.channel,
    COUNT(DISTINCT u.user_id) AS total_users,
    COUNT(DISTINCT CASE WHEN me.event_type = 'conversion' THEN me.user_id END) AS converted_users,
    ROUND(CAST(COUNT(DISTINCT CASE WHEN me.event_type = 'conversion' THEN me.user_id END) AS REAL) /
          COUNT(DISTINCT u.user_id), 4) AS conversion_rate
FROM users u
LEFT JOIN milestone_events me ON u.user_id = me.user_id AND me.event_type = 'conversion'
GROUP BY u.channel
ORDER BY conversion_rate DESC
""")

cur.execute("""CREATE VIEW weekly_cohorts AS
SELECT
    u.channel,
    CAST((julianday(u.signup_date) - julianday('2023-01-01')) / 7 AS INTEGER) AS signup_week,
    COUNT(DISTINCT u.user_id) AS cohort_size,
    COUNT(DISTINCT CASE WHEN me.event_type = 'conversion' THEN me.user_id END) AS conversions,
    ROUND(CAST(COUNT(DISTINCT CASE WHEN me.event_type = 'conversion' THEN me.user_id END) AS REAL) /
          COUNT(DISTINCT u.user_id), 4) AS conversion_rate
FROM users u
LEFT JOIN milestone_events me ON u.user_id = me.user_id AND me.event_type = 'conversion'
GROUP BY u.channel, signup_week
ORDER BY u.channel, signup_week
""")

conn.commit()
conn.close()
print(f"Generated {user_id - 1} users across {len(CHANNELS)} channels")
