#!/usr/bin/env python3
"""Generate deterministic sales data for star tree index task."""

import csv
import random
import os
import itertools

regions = ['NA', 'EU', 'APAC', 'LATAM', 'MEA']
categories = ['electronics', 'clothing', 'food', 'books', 'sports', 'home', 'toys']
channels = ['web', 'mobile', 'store', 'wholesale']
days = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

region_weights = [0.35, 0.30, 0.20, 0.10, 0.05]
category_weights = [0.25, 0.20, 0.15, 0.15, 0.10, 0.10, 0.05]
channel_weights = [0.40, 0.35, 0.15, 0.10]
day_weights = [0.12, 0.12, 0.13, 0.13, 0.15, 0.18, 0.17]

base_revenue = {
    'electronics': 500, 'clothing': 100, 'food': 30,
    'books': 20, 'sports': 80, 'home': 150, 'toys': 40
}


def make_record(region, category, channel, day):
    rev = max(1.0, random.gauss(base_revenue[category], base_revenue[category] * 0.3))
    qty = max(1, int(random.gauss(5, 2)))
    disc = round(max(0.0, min(0.5, random.gauss(0.1, 0.08))), 4)
    return [region, category, channel, day, round(rev, 2), qty, disc]


def generate_segment(filename, n, seed_offset):
    random.seed(42 + seed_offset)
    records = []

    # Guarantee every dimension combination has at least one record
    for combo in itertools.product(regions, categories, channels, days):
        records.append(make_record(*combo))

    # Fill remaining with weighted random
    while len(records) < n:
        r = random.choices(regions, weights=region_weights, k=1)[0]
        c = random.choices(categories, weights=category_weights, k=1)[0]
        ch = random.choices(channels, weights=channel_weights, k=1)[0]
        d = random.choices(days, weights=day_weights, k=1)[0]
        records.append(make_record(r, c, ch, d))

    random.shuffle(records)

    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['region', 'category', 'channel', 'day_of_week',
                         'revenue', 'quantity', 'discount'])
        writer.writerows(records)


os.makedirs('/app/data', exist_ok=True)
generate_segment('/app/data/sales_data_segment_a.csv', 25000, 0)
generate_segment('/app/data/sales_data_segment_b.csv', 25000, 1000)
print(f"Generated 2 segments of 25000 records each in /app/data/")
