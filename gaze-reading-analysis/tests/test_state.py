"""Tests for the gaze-during-reading analysis pipeline.

Verifies fixation detection, saccade detection, reading measure
computation (including go-past time and landing position),
blink-margin filtering, SQLite database creation, and Makefile
orchestration.
"""

import csv
import math
import os
import sqlite3
import subprocess

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_csv(path):
    """Read a CSV file and return a list of dicts."""
    with open(path) as f:
        return list(csv.DictReader(f))


def run_pipeline(data_dir, output_dir):
    """Run the agent's pipeline on the given data directory."""
    result = subprocess.run(
        ['python3', '/app/analyze.py',
         '--data-dir', data_dir, '--output-dir', output_dir],
        capture_output=True, text=True, cwd='/app', timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f'Pipeline failed (rc={result.returncode}):\n'
            f'STDOUT: {result.stdout}\nSTDERR: {result.stderr}'
        )
    return result


def make_linear_saccade(x_start, y_start, x_end, y_end, n_samples, t_start):
    """Generate samples for a linear saccade."""
    samples = []
    for s in range(n_samples):
        frac = s / n_samples
        x = x_start + (x_end - x_start) * frac
        y = y_start + (y_end - y_start) * frac
        samples.append((t_start + s, f'{x:.6f}', f'{y:.6f}'))
    return samples


def make_fixation(x, y, duration_ms, t_start):
    """Generate samples for a perfectly still fixation."""
    return [(t_start + s, f'{x:.6f}', f'{y:.6f}')
            for s in range(duration_ms)]


def write_gaze_csv(path, samples):
    """Write gaze samples to a CSV file."""
    with open(path, 'w', newline='') as f:
        f.write('timestamp_ms,x_deg,y_deg\n')
        for t, x, y in samples:
            f.write(f'{t},{x},{y}\n')


def write_aois_csv(path, aois):
    """Write AOI definitions to a CSV file."""
    with open(path, 'w', newline='') as f:
        f.write('passage_id,word_idx,word_text,x_min,y_min,x_max,y_max\n')
        for a in aois:
            f.write(f"{a[0]},{a[1]},{a[2]},{a[3]},{a[4]},{a[5]},{a[6]}\n")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def main_output():
    """Run the pipeline on the default data and return parsed output."""
    if not os.path.isfile('/app/output/fixations.csv'):
        subprocess.run(
            ['make', '-C', '/app', 'all'],
            capture_output=True, text=True, timeout=120,
        )

    return {
        'fixations': read_csv('/app/output/fixations.csv'),
        'saccades': read_csv('/app/output/saccades.csv'),
        'measures': read_csv('/app/output/reading_measures.csv'),
    }


# ---------------------------------------------------------------------------
# Tests on the main (provided) data
# ---------------------------------------------------------------------------

class TestOutputFilesExist:
    """Output files should exist and have correct structure."""

    def test_fixations_file_exists(self, main_output):
        assert os.path.isfile('/app/output/fixations.csv')

    def test_saccades_file_exists(self, main_output):
        assert os.path.isfile('/app/output/saccades.csv')

    def test_measures_file_exists(self, main_output):
        assert os.path.isfile('/app/output/reading_measures.csv')


class TestFixationsFormat:
    """Fixations CSV should have correct columns and reasonable values."""

    def test_required_columns(self, main_output):
        rows = main_output['fixations']
        assert len(rows) > 0, 'No fixations detected'
        required = {'trial_id', 'onset_ms', 'offset_ms', 'duration_ms',
                     'x_center', 'y_center', 'word_idx', 'landing_position'}
        actual = set(rows[0].keys())
        for col in required:
            assert col in actual, f'Missing column: {col}'

    def test_minimum_duration(self, main_output):
        for row in main_output['fixations']:
            d = float(row['duration_ms'])
            assert d >= 80, f'Fixation duration {d} < 80ms'

    def test_fixation_count_reasonable(self, main_output):
        n = len(main_output['fixations'])
        assert 40 < n < 300, f'Fixation count {n} seems unreasonable'

    def test_mean_duration_reasonable(self, main_output):
        durations = [float(r['duration_ms'])
                     for r in main_output['fixations']]
        mean_d = sum(durations) / len(durations)
        assert 100 < mean_d < 450, (
            f'Mean fixation duration {mean_d:.1f}ms out of range')

    def test_landing_position_values(self, main_output):
        for row in main_output['fixations']:
            lp = float(row['landing_position'])
            w = int(row['word_idx'])
            if w == -1:
                assert lp == -1, (
                    f'Off-text fixation should have landing_position=-1')
            else:
                assert 0 <= lp <= 1, (
                    f'Landing position {lp} out of [0,1] for word {w}')


class TestSaccadesFormat:
    """Saccades CSV should have correct columns and reasonable values."""

    def test_required_columns(self, main_output):
        rows = main_output['saccades']
        assert len(rows) > 0, 'No saccades detected'
        required = {'trial_id', 'onset_ms', 'offset_ms', 'duration_ms'}
        actual = set(rows[0].keys())
        for col in required:
            assert col in actual, f'Missing column: {col}'

    def test_minimum_duration(self, main_output):
        for row in main_output['saccades']:
            d = float(row['duration_ms'])
            assert d >= 6, f'Saccade duration {d} < 6ms'

    def test_saccade_count_reasonable(self, main_output):
        n = len(main_output['saccades'])
        assert 10 < n < 300, f'Saccade count {n} seems unreasonable'


class TestReadingMeasuresFormat:
    """Reading measures CSV should have correct columns."""

    def test_required_columns(self, main_output):
        rows = main_output['measures']
        assert len(rows) > 0, 'No reading measures'
        required = {'trial_id', 'word_idx', 'first_fixation_duration',
                     'gaze_duration', 'go_past_time', 'total_reading_time',
                     'was_skipped', 'was_regressed_to',
                     'first_fixation_landing'}
        actual = set(rows[0].keys())
        for col in required:
            assert col in actual, f'Missing column: {col}'

    def test_row_count(self, main_output):
        # 6 trials (3 readers x 2 passages) x 20 words = 120 rows
        n = len(main_output['measures'])
        assert n == 120, f'Expected 120 measure rows, got {n}'


class TestReadingMeasuresConsistency:
    """Reading measures should satisfy consistency constraints."""

    def test_ffd_leq_gd_leq_trt(self, main_output):
        for row in main_output['measures']:
            ffd = float(row['first_fixation_duration'])
            gd = float(row['gaze_duration'])
            trt = float(row['total_reading_time'])
            assert ffd >= 0, f'FFD negative: {row}'
            assert gd >= ffd - 0.01, f'GD < FFD: {row}'
            assert trt >= gd - 0.01, f'TRT < GD: {row}'

    def test_gd_leq_gpt(self, main_output):
        """Go-past time must be >= gaze duration for every word."""
        for row in main_output['measures']:
            gd = float(row['gaze_duration'])
            gpt = float(row['go_past_time'])
            assert gpt >= gd - 0.01, (
                f'GPT ({gpt}) < GD ({gd}) for '
                f'{row["trial_id"]} word {row["word_idx"]}')

    def test_skipped_words_have_zero_measures(self, main_output):
        for row in main_output['measures']:
            skipped = int(float(row['was_skipped']))
            if skipped:
                ffd = float(row['first_fixation_duration'])
                gd = float(row['gaze_duration'])
                gpt = float(row['go_past_time'])
                assert ffd == 0, (
                    f'Skipped word has nonzero FFD: {row}')
                assert gd == 0, (
                    f'Skipped word has nonzero GD: {row}')
                assert gpt == 0, (
                    f'Skipped word has nonzero GPT: {row}')

    def test_non_negative_values(self, main_output):
        for row in main_output['measures']:
            for col in ('first_fixation_duration', 'gaze_duration',
                        'go_past_time', 'total_reading_time'):
                assert float(row[col]) >= 0, (
                    f'{col} negative in {row}')

    def test_first_fixation_landing_values(self, main_output):
        for row in main_output['measures']:
            ffl = float(row['first_fixation_landing'])
            skipped = int(float(row['was_skipped']))
            if skipped:
                assert ffl == -1, (
                    f'Skipped word should have ffl=-1, got {ffl}')
            elif ffl >= 0:
                assert 0 <= ffl <= 1, (
                    f'Landing position {ffl} out of [0,1]')


# ---------------------------------------------------------------------------
# SQLite database tests
# ---------------------------------------------------------------------------

class TestSQLiteDatabase:
    """Verify SQLite database structure and content."""

    def test_database_exists(self, main_output):
        assert os.path.isfile('/app/output/gaze.db'), (
            'gaze.db not found in /app/output/')

    def test_fixations_table_populated(self, main_output):
        conn = sqlite3.connect('/app/output/gaze.db')
        cur = conn.execute('SELECT COUNT(*) FROM fixations')
        count = cur.fetchone()[0]
        conn.close()
        assert count > 0, 'fixations table is empty'

    def test_saccades_table_populated(self, main_output):
        conn = sqlite3.connect('/app/output/gaze.db')
        cur = conn.execute('SELECT COUNT(*) FROM saccades')
        count = cur.fetchone()[0]
        conn.close()
        assert count > 0, 'saccades table is empty'

    def test_reading_measures_table_count(self, main_output):
        conn = sqlite3.connect('/app/output/gaze.db')
        cur = conn.execute('SELECT COUNT(*) FROM reading_measures')
        count = cur.fetchone()[0]
        conn.close()
        assert count == 120, f'Expected 120 reading_measures rows, got {count}'

    def test_reader_summary_view(self, main_output):
        conn = sqlite3.connect('/app/output/gaze.db')
        cur = conn.execute(
            'SELECT reader_id, mean_ffd, mean_gd, skip_rate, regression_rate '
            'FROM reader_summary ORDER BY reader_id')
        rows = cur.fetchall()
        conn.close()
        assert len(rows) == 3, f'Expected 3 reader_summary rows, got {len(rows)}'
        reader_ids = [r[0] for r in rows]
        assert set(reader_ids) == {'R01', 'R02', 'R03'}, (
            f'Unexpected reader_ids: {reader_ids}')
        for row in rows:
            assert row[1] is not None and float(row[1]) > 0, (
                f'mean_ffd invalid for {row[0]}')
            assert row[2] is not None and float(row[2]) > 0, (
                f'mean_gd invalid for {row[0]}')
            assert 0 <= float(row[3]) <= 1, (
                f'skip_rate out of range for {row[0]}')
            assert 0 <= float(row[4]) <= 1, (
                f'regression_rate out of range for {row[0]}')

    def test_passage_difficulty_view(self, main_output):
        conn = sqlite3.connect('/app/output/gaze.db')
        cur = conn.execute(
            'SELECT passage_id, mean_trt, mean_skip_rate '
            'FROM passage_difficulty ORDER BY passage_id')
        rows = cur.fetchall()
        conn.close()
        assert len(rows) == 2, f'Expected 2 passage_difficulty rows, got {len(rows)}'
        passage_ids = [r[0] for r in rows]
        assert set(passage_ids) == {'P1', 'P2'}, (
            f'Unexpected passage_ids: {passage_ids}')
        for row in rows:
            assert row[1] is not None and float(row[1]) > 0, (
                f'mean_trt invalid for {row[0]}')
            assert 0 <= float(row[2]) <= 1, (
                f'mean_skip_rate out of range for {row[0]}')

    def test_processing_difficulty_view(self, main_output):
        conn = sqlite3.connect('/app/output/gaze.db')
        cur = conn.execute(
            'SELECT passage_id, word_idx, mean_gpt, regression_cost, '
            'mean_landing FROM processing_difficulty '
            'ORDER BY passage_id, word_idx')
        rows = cur.fetchall()
        conn.close()
        # 2 passages x 20 words = 40 rows
        assert len(rows) == 40, (
            f'Expected 40 processing_difficulty rows, got {len(rows)}')
        passages = set(r[0] for r in rows)
        assert passages == {'P1', 'P2'}
        for row in rows:
            gpt = row[2]
            rc = row[3]
            ml = row[4]
            if gpt is not None:
                assert float(gpt) >= 0, (
                    f'mean_gpt negative: {row}')
            if rc is not None:
                assert float(rc) >= -0.01, (
                    f'regression_cost negative: {row}')
            if ml is not None:
                assert 0 <= float(ml) <= 1, (
                    f'mean_landing out of range: {row}')


# ---------------------------------------------------------------------------
# Known-signal tests
# ---------------------------------------------------------------------------

class TestKnownSignalThreeFixations:
    """Test with a clean 3-fixation signal including a regression.

    Signal: 200ms fixation at (2,2) -> 30ms saccade -> 200ms fixation at (8,2)
            -> 30ms saccade back -> 200ms fixation at (2,2) [regression]
    Expected: 3 fixations, 2 saccades, word 0 regressed to.
    GPT(word 1) should exceed GD(word 1) because the regression to word 0
    happens before the reader advances past word 1.
    """

    @pytest.fixture()
    def known_output(self, tmp_path):
        gaze_dir = tmp_path / 'gaze'
        gaze_dir.mkdir()
        out_dir = tmp_path / 'output'
        out_dir.mkdir()

        samples = []
        t = 0

        samples.extend(make_fixation(2.0, 2.0, 200, t))
        t += 200
        samples.extend(make_linear_saccade(2.0, 2.0, 8.0, 2.0, 30, t))
        t += 30
        samples.extend(make_fixation(8.0, 2.0, 200, t))
        t += 200
        samples.extend(make_linear_saccade(8.0, 2.0, 2.0, 2.0, 30, t))
        t += 30
        samples.extend(make_fixation(2.0, 2.0, 200, t))
        t += 200

        write_gaze_csv(str(gaze_dir / 'T01_K1.csv'), samples)
        write_aois_csv(str(tmp_path / 'aois.csv'), [
            ('K1', 0, 'alpha', 0.0, 1.0, 4.0, 3.0),
            ('K1', 1, 'beta', 6.0, 1.0, 10.0, 3.0),
        ])

        run_pipeline(str(tmp_path), str(out_dir))

        return {
            'fixations': read_csv(str(out_dir / 'fixations.csv')),
            'saccades': read_csv(str(out_dir / 'saccades.csv')),
            'measures': read_csv(str(out_dir / 'reading_measures.csv')),
        }

    def test_fixation_count(self, known_output):
        assert len(known_output['fixations']) == 3, (
            f"Expected 3 fixations, got {len(known_output['fixations'])}")

    def test_saccade_count(self, known_output):
        assert len(known_output['saccades']) == 2, (
            f"Expected 2 saccades, got {len(known_output['saccades'])}")

    def test_fixation_durations(self, known_output):
        durations = sorted(float(f['duration_ms'])
                           for f in known_output['fixations'])
        for d in durations:
            assert 190 <= d <= 210, (
                f'Fixation duration {d} outside expected range')

    def test_word0_reading_measures(self, known_output):
        w0 = [m for m in known_output['measures']
              if int(m['word_idx']) == 0]
        assert len(w0) == 1
        w0 = w0[0]

        ffd = float(w0['first_fixation_duration'])
        gd = float(w0['gaze_duration'])
        gpt = float(w0['go_past_time'])
        trt = float(w0['total_reading_time'])
        regressed = int(float(w0['was_regressed_to']))
        skipped = int(float(w0['was_skipped']))

        assert 190 <= ffd <= 210, f'FFD(0) = {ffd}, expected ~199'
        assert 190 <= gd <= 210, f'GD(0) = {gd}, expected ~199'
        assert 190 <= gpt <= 210, f'GPT(0) = {gpt}, expected ~199'
        assert 385 <= trt <= 410, f'TRT(0) = {trt}, expected ~397'
        assert regressed == 1, 'Word 0 should be regressed to'
        assert skipped == 0, 'Word 0 should not be skipped'

    def test_word1_reading_measures(self, known_output):
        w1 = [m for m in known_output['measures']
              if int(m['word_idx']) == 1]
        assert len(w1) == 1
        w1 = w1[0]

        ffd = float(w1['first_fixation_duration'])
        gd = float(w1['gaze_duration'])
        gpt = float(w1['go_past_time'])
        trt = float(w1['total_reading_time'])
        regressed = int(float(w1['was_regressed_to']))
        skipped = int(float(w1['was_skipped']))

        assert 190 <= ffd <= 210, f'FFD(1) = {ffd}, expected ~198'
        assert 190 <= gd <= 210, f'GD(1) = {gd}, expected ~198'
        # GPT should include the regression fixation on word 0
        assert 385 <= gpt <= 420, f'GPT(1) = {gpt}, expected ~396'
        assert gpt > gd, (
            f'GPT ({gpt}) should exceed GD ({gd}) due to regression')
        assert 190 <= trt <= 210, f'TRT(1) = {trt}, expected ~198'
        assert regressed == 0, 'Word 1 should not be regressed to'
        assert skipped == 0, 'Word 1 should not be skipped'

    def test_landing_positions(self, known_output):
        for fix in known_output['fixations']:
            w = int(fix['word_idx'])
            lp = float(fix['landing_position'])
            if w >= 0:
                assert 0.45 <= lp <= 0.55, (
                    f'Landing position {lp} for word {w}, expected ~0.5')


class TestKnownSignalSkipDetection:
    """Test skip detection: reader fixates word 0 then jumps to word 2,
    skipping word 1.

    Signal: 200ms fixation at (1.5,2) -> 30ms saccade -> 200ms fixation
    at (9.5,2)
    Expected: word 1 is skipped; GPT(word 1) = 0.
    """

    @pytest.fixture()
    def skip_output(self, tmp_path):
        gaze_dir = tmp_path / 'gaze'
        gaze_dir.mkdir()
        out_dir = tmp_path / 'output'
        out_dir.mkdir()

        samples = []
        t = 0

        samples.extend(make_fixation(1.5, 2.0, 200, t))
        t += 200
        samples.extend(make_linear_saccade(1.5, 2.0, 9.5, 2.0, 30, t))
        t += 30
        samples.extend(make_fixation(9.5, 2.0, 200, t))
        t += 200

        write_gaze_csv(str(gaze_dir / 'T01_S1.csv'), samples)

        write_aois_csv(str(tmp_path / 'aois.csv'), [
            ('S1', 0, 'first', 0.0, 1.0, 3.0, 3.0),
            ('S1', 1, 'second', 4.0, 1.0, 7.0, 3.0),
            ('S1', 2, 'third', 8.0, 1.0, 11.0, 3.0),
        ])

        run_pipeline(str(tmp_path), str(out_dir))

        return {
            'fixations': read_csv(str(out_dir / 'fixations.csv')),
            'measures': read_csv(str(out_dir / 'reading_measures.csv')),
        }

    def test_fixation_count(self, skip_output):
        assert len(skip_output['fixations']) == 2

    def test_word1_skipped(self, skip_output):
        w1 = [m for m in skip_output['measures']
              if int(m['word_idx']) == 1]
        assert len(w1) == 1
        w1 = w1[0]

        assert int(float(w1['was_skipped'])) == 1, (
            'Word 1 should be skipped')
        assert float(w1['first_fixation_duration']) == 0
        assert float(w1['gaze_duration']) == 0
        assert float(w1['go_past_time']) == 0
        assert float(w1['total_reading_time']) == 0

    def test_word0_not_skipped(self, skip_output):
        w0 = [m for m in skip_output['measures']
              if int(m['word_idx']) == 0]
        assert len(w0) == 1
        assert int(float(w0[0]['was_skipped'])) == 0
        assert float(w0[0]['first_fixation_duration']) > 0

    def test_word2_not_skipped(self, skip_output):
        w2 = [m for m in skip_output['measures']
              if int(m['word_idx']) == 2]
        assert len(w2) == 1
        assert int(float(w2[0]['was_skipped'])) == 0
        assert float(w2[0]['first_fixation_duration']) > 0


class TestKnownSignalGazeDuration:
    """Test gaze duration with multiple first-pass fixations on the same word.

    Signal: 150ms fix at (2,2) [word 0] -> tiny saccade -> 150ms refix at
    (2.5,2) [still word 0] -> saccade -> 200ms fix at (8,2) [word 1]
    Expected: GD(word 0) = FFD(word 0) + refix duration ~ 300ms.
    GPT(word 0) = GD(word 0) because no regression from word 0.
    """

    @pytest.fixture()
    def gd_output(self, tmp_path):
        gaze_dir = tmp_path / 'gaze'
        gaze_dir.mkdir()
        out_dir = tmp_path / 'output'
        out_dir.mkdir()

        samples = []
        t = 0

        samples.extend(make_fixation(2.0, 2.0, 150, t))
        t += 150

        for s in range(20):
            frac = s / 20
            x = 2.0 + 1.5 * frac
            samples.append((t, f'{x:.6f}', '2.000000'))
            t += 1

        samples.extend(make_fixation(2.5, 2.0, 150, t))
        t += 150
        samples.extend(make_linear_saccade(2.5, 2.0, 8.0, 2.0, 30, t))
        t += 30
        samples.extend(make_fixation(8.0, 2.0, 200, t))
        t += 200

        write_gaze_csv(str(gaze_dir / 'T01_G1.csv'), samples)

        write_aois_csv(str(tmp_path / 'aois.csv'), [
            ('G1', 0, 'alpha', 0.0, 1.0, 4.0, 3.0),
            ('G1', 1, 'beta', 6.0, 1.0, 10.0, 3.0),
        ])

        run_pipeline(str(tmp_path), str(out_dir))

        return {
            'fixations': read_csv(str(out_dir / 'fixations.csv')),
            'measures': read_csv(str(out_dir / 'reading_measures.csv')),
        }

    def test_gd_greater_than_ffd_for_refixated_word(self, gd_output):
        """GD should exceed FFD when a word receives multiple first-pass
        fixations. GPT should equal GD when no regressions occur."""
        w0 = [m for m in gd_output['measures']
              if int(m['word_idx']) == 0]
        assert len(w0) == 1
        w0 = w0[0]

        ffd = float(w0['first_fixation_duration'])
        gd = float(w0['gaze_duration'])
        gpt = float(w0['go_past_time'])
        trt = float(w0['total_reading_time'])

        assert 140 <= ffd <= 160, f'FFD = {ffd}, expected ~149'
        assert gd > ffd, f'GD ({gd}) should exceed FFD ({ffd})'
        assert 280 <= gd <= 320, f'GD = {gd}, expected ~298'

        # GPT should equal GD (no regressions from word 0)
        assert abs(gpt - gd) < 5, (
            f'GPT ({gpt}) should equal GD ({gd}) with no regressions')

        # TRT should equal GD (no regressions)
        assert abs(trt - gd) < 5, f'TRT ({trt}) should equal GD ({gd})'


class TestKnownSignalGoPostTime:
    """Test go-past time with a regression before advancing.

    3 words. Reader: fix word 0 (200ms) -> fix word 1 (200ms) ->
    regress to word 0 (150ms) -> advance to word 2 (200ms).

    Expected:
    - Word 0: GPT = GD (reader advances past word 0 immediately)
    - Word 1: GPT > GD (regression to word 0 occurs before advancing past 1)
    - Word 2: GPT = GD (no regression)
    Also tests landing position variation: word 0 at 0.5, word 1 at 0.25,
    word 2 at 0.75.
    """

    @pytest.fixture()
    def gpt_output(self, tmp_path):
        gaze_dir = tmp_path / 'gaze'
        gaze_dir.mkdir()
        out_dir = tmp_path / 'output'
        out_dir.mkdir()

        samples = []
        t = 0

        # Fix word 0 at (2,2) — AOI [0,4] — landing = 0.5
        samples.extend(make_fixation(2.0, 2.0, 200, t))
        t += 200
        # Saccade to word 1
        samples.extend(make_linear_saccade(2.0, 2.0, 6.0, 2.0, 30, t))
        t += 30
        # Fix word 1 at (6,2) — AOI [5,9] — landing = 0.25
        samples.extend(make_fixation(6.0, 2.0, 200, t))
        t += 200
        # Saccade back to word 0 (regression)
        samples.extend(make_linear_saccade(6.0, 2.0, 2.0, 2.0, 30, t))
        t += 30
        # Regression fixation on word 0
        samples.extend(make_fixation(2.0, 2.0, 150, t))
        t += 150
        # Saccade to word 2
        samples.extend(make_linear_saccade(2.0, 2.0, 13.0, 2.0, 30, t))
        t += 30
        # Fix word 2 at (13,2) — AOI [10,14] — landing = 0.75
        samples.extend(make_fixation(13.0, 2.0, 200, t))
        t += 200

        write_gaze_csv(str(gaze_dir / 'T01_GP1.csv'), samples)
        write_aois_csv(str(tmp_path / 'aois.csv'), [
            ('GP1', 0, 'alpha', 0.0, 1.0, 4.0, 3.0),
            ('GP1', 1, 'beta', 5.0, 1.0, 9.0, 3.0),
            ('GP1', 2, 'gamma', 10.0, 1.0, 14.0, 3.0),
        ])

        run_pipeline(str(tmp_path), str(out_dir))

        return {
            'fixations': read_csv(str(out_dir / 'fixations.csv')),
            'measures': read_csv(str(out_dir / 'reading_measures.csv')),
        }

    def test_fixation_count(self, gpt_output):
        assert len(gpt_output['fixations']) == 4, (
            f"Expected 4 fixations, got {len(gpt_output['fixations'])}")

    def test_word0_gpt_equals_gd(self, gpt_output):
        """Word 0: no regression from word 0, so GPT should equal GD."""
        w0 = [m for m in gpt_output['measures']
              if int(m['word_idx']) == 0]
        assert len(w0) == 1
        w0 = w0[0]
        gd = float(w0['gaze_duration'])
        gpt = float(w0['go_past_time'])
        assert abs(gpt - gd) < 5, (
            f'GPT(0) = {gpt} should equal GD(0) = {gd}')

    def test_word1_gpt_exceeds_gd(self, gpt_output):
        """Word 1: regression to word 0 before advancing past word 1,
        so GPT should include the regression fixation duration."""
        w1 = [m for m in gpt_output['measures']
              if int(m['word_idx']) == 1]
        assert len(w1) == 1
        w1 = w1[0]

        gd = float(w1['gaze_duration'])
        gpt = float(w1['go_past_time'])
        trt = float(w1['total_reading_time'])

        # GD = ~198 (single first-pass fixation on word 1)
        assert 185 <= gd <= 210, f'GD(1) = {gd}'

        # GPT = ~198 + ~148 = ~346 (includes regression to word 0)
        assert 320 <= gpt <= 380, f'GPT(1) = {gpt}, expected ~346'
        assert gpt > gd + 100, (
            f'GPT ({gpt}) should exceed GD ({gd}) by regression '
            f'duration (~148)')

        # TRT = GD since only one fixation ON word 1
        assert abs(trt - gd) < 5, (
            f'TRT ({trt}) should equal GD ({gd})')

        # GPT > TRT because GPT includes time on OTHER words
        assert gpt > trt + 50, (
            f'GPT ({gpt}) should exceed TRT ({trt})')

    def test_word2_gpt_equals_gd(self, gpt_output):
        """Word 2: no regression, GPT should equal GD."""
        w2 = [m for m in gpt_output['measures']
              if int(m['word_idx']) == 2]
        assert len(w2) == 1
        w2 = w2[0]
        gd = float(w2['gaze_duration'])
        gpt = float(w2['go_past_time'])
        assert abs(gpt - gd) < 5, (
            f'GPT(2) = {gpt} should equal GD(2) = {gd}')

    def test_landing_positions(self, gpt_output):
        """Verify landing positions: word 0 = 0.5, word 1 = 0.25,
        word 2 = 0.75."""
        measures = gpt_output['measures']

        w0 = [m for m in measures if int(m['word_idx']) == 0][0]
        w1 = [m for m in measures if int(m['word_idx']) == 1][0]
        w2 = [m for m in measures if int(m['word_idx']) == 2][0]

        # Word 0: fix at (2,2), AOI [0,4] -> (2-0)/4 = 0.5
        ffl0 = float(w0['first_fixation_landing'])
        assert abs(ffl0 - 0.5) < 0.05, (
            f'Word 0 landing = {ffl0}, expected 0.5')

        # Word 1: fix at (6,2), AOI [5,9] -> (6-5)/4 = 0.25
        ffl1 = float(w1['first_fixation_landing'])
        assert abs(ffl1 - 0.25) < 0.05, (
            f'Word 1 landing = {ffl1}, expected 0.25')

        # Word 2: fix at (13,2), AOI [10,14] -> (13-10)/4 = 0.75
        ffl2 = float(w2['first_fixation_landing'])
        assert abs(ffl2 - 0.75) < 0.05, (
            f'Word 2 landing = {ffl2}, expected 0.75')


class TestBlinkMarginFiltering:
    """Verify that samples within 50ms of blink boundaries are excluded.

    Signal: 200ms fixation -> 100ms blink (NaN) -> 200ms fixation.
    With 50ms margin, both fixations should be shortened by ~50ms
    compared to non-margin processing.
    """

    @pytest.fixture()
    def blink_output(self, tmp_path):
        gaze_dir = tmp_path / 'gaze'
        gaze_dir.mkdir()
        out_dir = tmp_path / 'output'
        out_dir.mkdir()

        samples = []
        t = 0

        # First fixation at (2,2) for 200ms
        samples.extend(make_fixation(2.0, 2.0, 200, t))
        t += 200

        # Blink (NaN) for 100ms
        for i in range(100):
            samples.append((t + i, 'NaN', 'NaN'))
        t += 100

        # Second fixation at (8,2) for 200ms
        samples.extend(make_fixation(8.0, 2.0, 200, t))
        t += 200

        write_gaze_csv(str(gaze_dir / 'T01_BM1.csv'), samples)
        write_aois_csv(str(tmp_path / 'aois.csv'), [
            ('BM1', 0, 'alpha', 0.0, 1.0, 4.0, 3.0),
            ('BM1', 1, 'beta', 6.0, 1.0, 10.0, 3.0),
        ])

        run_pipeline(str(tmp_path), str(out_dir))

        return {
            'fixations': read_csv(str(out_dir / 'fixations.csv')),
        }

    def test_two_fixations_detected(self, blink_output):
        assert len(blink_output['fixations']) == 2, (
            f"Expected 2 fixations, got {len(blink_output['fixations'])}")

    def test_first_fixation_shortened_by_margin(self, blink_output):
        """First fixation should end before blink margin (~148ms),
        not at blink onset (~198ms without margin)."""
        fix0 = blink_output['fixations'][0]
        duration = float(fix0['duration_ms'])
        assert duration < 165, (
            f'First fixation duration {duration}ms too long — '
            f'blink margin (50ms) should shorten it to ~148ms')

    def test_second_fixation_onset_delayed(self, blink_output):
        """Second fixation should start after blink + margin (~351ms),
        not immediately after blink (~301ms without margin)."""
        fix1 = blink_output['fixations'][1]
        onset = float(fix1['onset_ms'])
        assert onset >= 340, (
            f'Second fixation onset {onset}ms too early — '
            f'blink margin (50ms) should delay it to ~351ms')


# ---------------------------------------------------------------------------
# Makefile round-trip test
# ---------------------------------------------------------------------------

class TestMakefileRoundTrip:
    """Verify Makefile clean + all round trip."""

    def test_makefile_exists(self):
        assert os.path.isfile('/app/Makefile'), '/app/Makefile not found'

    def test_round_trip(self):
        # Clean
        r = subprocess.run(
            ['make', '-C', '/app', 'clean'],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, f'make clean failed: {r.stderr}'
        assert not os.path.exists('/app/output/fixations.csv'), (
            'fixations.csv still exists after make clean')

        # Rebuild
        r = subprocess.run(
            ['make', '-C', '/app', 'all'],
            capture_output=True, text=True, timeout=120,
        )
        assert r.returncode == 0, f'make all failed: {r.stderr}'

        # Verify CSV outputs
        for fname in ('fixations.csv', 'saccades.csv',
                      'reading_measures.csv'):
            assert os.path.isfile(f'/app/output/{fname}'), (
                f'{fname} missing after make all')

        # Verify database
        assert os.path.isfile('/app/output/gaze.db'), (
            'gaze.db missing after make all')
        conn = sqlite3.connect('/app/output/gaze.db')
        for tbl in ('fixations', 'saccades', 'reading_measures'):
            cur = conn.execute(f'SELECT COUNT(*) FROM {tbl}')
            assert cur.fetchone()[0] > 0, (
                f'{tbl} table empty after rebuild')
        conn.close()
