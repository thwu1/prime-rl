"""
Optimal Touring - Game Environment

A combinatorial optimization puzzle where a player plans a tour through
tourist sites on a city grid, maximizing total collected value subject to
temporal and spatial constraints.
"""

import random
import json


def generate_instance(seed, num_sites=40):
    """Generate a problem instance with the given random seed."""
    random.seed(seed)
    sites_data = {}
    for site_id in range(1, num_sites + 1):
        beginhour = random.randint(0, 12)
        endhour = random.randint(beginhour + 2, 21)
        sites_data[site_id] = {
            'avenue': random.randint(0, 30),
            'street': random.randint(0, 30),
            'desiredtime': random.randint(5, 50),
            'value': random.randint(1, 200),
            'beginhour': beginhour,
            'endhour': endhour,
        }
    return sites_data


def evaluate_tour(sites_data, tour):
    """
    Evaluate a proposed tour through the sites.

    Validates all constraints and returns the total value collected if the
    tour is feasible.  Returns -1 if any constraint is violated.
    Returns 0 for an empty tour.
    """
    # Normalise keys to int (JSON stores keys as strings)
    sites = {}
    for k, v in sites_data.items():
        sites[int(k)] = v

    if not tour:
        return 0

    # No duplicate visits
    if len(set(tour)) != len(tour):
        return -1

    # All IDs must be valid
    for site_id in tour:
        if site_id not in sites:
            return -1

    total_value = 0
    current_time = None
    prev_site = None

    for site_id in tour:
        site = sites[site_id]

        if current_time is None:
            # First site: tour begins at this site's opening time
            current_time = site['beginhour'] * 60
            if current_time + site['desiredtime'] > site['endhour'] * 60:
                return -1  # cannot complete visit within window
            total_value += site['value']
            current_time += site['desiredtime']
            prev_site = site
            continue

        # Travel time between consecutive sites (Manhattan distance, in minutes)
        travel_time = (abs(site['avenue'] - prev_site['avenue']) +
                       abs(site['street'] - prev_site['street']))
        arrival_time = current_time + travel_time

        # Must not arrive before the site opens
        if arrival_time < site['beginhour'] * 60:
            return -1

        # Must finish the visit before the site closes
        if arrival_time + site['desiredtime'] > site['endhour'] * 60:
            return -1

        current_time = arrival_time + site['desiredtime']
        total_value += site['value']
        prev_site = site

    return total_value


def greedy_solve(sites_data):
    """
    Simple greedy baseline: sort sites by value (descending) and greedily
    append the first feasible site at each step.
    """
    sites = {int(k): v for k, v in sites_data.items()}
    sorted_ids = sorted(sites.keys(), key=lambda s: sites[s]['value'],
                        reverse=True)

    tour = []
    current_time = None
    prev_site = None

    for site_id in sorted_ids:
        site = sites[site_id]
        if current_time is None:
            start = site['beginhour'] * 60
            if start + site['desiredtime'] <= site['endhour'] * 60:
                tour.append(site_id)
                current_time = start + site['desiredtime']
                prev_site = site
        else:
            travel = (abs(site['avenue'] - prev_site['avenue']) +
                      abs(site['street'] - prev_site['street']))
            arrival = current_time + travel
            if (arrival >= site['beginhour'] * 60 and
                    arrival + site['desiredtime'] <= site['endhour'] * 60):
                tour.append(site_id)
                current_time = arrival + site['desiredtime']
                prev_site = site

    return tour
