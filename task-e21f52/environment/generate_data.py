#!/usr/bin/env python3
"""Generate synthetic eye-tracking reading data for the gaze pipeline task.

Uses only random.Random().random() and .randint() which use Mersenne Twister
and are stable across all Python 3.x versions (unlike .gauss() which changed
algorithm in Python 3.12).

"""
import csv
import math
import os
import sys


def generate_data(output_dir):
    os.makedirs(output_dir, exist_ok=True)

    # Use a dedicated Random instance (Mersenne Twister, stable across versions)
    import random
    rng = random.Random(42)

    N_PARTICIPANTS = 8
    N_TEXTS = 6

    # Fixed reading skill scores spanning low to high
    skill_scores = [32.5, 45.1, 52.8, 61.3, 68.7, 75.2, 83.4, 91.0]
    participants = []
    for i in range(N_PARTICIPANTS):
        participants.append({
            'participant_id': f'P{i:03d}',
            'reading_skill_score': skill_scores[i],
            'is_l2_reader': 1 if i >= 6 else 0,
        })

    # Generate text layouts with word AOIs
    texts = []
    all_word_aois = []

    for tid in range(N_TEXTS):
        n_words = 10 + rng.randint(0, 8)   # 10-18 words per text
        difficulty = round(1.0 + tid * 0.8, 2)

        word_aois = []
        x_cursor = 100
        y_cursor = 300

        for wid in range(n_words):
            word_len = rng.randint(3, 10)
            word_width = word_len * 14
            if x_cursor + word_width > 1700:
                x_cursor = 100
                y_cursor += 60

            word = ''.join(chr(ord('a') + rng.randint(0, 25))
                           for _ in range(word_len))
            word_aois.append({
                'text_id': f'T{tid:03d}',
                'word_index': wid,
                'x_min': x_cursor,
                'y_min': y_cursor - 20,
                'x_max': x_cursor + word_width,
                'y_max': y_cursor + 20,
                'word': word,
            })
            x_cursor += word_width + 20

        texts.append({
            'text_id': f'T{tid:03d}',
            'difficulty_level': difficulty,
            'num_words': n_words,
        })
        all_word_aois.extend(word_aois)

    # Generate raw gaze samples at 1000 Hz
    raw_gaze_rows = []

    for p in participants:
        for t in texts:
            pid = p['participant_id']
            tid = t['text_id']
            text_aois = [a for a in all_word_aois if a['text_id'] == tid]
            n_words = len(text_aois)
            skill = p['reading_skill_score']
            difficulty = t['difficulty_level']

            # Reading behaviour governed by skill and difficulty
            base_fix_dur = int(280 - skill * 1.2 + difficulty * 15)
            skip_prob = min(0.30, max(0.02, 0.05 + skill * 0.002 - difficulty * 0.01))
            regress_prob = min(0.15, max(0.02, 0.10 - skill * 0.0005 + difficulty * 0.008))

            timestamp = 0
            current_word = 0

            while current_word < n_words:
                aoi = text_aois[current_word]

                # Skip word? (use rng.random(), NOT rng.gauss())
                if current_word > 0 and rng.random() < skip_prob:
                    current_word += 1
                    continue

                # Generate fixation samples
                fix_cx = (aoi['x_min'] + aoi['x_max']) / 2.0
                fix_cy = (aoi['y_min'] + aoi['y_max']) / 2.0
                # Duration variation: uniform noise instead of gauss
                dur_var = rng.randint(-35, 35)
                fix_dur = max(100, base_fix_dur + dur_var)

                for _ in range(fix_dur):
                    # Uniform noise in [-0.03, +0.03] px — velocity stays
                    # well below 100 px/s threshold (max ~85 px/s worst case)
                    nx = 0.06 * rng.random() - 0.03
                    ny = 0.06 * rng.random() - 0.03
                    pd_val = 3.3 + 0.4 * rng.random()  # pupil 3.3-3.7
                    raw_gaze_rows.append([
                        timestamp,
                        round(fix_cx + nx, 4),
                        round(fix_cy + ny, 4),
                        round(pd_val, 2),
                        pid, tid,
                    ])
                    timestamp += 1

                # Decide next word (forward or regression)
                next_word = current_word + 1
                if current_word > 1 and rng.random() < regress_prob:
                    next_word = rng.randint(0, current_word - 1)

                # Generate saccade samples (velocity clearly above threshold)
                if next_word < n_words:
                    next_aoi = text_aois[next_word]
                    sac_dur = rng.randint(15, 35)
                    start_x, start_y = fix_cx, fix_cy
                    end_x = (next_aoi['x_min'] + next_aoi['x_max']) / 2.0
                    end_y = (next_aoi['y_min'] + next_aoi['y_max']) / 2.0

                    for s in range(sac_dur):
                        # Start interpolation from frac > 0 so first saccade
                        # sample is clearly displaced from fixation position
                        frac = (s + 1) / (sac_dur + 1)
                        sx = start_x + (end_x - start_x) * frac
                        sy = start_y + (end_y - start_y) * frac
                        # Larger noise during saccade
                        snx = 1.0 * rng.random() - 0.5
                        sny = 1.0 * rng.random() - 0.5
                        pd_val = 3.3 + 0.4 * rng.random()
                        raw_gaze_rows.append([
                            timestamp,
                            round(sx + snx, 4),
                            round(sy + sny, 4),
                            round(pd_val, 2),
                            pid, tid,
                        ])
                        timestamp += 1

                # Occasional blink (~3%)
                if rng.random() < 0.03:
                    blink_dur = rng.randint(80, 200)
                    for _ in range(blink_dur):
                        raw_gaze_rows.append([
                            timestamp, 0.0, 0.0, 0.0, pid, tid,
                        ])
                        timestamp += 1

                current_word = next_word

    # ---- Write CSV files ----
    with open(os.path.join(output_dir, 'raw_gaze.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['timestamp_ms', 'x_px', 'y_px', 'pupil_diameter',
                     'participant_id', 'text_id'])
        w.writerows(raw_gaze_rows)

    with open(os.path.join(output_dir, 'word_aois.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=[
            'text_id', 'word_index', 'x_min', 'y_min', 'x_max', 'y_max', 'word'])
        w.writeheader()
        w.writerows(all_word_aois)

    with open(os.path.join(output_dir, 'participants.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=[
            'participant_id', 'reading_skill_score', 'is_l2_reader'])
        w.writeheader()
        w.writerows(participants)

    with open(os.path.join(output_dir, 'stimuli.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=[
            'text_id', 'difficulty_level', 'num_words'])
        w.writeheader()
        w.writerows(texts)

    # Verification
    n_rows = len(raw_gaze_rows)
    n_trials = N_PARTICIPANTS * N_TEXTS
    print(f'Generated {n_rows} gaze samples across {n_trials} trials',
          file=sys.stderr)
    assert n_rows > 10000, f'Too few gaze samples: {n_rows}'

    # Verify CSV readback
    with open(os.path.join(output_dir, 'raw_gaze.csv')) as f:
        reader = csv.DictReader(f)
        verify_rows = list(reader)
    assert len(verify_rows) == n_rows, \
        f'CSV readback mismatch: wrote {n_rows}, read {len(verify_rows)}'

    # Print verification to stdout (captured in Docker build log)
    print(f'OK: {n_rows} gaze rows, {n_trials} trials, '
          f'{len(all_word_aois)} word AOIs')


if __name__ == '__main__':
    generate_data('/app/data')
