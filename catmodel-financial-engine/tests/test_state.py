"""
Verification tests for the hierarchical financial module pipeline.

"""

import csv
import json
import os
import sqlite3
import subprocess
import pytest
from collections import defaultdict


# ---------------------------------------------------------------------------
# Reference implementation (used only for verification)
# ---------------------------------------------------------------------------

def _apply_calcrule(calcrule_id, params, input_loss):
    ded = params['deductible1']
    att = params['attachment1']
    lim = params['limit1']
    sh = params['share1']

    if calcrule_id == 1:
        loss = input_loss - ded
        if loss < 0:
            loss = 0.0
        if loss > lim:
            loss = lim
        return loss
    elif calcrule_id == 2:
        loss = input_loss - ded
        if loss < 0:
            loss = 0.0
        if loss > att + lim:
            loss = lim
        else:
            loss = loss - att
        if loss < 0:
            loss = 0.0
        loss = loss * sh
        return loss
    elif calcrule_id == 3:
        if input_loss <= ded:
            return 0.0
        loss = input_loss
        if loss > lim:
            loss = lim
        return loss
    elif calcrule_id == 5:
        if ded + lim >= 1.0:
            return input_loss * (1.0 - ded)
        else:
            return input_loss * lim
    elif calcrule_id == 9:
        effective_ded = ded * lim
        loss = input_loss - effective_ded
        if loss < 0:
            loss = 0.0
        if loss > lim:
            loss = lim
        return loss
    elif calcrule_id == 12:
        return max(input_loss - ded, 0.0)
    elif calcrule_id == 14:
        return min(input_loss, lim)
    elif calcrule_id == 16:
        loss = input_loss * (1.0 - ded)
        if loss < 0:
            loss = 0.0
        return loss
    elif calcrule_id == 100:
        return input_loss
    else:
        raise ValueError(f"Unknown calcrule {calcrule_id}")


def _load_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def _build_reference():
    """Compute full reference output and intermediate level losses."""
    programme = _load_csv('/app/data/fm_programme.csv')
    profiles_raw = _load_csv('/app/data/fm_profile.csv')
    policytc = _load_csv('/app/data/fm_policytc.csv')
    guls = _load_csv('/app/data/guls.csv')

    profile_map = {}
    for p in profiles_raw:
        pid = int(p['profile_id'])
        profile_map[pid] = {
            'calcrule_id': int(p['calcrule_id']),
            'deductible1': float(p['deductible1']),
            'attachment1': float(p['attachment1']),
            'limit1': float(p['limit1']),
            'share1': float(p['share1']),
        }

    hierarchy = defaultdict(dict)
    for row in programme:
        level = int(row['level_id'])
        fid = int(row['from_agg_id'])
        tid = int(row['to_agg_id'])
        hierarchy[level][fid] = tid

    max_level = max(hierarchy.keys())

    node_profile = {}
    for row in policytc:
        level = int(row['level_id'])
        agg_id = int(row['agg_id'])
        profile_id = int(row['profile_id'])
        node_profile[(level, agg_id)] = (profile_map[profile_id]['calcrule_id'],
                                          profile_map[profile_id])

    event_samples = defaultdict(dict)
    all_items = set()
    for row in guls:
        eid = int(row['event_id'])
        iid = int(row['item_id'])
        sid = int(row['sidx'])
        loss = float(row['loss'])
        event_samples[(eid, sid)][iid] = loss
        all_items.add(iid)

    all_items = sorted(all_items)

    level_nodes = {}
    for level in range(1, max_level + 1):
        nodes = defaultdict(list)
        for fid, tid in hierarchy[level].items():
            nodes[tid].append(fid)
        level_nodes[level] = dict(nodes)

    def get_descendants(level, from_agg_ids):
        current = set(from_agg_ids)
        for lev in range(level - 1, 0, -1):
            prev = set()
            for fid, tid in hierarchy[lev].items():
                if tid in current:
                    prev.add(fid)
            current = prev
        return sorted(i for i in current if i in all_items)

    results = {}
    level_losses_ref = {}  # (eid, sid, level, node_id) -> (input_loss, output_loss)

    for (eid, sid), gul_map in sorted(event_samples.items()):
        item_loss = {iid: gul_map.get(iid, 0.0) for iid in all_items}

        for level in range(1, max_level + 1):
            nodes = level_nodes.get(level, {})
            for node_id, children in nodes.items():
                desc_items = get_descendants(level, children)
                agg_input = sum(item_loss[iid] for iid in desc_items)

                calcrule_id, params = node_profile[(level, node_id)]
                agg_output = _apply_calcrule(calcrule_id, params, agg_input)

                level_losses_ref[(eid, sid, level, node_id)] = (agg_input, agg_output)

                if agg_input > 0:
                    factor = agg_output / agg_input
                else:
                    factor = 0.0

                for iid in desc_items:
                    item_loss[iid] *= factor

        for iid in all_items:
            rounded = round(item_loss[iid], 2)
            if rounded > 0:
                results[(eid, iid, sid)] = rounded

    return results, level_losses_ref


def _load_solver_output():
    output_path = '/app/output.csv'
    if not os.path.exists(output_path):
        return None
    result = {}
    with open(output_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            eid = int(row['event_id'])
            iid = int(row['item_id'])
            sid = int(row['sidx'])
            loss = float(row['loss'])
            result[(eid, iid, sid)] = loss
    return result


# Build reference once for all tests
_REFERENCE = None
_LEVEL_LOSSES_REF = None
_SOLVER = None


def _get_reference():
    global _REFERENCE, _LEVEL_LOSSES_REF
    if _REFERENCE is None:
        _REFERENCE, _LEVEL_LOSSES_REF = _build_reference()
    return _REFERENCE


def _get_level_losses_ref():
    global _LEVEL_LOSSES_REF
    if _LEVEL_LOSSES_REF is None:
        _get_reference()
    return _LEVEL_LOSSES_REF


def _get_solver():
    global _SOLVER
    if _SOLVER is None:
        _SOLVER = _load_solver_output()
    return _SOLVER


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestArtifactsExist:
    def test_output_csv_exists(self):
        assert os.path.exists('/app/output.csv'), \
            "Output file /app/output.csv does not exist"

    def test_fm_results_db_exists(self):
        assert os.path.exists('/app/fm_results.db'), \
            "SQLite database /app/fm_results.db does not exist"

    def test_report_json_exists(self):
        assert os.path.exists('/app/report.json'), \
            "Report file /app/report.json does not exist"

    def test_makefile_exists(self):
        assert os.path.exists('/app/Makefile'), \
            "Makefile /app/Makefile does not exist"

    def test_output_has_correct_columns(self):
        with open('/app/output.csv') as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames
        assert 'event_id' in fields
        assert 'item_id' in fields
        assert 'sidx' in fields
        assert 'loss' in fields

    def test_output_not_empty(self):
        solver = _get_solver()
        assert solver is not None
        assert len(solver) > 0

    def test_output_row_count_reasonable(self):
        solver = _get_solver()
        assert solver is not None
        assert len(solver) >= 80, f"Too few output rows: {len(solver)}"
        assert len(solver) <= 180, f"Too many output rows: {len(solver)}"


class TestSQLiteSchema:
    """Verify the SQLite database has the correct schema."""

    def test_level_losses_table_exists(self):
        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='level_losses'")
        result = c.fetchone()
        conn.close()
        assert result is not None, "Table 'level_losses' does not exist"

    def test_level_losses_columns(self):
        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        c.execute("PRAGMA table_info(level_losses)")
        cols = {row[1] for row in c.fetchall()}
        conn.close()
        expected = {'event_id', 'sidx', 'level', 'agg_id', 'input_loss', 'output_loss'}
        missing = expected - cols
        assert len(missing) == 0, f"level_losses missing columns: {missing}"

    def test_final_losses_table_exists(self):
        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='final_losses'")
        result = c.fetchone()
        conn.close()
        assert result is not None, "Table 'final_losses' does not exist"

    def test_final_losses_columns(self):
        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        c.execute("PRAGMA table_info(final_losses)")
        cols = {row[1] for row in c.fetchall()}
        conn.close()
        expected = {'event_id', 'item_id', 'sidx', 'loss'}
        missing = expected - cols
        assert len(missing) == 0, f"final_losses missing columns: {missing}"

    def test_event_summary_view_exists(self):
        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='view' AND name='event_summary'")
        result = c.fetchone()
        conn.close()
        assert result is not None, "View 'event_summary' does not exist"

    def test_event_summary_columns(self):
        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        c.execute("SELECT * FROM event_summary LIMIT 1")
        col_names = [desc[0] for desc in c.description]
        conn.close()
        expected = {'event_id', 'total_gul', 'total_insured', 'item_count', 'reduction_pct'}
        actual = set(col_names)
        missing = expected - actual
        assert len(missing) == 0, f"event_summary missing columns: {missing}"

    def test_level_losses_row_count(self):
        """Should have 8 nodes * 15 (event,sample) pairs = 120 rows."""
        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM level_losses")
        count = c.fetchone()[0]
        conn.close()
        assert count == 120, f"Expected 120 level_losses rows, got {count}"

    def test_final_losses_only_positive(self):
        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM final_losses WHERE loss <= 0")
        count = c.fetchone()[0]
        conn.close()
        assert count == 0, f"final_losses has {count} non-positive loss rows"


class TestReferenceMatch:
    """Compare solver output to reference implementation."""

    def test_all_expected_keys_present(self):
        ref = _get_reference()
        solver = _get_solver()
        assert solver is not None
        missing = [k for k in ref if k not in solver]
        assert len(missing) == 0, \
            f"Missing {len(missing)} expected rows. First 10: {missing[:10]}"

    def test_no_unexpected_keys(self):
        ref = _get_reference()
        solver = _get_solver()
        assert solver is not None
        extra = [k for k in solver if k not in ref]
        assert len(extra) == 0, \
            f"Found {len(extra)} unexpected rows. First 10: {extra[:10]}"

    def test_values_match(self):
        ref = _get_reference()
        solver = _get_solver()
        assert solver is not None
        mismatches = []
        for key in ref:
            if key in solver:
                expected = ref[key]
                actual = solver[key]
                if abs(actual - expected) > 0.02:
                    mismatches.append((key, expected, actual))
        assert len(mismatches) == 0, \
            f"{len(mismatches)} value mismatches. First 10: {mismatches[:10]}"


class TestLevelLossesDB:
    """Verify intermediate level losses stored in SQLite match reference."""

    def test_level_losses_keys_complete(self):
        ll_ref = _get_level_losses_ref()
        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        rows = c.execute(
            'SELECT event_id, sidx, level, agg_id FROM level_losses'
        ).fetchall()
        conn.close()
        db_keys = {(r[0], r[1], r[2], r[3]) for r in rows}
        ref_keys = set(ll_ref.keys())
        missing = ref_keys - db_keys
        assert len(missing) == 0, \
            f"Missing {len(missing)} level_losses rows. First 5: {sorted(missing)[:5]}"

    def test_level_losses_input_values(self):
        ll_ref = _get_level_losses_ref()
        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        rows = c.execute(
            'SELECT event_id, sidx, level, agg_id, input_loss FROM level_losses'
        ).fetchall()
        conn.close()
        errors = []
        for r in rows:
            key = (r[0], r[1], r[2], r[3])
            if key in ll_ref:
                ref_in = ll_ref[key][0]
                if abs(r[4] - ref_in) > 0.1:
                    errors.append((key, ref_in, r[4]))
        assert len(errors) == 0, \
            f"{len(errors)} input_loss mismatches. First 5: {errors[:5]}"

    def test_level_losses_output_values(self):
        ll_ref = _get_level_losses_ref()
        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        rows = c.execute(
            'SELECT event_id, sidx, level, agg_id, output_loss FROM level_losses'
        ).fetchall()
        conn.close()
        errors = []
        for r in rows:
            key = (r[0], r[1], r[2], r[3])
            if key in ll_ref:
                ref_out = ll_ref[key][1]
                if abs(r[4] - ref_out) > 0.1:
                    errors.append((key, ref_out, r[4]))
        assert len(errors) == 0, \
            f"{len(errors)} output_loss mismatches. First 5: {errors[:5]}"

    def test_final_losses_db_matches_csv(self):
        """final_losses table must be consistent with output.csv."""
        solver = _get_solver()
        assert solver is not None
        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        rows = c.execute(
            'SELECT event_id, item_id, sidx, loss FROM final_losses'
        ).fetchall()
        conn.close()
        db_data = {}
        for r in rows:
            db_data[(r[0], r[1], r[2])] = r[3]
        # Check counts match
        assert len(db_data) == len(solver), \
            f"final_losses has {len(db_data)} rows but output.csv has {len(solver)}"
        # Check values match
        mismatches = []
        for key in solver:
            if key not in db_data:
                mismatches.append((key, 'missing from db'))
            elif abs(db_data[key] - solver[key]) > 0.01:
                mismatches.append((key, solver[key], db_data[key]))
        assert len(mismatches) == 0, \
            f"{len(mismatches)} DB/CSV mismatches. First 5: {mismatches[:5]}"


class TestEventSummary:
    """Verify the event_summary view returns correct aggregated values."""

    def test_event_summary_row_count(self):
        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM event_summary")
        count = c.fetchone()[0]
        conn.close()
        assert count == 5, f"Expected 5 event_summary rows, got {count}"

    def test_event_summary_total_gul(self):
        """Verify total_gul matches sum of GUL losses per event."""
        guls = _load_csv('/app/data/guls.csv')
        gul_totals = defaultdict(float)
        for row in guls:
            gul_totals[int(row['event_id'])] += float(row['loss'])

        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        rows = c.execute(
            "SELECT event_id, total_gul FROM event_summary"
        ).fetchall()
        conn.close()
        errors = []
        for r in rows:
            expected = gul_totals[r[0]]
            if abs(r[1] - expected) > 0.01:
                errors.append((r[0], expected, r[1]))
        assert len(errors) == 0, \
            f"total_gul mismatches: {errors}"

    def test_event_summary_total_insured(self):
        """Verify total_insured matches sum of final_losses per event."""
        ref = _get_reference()
        ref_totals = defaultdict(float)
        for (eid, iid, sid), loss in ref.items():
            ref_totals[eid] += loss

        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        rows = c.execute(
            "SELECT event_id, total_insured FROM event_summary"
        ).fetchall()
        conn.close()
        errors = []
        for r in rows:
            expected = ref_totals[r[0]]
            if abs(r[1] - expected) > 1.0:
                errors.append((r[0], expected, r[1]))
        assert len(errors) == 0, \
            f"total_insured mismatches: {errors}"

    def test_event_summary_item_count(self):
        """Verify item_count = distinct items with positive loss."""
        ref = _get_reference()
        item_counts = defaultdict(set)
        for (eid, iid, sid), loss in ref.items():
            if loss > 0:
                item_counts[eid].add(iid)

        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        rows = c.execute(
            "SELECT event_id, item_count FROM event_summary"
        ).fetchall()
        conn.close()
        errors = []
        for r in rows:
            expected = len(item_counts[r[0]])
            if r[1] != expected:
                errors.append((r[0], expected, r[1]))
        assert len(errors) == 0, \
            f"item_count mismatches: {errors}"

    def test_event_summary_reduction_pct(self):
        """Verify reduction_pct calculation."""
        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        rows = c.execute(
            "SELECT event_id, total_gul, total_insured, reduction_pct FROM event_summary"
        ).fetchall()
        conn.close()
        errors = []
        for r in rows:
            eid, tg, ti, rp = r
            expected_rp = round(100.0 * (1.0 - ti / tg), 2)
            if abs(rp - expected_rp) > 0.05:
                errors.append((eid, expected_rp, rp))
        assert len(errors) == 0, \
            f"reduction_pct mismatches: {errors}"


class TestReportJSON:
    """Verify report.json content and structure."""

    def test_report_is_valid_json(self):
        with open('/app/report.json') as f:
            data = json.load(f)
        assert isinstance(data, list), "report.json must be a JSON array"

    def test_report_has_5_events(self):
        with open('/app/report.json') as f:
            data = json.load(f)
        assert len(data) == 5, f"Expected 5 events in report, got {len(data)}"

    def test_report_schema(self):
        with open('/app/report.json') as f:
            data = json.load(f)
        required_keys = {'event_id', 'total_gul', 'total_insured', 'item_count', 'reduction_pct'}
        for entry in data:
            missing = required_keys - set(entry.keys())
            assert len(missing) == 0, \
                f"Event {entry.get('event_id', '?')} missing keys: {missing}"

    def test_report_sorted_by_event_id(self):
        with open('/app/report.json') as f:
            data = json.load(f)
        event_ids = [e['event_id'] for e in data]
        assert event_ids == sorted(event_ids), \
            f"report.json not sorted by event_id: {event_ids}"

    def test_report_values_match_view(self):
        """Report values must match event_summary view."""
        with open('/app/report.json') as f:
            report_data = json.load(f)

        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        rows = c.execute(
            "SELECT event_id, total_gul, total_insured, item_count, reduction_pct "
            "FROM event_summary ORDER BY event_id"
        ).fetchall()
        conn.close()

        view_data = {}
        for r in rows:
            view_data[r[0]] = {
                'total_gul': r[1], 'total_insured': r[2],
                'item_count': r[3], 'reduction_pct': r[4]
            }

        errors = []
        for entry in report_data:
            eid = entry['event_id']
            if eid not in view_data:
                errors.append(f"Event {eid} in report but not in view")
                continue
            v = view_data[eid]
            if abs(entry['total_gul'] - v['total_gul']) > 0.01:
                errors.append(f"E{eid} total_gul: report={entry['total_gul']}, view={v['total_gul']}")
            if abs(entry['total_insured'] - v['total_insured']) > 1.0:
                errors.append(f"E{eid} total_insured: report={entry['total_insured']}, view={v['total_insured']}")
            if entry['item_count'] != v['item_count']:
                errors.append(f"E{eid} item_count: report={entry['item_count']}, view={v['item_count']}")
            if abs(entry['reduction_pct'] - v['reduction_pct']) > 0.05:
                errors.append(f"E{eid} reduction_pct: report={entry['reduction_pct']}, view={v['reduction_pct']}")

        assert len(errors) == 0, \
            f"Report/view mismatches: {errors}"


class TestLossConservation:
    """Verify aggregate-level loss conservation."""

    def test_event_totals(self):
        ref = _get_reference()
        solver = _get_solver()
        assert solver is not None
        solver_totals = defaultdict(float)
        ref_totals = defaultdict(float)
        for (eid, iid, sid), loss in solver.items():
            solver_totals[(eid, sid)] += loss
        for (eid, iid, sid), loss in ref.items():
            ref_totals[(eid, sid)] += loss
        for key in ref_totals:
            assert key in solver_totals, f"Missing event/sample {key}"
            assert abs(solver_totals[key] - ref_totals[key]) < 0.5, \
                f"Event {key}: expected {ref_totals[key]:.2f}, got {solver_totals[key]:.2f}"


class TestBackAllocation:
    """Verify proportional back-allocation within L1 groups."""

    def test_proportionality_within_groups(self):
        guls_raw = _load_csv('/app/data/guls.csv')
        programme = _load_csv('/app/data/fm_programme.csv')
        solver = _get_solver()
        assert solver is not None

        l1_groups = defaultdict(list)
        for row in programme:
            if int(row['level_id']) == 1:
                l1_groups[int(row['to_agg_id'])].append(int(row['from_agg_id']))

        gul_map = {}
        for row in guls_raw:
            eid = int(row['event_id'])
            iid = int(row['item_id'])
            sid = int(row['sidx'])
            gul_map[(eid, iid, sid)] = float(row['loss'])

        errors = []
        events_sidxs = set()
        for (eid, iid, sid) in solver:
            events_sidxs.add((eid, sid))

        for eid, sid in events_sidxs:
            for gid, items in l1_groups.items():
                gul_vals = {i: gul_map.get((eid, i, sid), 0.0) for i in items}
                out_vals = {i: solver.get((eid, i, sid), 0.0) for i in items}
                gul_total = sum(gul_vals.values())
                out_total = sum(out_vals.values())
                if gul_total == 0 or out_total == 0:
                    continue
                for i in items:
                    if gul_vals[i] == 0:
                        if out_vals[i] != 0:
                            errors.append(
                                f"E{eid}S{sid} G{gid} I{i}: GUL=0 but loss={out_vals[i]}")
                        continue
                    expected_ratio = gul_vals[i] / gul_total
                    actual_ratio = out_vals[i] / out_total
                    if abs(expected_ratio - actual_ratio) > 0.001:
                        errors.append(
                            f"E{eid}S{sid} G{gid} I{i}: "
                            f"expected ratio {expected_ratio:.6f}, got {actual_ratio:.6f}")

        assert len(errors) == 0, \
            f"{len(errors)} proportionality errors. First 5: {errors[:5]}"


class TestCalcruleEdgeCases:
    """Verify correct handling of calcrule-specific edge cases."""

    def test_franchise_at_threshold(self):
        """Event 2, S1: Group 3 items 7,8,9 have GUL sum = 50000+30000+40000 = 120000.
        Calcrule 3 (franchise) with ded=120000: input <= ded → output = 0."""
        ll_ref = _get_level_losses_ref()
        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        row = c.execute(
            "SELECT output_loss FROM level_losses WHERE event_id=2 AND sidx=1 AND level=1 AND agg_id=3"
        ).fetchone()
        conn.close()
        assert row is not None, "Missing level_losses row for E2 S1 L1 N3"
        assert row[0] == 0.0, \
            f"Franchise at threshold should produce 0, got {row[0]}"

    def test_franchise_above_threshold(self):
        """Event 1, S1: Group 3 items sum = 850000 > franchise ded 120000.
        Full loss passes through (capped at limit 900000)."""
        solver = _get_solver()
        ref = _get_reference()
        assert solver is not None
        for iid in [7, 8, 9]:
            ref_val = ref.get((1, iid, 1), 0.0)
            solver_val = solver.get((1, iid, 1), 0.0)
            assert solver_val > 0, \
                f"E1 S1 I{iid}: expected non-zero loss (franchise above threshold)"
            assert abs(solver_val - ref_val) < 0.02, \
                f"E1 S1 I{iid}: expected {ref_val}, got {solver_val}"

    def test_pct_loss_deductible(self):
        """Calcrule 16 (percentage of loss deductible) should always produce
        output when input > 0. Items 10,11,12 use this calcrule."""
        solver = _get_solver()
        ref = _get_reference()
        assert solver is not None
        for key in ref:
            eid, iid, sid = key
            if iid in [10, 11, 12]:
                assert key in solver, \
                    f"E{eid} S{sid} I{iid}: pct-loss deductible should produce output"

    def test_proportional_limit_calcrule5(self):
        """Calcrule 5 at L2 for account 2: with ded=0.08, lim=0.50 (sum < 1),
        the output should be input * 0.50."""
        ll_ref = _get_level_losses_ref()
        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        rows = c.execute(
            "SELECT event_id, sidx, input_loss, output_loss FROM level_losses "
            "WHERE level=2 AND agg_id=2"
        ).fetchall()
        conn.close()
        errors = []
        for r in rows:
            expected_out = r[2] * 0.50
            if abs(r[3] - expected_out) > 0.1:
                errors.append(f"E{r[0]}S{r[1]}: expected {expected_out}, got {r[3]}")
        assert len(errors) == 0, \
            f"Calcrule 5 mismatches: {errors}"

    def test_zero_gul_items_stay_zero(self):
        guls_raw = _load_csv('/app/data/guls.csv')
        solver = _get_solver()
        assert solver is not None
        gul_map = {}
        for row in guls_raw:
            eid = int(row['event_id'])
            iid = int(row['item_id'])
            sid = int(row['sidx'])
            gul_map[(eid, iid, sid)] = float(row['loss'])
        errors = []
        for key, loss in solver.items():
            gul = gul_map.get(key, 0.0)
            if gul == 0.0 and loss > 0.0:
                errors.append(f"E{key[0]} I{key[1]} S{key[2]}: GUL=0 but loss={loss}")
        assert len(errors) == 0, \
            f"{len(errors)} zero-GUL violations. First 5: {errors[:5]}"

    def test_item_loss_not_exceeds_gul(self):
        guls_raw = _load_csv('/app/data/guls.csv')
        solver = _get_solver()
        assert solver is not None
        gul_map = {}
        for row in guls_raw:
            eid = int(row['event_id'])
            iid = int(row['item_id'])
            sid = int(row['sidx'])
            gul_map[(eid, iid, sid)] = float(row['loss'])
        for key, loss in solver.items():
            gul = gul_map.get(key, 0.0)
            assert loss <= gul + 0.01, \
                f"E{key[0]} I{key[1]} S{key[2]}: loss {loss} exceeds GUL {gul}"

    def test_small_event_below_deductibles(self):
        """Event 3, S3: Very small losses should all be zeroed out by deductibles."""
        solver = _get_solver()
        assert solver is not None
        for iid in range(1, 13):
            loss = solver.get((3, iid, 3), 0.0)
            assert loss == 0.0, \
                f"E3 S3 I{iid}: expected 0 (below deductibles), got {loss}"

    def test_excess_layer_calcrule2(self):
        """Calcrule 2 (excess layer at L4) with att=500000, lim=3000000, sh=0.80.
        Verify in level_losses that the share is applied."""
        ll_ref = _get_level_losses_ref()
        conn = sqlite3.connect('/app/fm_results.db')
        c = conn.cursor()
        rows = c.execute(
            "SELECT event_id, sidx, input_loss, output_loss FROM level_losses "
            "WHERE level=4 AND agg_id=1"
        ).fetchall()
        conn.close()
        for r in rows:
            eid, sid, inp, out = r
            ref_key = (eid, sid, 4, 1)
            ref_in, ref_out = ll_ref[ref_key]
            assert abs(inp - ref_in) < 0.1, \
                f"E{eid}S{sid} L4 input: expected {ref_in}, got {inp}"
            assert abs(out - ref_out) < 0.1, \
                f"E{eid}S{sid} L4 output: expected {ref_out}, got {out}"
            # If input > attachment, share should reduce output
            if inp > 500000:
                assert out < inp, \
                    f"E{eid}S{sid}: excess layer should reduce loss (in={inp}, out={out})"


class TestMakefileRebuild:
    """Verify make clean && make all produces correct outputs."""

    def test_make_clean_removes_artifacts(self):
        result = subprocess.run(
            ['make', '-C', '/app', 'clean'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, \
            f"make clean failed: {result.stderr}"
        assert not os.path.exists('/app/output.csv'), \
            "make clean did not remove output.csv"
        assert not os.path.exists('/app/fm_results.db'), \
            "make clean did not remove fm_results.db"
        assert not os.path.exists('/app/report.json'), \
            "make clean did not remove report.json"

    def test_make_all_rebuilds(self):
        # Ensure clean state first
        subprocess.run(['make', '-C', '/app', 'clean'],
                       capture_output=True, timeout=30)
        result = subprocess.run(
            ['make', '-C', '/app', 'all'],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, \
            f"make all failed: {result.stderr}"
        assert os.path.exists('/app/output.csv'), \
            "make all did not produce output.csv"
        assert os.path.exists('/app/fm_results.db'), \
            "make all did not produce fm_results.db"
        assert os.path.exists('/app/report.json'), \
            "make all did not produce report.json"

    def test_rebuilt_output_matches_reference(self):
        """After clean + rebuild, output must still match reference."""
        ref = _get_reference()
        solver_rebuilt = _load_solver_output()
        assert solver_rebuilt is not None
        mismatches = []
        for key in ref:
            if key not in solver_rebuilt:
                mismatches.append((key, ref[key], 'missing'))
            elif abs(solver_rebuilt[key] - ref[key]) > 0.02:
                mismatches.append((key, ref[key], solver_rebuilt[key]))
        assert len(mismatches) == 0, \
            f"{len(mismatches)} post-rebuild mismatches. First 5: {mismatches[:5]}"
