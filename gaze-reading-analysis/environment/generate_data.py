#!/usr/bin/env python3
"""Generate synthetic gaze-during-reading data for the analysis task."""

import csv
import math
import os
import random

random.seed(42)

PASSAGES = {
    'P1': [
        'The', 'quick', 'brown', 'fox', 'jumped',
        'over', 'the', 'lazy', 'sleeping', 'dog',
        'while', 'birds', 'sang', 'their', 'morning',
        'songs', 'from', 'tall', 'ancient', 'trees',
    ],
    'P2': [
        'Modern', 'science', 'reveals', 'complex', 'patterns',
        'hidden', 'within', 'natural', 'biological', 'systems',
        'where', 'tiny', 'changes', 'produce', 'massive',
        'effects', 'across', 'entire', 'living', 'networks',
    ],
}


def create_aois():
    """Create word AOIs arranged in two lines of 10 words each."""
    aois = {}
    for pid, words in PASSAGES.items():
        aois[pid] = []
        x = 1.0
        y = 2.0
        for i, word in enumerate(words):
            if i == 10:
                x = 1.0
                y = 4.0
            word_width = len(word) * 0.35
            aois[pid].append({
                'passage_id': pid,
                'word_idx': i,
                'word_text': word,
                'x_min': round(x, 4),
                'y_min': round(y - 0.3, 4),
                'x_max': round(x + word_width, 4),
                'y_max': round(y + 0.3, 4),
            })
            x += word_width + 0.6
    return aois


def generate_scanpath(aois, skill):
    """Generate a reading scanpath (list of fixation events) for a reader."""
    params = {
        'high': {'skip_p': 0.20, 'reg_p': 0.05, 'dur_mean': 190,
                 'dur_std': 30, 'refix_p': 0.05},
        'medium': {'skip_p': 0.10, 'reg_p': 0.10, 'dur_mean': 240,
                   'dur_std': 40, 'refix_p': 0.10},
        'low': {'skip_p': 0.05, 'reg_p': 0.20, 'dur_mean': 300,
                'dur_std': 50, 'refix_p': 0.15},
    }[skill]

    events = []
    n_words = len(aois)
    current = 0

    while current < n_words:
        word_text = aois[current]['word_text']
        is_short = len(word_text) <= 3
        sp = params['skip_p'] * (2.0 if is_short else 0.5)

        if random.random() < sp and 0 < current < n_words - 1:
            current += 1
            continue

        word_len_factor = 1.0 + (len(word_text) - 4) * 0.05
        dur = int(random.gauss(params['dur_mean'] * word_len_factor,
                               params['dur_std']))
        dur = max(100, min(600, dur))
        events.append({'word_idx': current, 'duration_ms': dur})

        if random.random() < params['refix_p']:
            rd = int(random.gauss(params['dur_mean'] * 0.7,
                                  params['dur_std'] * 0.5))
            events.append({'word_idx': current,
                           'duration_ms': max(80, min(400, rd))})

        if random.random() < params['reg_p'] and current > 2:
            rt = random.randint(max(0, current - 4), current - 1)
            rd = int(random.gauss(params['dur_mean'] * 0.8, params['dur_std']))
            events.append({'word_idx': rt,
                           'duration_ms': max(100, min(500, rd))})

        current += 1

    return events


def scanpath_to_gaze(events, aois):
    """Convert a scanpath to raw gaze position samples at 1000 Hz."""
    samples = []
    t = 0

    for i, ev in enumerate(events):
        w = min(ev['word_idx'], len(aois) - 1)
        aoi = aois[w]
        cx = (aoi['x_min'] + aoi['x_max']) / 2 + random.gauss(0, 0.04)
        cy = (aoi['y_min'] + aoi['y_max']) / 2 + random.gauss(0, 0.02)

        # Generate saccade to this fixation location
        if i > 0:
            px, py = samples[-1][1], samples[-1][2]
            if not (math.isnan(px) or math.isnan(py)):
                dist = math.sqrt((cx - px) ** 2 + (cy - py) ** 2)
            else:
                # Find last non-NaN sample
                dist = 3.0  # default
                for back in range(len(samples) - 1, -1, -1):
                    if not math.isnan(samples[back][1]):
                        px, py = samples[back][1], samples[back][2]
                        dist = math.sqrt((cx - px) ** 2 + (cy - py) ** 2)
                        break
            sdur = max(20, int(dist * 2 + random.gauss(10, 3)))
            for s in range(sdur):
                frac = 0.5 * (1 - math.cos(math.pi * s / sdur))
                sx = px + (cx - px) * frac + random.gauss(0, 0.1)
                sy = py + (cy - py) * frac + random.gauss(0, 0.04)
                samples.append((t, round(sx, 6), round(sy, 6)))
                t += 1

        # Generate fixation samples (low noise for clean fixation detection)
        for _ in range(ev['duration_ms']):
            fx = cx + random.gauss(0, 0.008)
            fy = cy + random.gauss(0, 0.008)
            samples.append((t, round(fx, 6), round(fy, 6)))
            t += 1

    # Add blinks (NaN gaps)
    total = len(samples)
    n_blinks = random.randint(1, 2)
    for _ in range(n_blinks):
        bs = random.randint(int(total * 0.2), int(total * 0.8))
        bd = random.randint(100, 250)
        for b in range(bs, min(bs + bd, total)):
            samples[b] = (samples[b][0], float('nan'), float('nan'))

    return samples


def main():
    aois = create_aois()

    os.makedirs('/app/data/gaze', exist_ok=True)

    # Save AOIs
    with open('/app/data/aois.csv', 'w', newline='') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=['passage_id', 'word_idx', 'word_text',
                        'x_min', 'y_min', 'x_max', 'y_max'],
        )
        writer.writeheader()
        for pid in sorted(aois):
            for a in aois[pid]:
                writer.writerow(a)

    # Generate gaze data for each reader-passage pair
    readers = {'R01': 'high', 'R02': 'medium', 'R03': 'low'}

    for rid, skill in readers.items():
        for pid in sorted(PASSAGES):
            sp = generate_scanpath(aois[pid], skill)
            samples = scanpath_to_gaze(sp, aois[pid])

            with open(f'/app/data/gaze/{rid}_{pid}.csv', 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp_ms', 'x_deg', 'y_deg'])
                for s in samples:
                    if math.isnan(s[1]):
                        writer.writerow([s[0], 'NaN', 'NaN'])
                    else:
                        writer.writerow(s)

    print('Data generation complete.')


if __name__ == '__main__':
    main()
