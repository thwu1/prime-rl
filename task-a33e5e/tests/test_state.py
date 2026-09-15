
import sys
sys.path.insert(0, '/app')

import csv
import json
import pytest
from collections import defaultdict

from star_tree import (
    StarTreeBuilder,
    StarTreeQueryEngine,
    StarTreeNode,
    merge_star_trees,
    STAR,
)

# ---------------------------------------------------------------------------
# DNA markers — hardcoded expected values from the deterministic dataset.
# These anchor the task to this specific data instance.
# ---------------------------------------------------------------------------

DNA_TOTAL_REVENUE_A = 4358853.35
DNA_TOTAL_COUNT_A = 25000.0
DNA_NA_REVENUE_SUM = 1519215.7
DNA_EU_ELEC_COUNT = 1782.0
DNA_APAC_FOOD_WEB_MIN = 4.53
DNA_EU_DISCOUNT_AVG = 0.10266456908344733
DNA_SPORTS_QTY_SUM = 11753.0
DNA_NA_SAT_REVENUE = 269694.0
DNA_MON_QTY_COUNT = 3105.0
DNA_GLOBAL_MIN_REV = 1.0
DNA_NA_CLOTH_MOB_FRI_MAX = 172.19
DNA_LATAM_HOME_WHSL_SUM = 4942.3
DNA_MERGED_TOTAL_REV = 8740891.04
DNA_MERGED_NA_ELEC_COUNT = 4185.0
DNA_MERGED_EU_DISC_AVG = 0.10270443102395331
DNA_MERGED_BOOKS_WEB_MIN = 1.0
DNA_MERGED_BOOKS_WEB_MAX = 42.18

DNA_GB_REGION_REVENUE = {
    'NA': 1519215.7, 'EU': 1282802.81, 'APAC': 861724.44,
    'LATAM': 451981.61, 'MEA': 243128.79,
}
DNA_GB_CAT_NA_REVENUE = {
    'electronics': 1064789.03, 'clothing': 177208.97, 'home': 126671.97,
    'sports': 69796.95, 'food': 37414.9, 'books': 25584.88, 'toys': 17749.0,
}
DNA_MERGED_GB_REGION_REV = {
    'NA': 3002628.15, 'EU': 2600546.1, 'APAC': 1734499.06,
    'LATAM': 919636.49, 'MEA': 483581.24,
}
DNA_MERGED_GB_CAT_MOB_DISC_AVG = {
    'electronics': 0.10203976396917148, 'toys': 0.10247165178571428,
    'books': 0.1041688939222348, 'sports': 0.10491767001114827,
    'food': 0.10794794082367053, 'home': 0.10337389811104751,
    'clothing': 0.10083480392156864,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def load_config():
    with open('/app/config.json') as f:
        return json.load(f)


def brute_force_query(data, constraints, metric, agg_type):
    filtered = [r for r in data
                if all(r[dim] == val for dim, val in constraints.items())]
    if not filtered:
        return None
    values = [float(r[metric]) for r in filtered]
    if agg_type == 'SUM':
        return sum(values)
    if agg_type == 'COUNT':
        return float(len(values))
    if agg_type == 'MIN':
        return min(values)
    if agg_type == 'MAX':
        return max(values)
    if agg_type == 'AVG':
        return sum(values) / len(values)
    raise ValueError(agg_type)


def brute_force_group_by(data, constraints, gb_dim, metric, agg_type):
    filtered = [r for r in data
                if all(r[dim] == val for dim, val in constraints.items())]
    groups = defaultdict(list)
    for r in filtered:
        groups[r[gb_dim]].append(float(r[metric]))
    result = {}
    for val, values in groups.items():
        if agg_type == 'SUM':
            result[val] = sum(values)
        elif agg_type == 'COUNT':
            result[val] = float(len(values))
        elif agg_type == 'MIN':
            result[val] = min(values)
        elif agg_type == 'MAX':
            result[val] = max(values)
        elif agg_type == 'AVG':
            result[val] = sum(values) / len(values)
    return result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def config():
    return load_config()


@pytest.fixture(scope='module')
def data_a():
    return load_csv('/app/data/sales_data_segment_a.csv')


@pytest.fixture(scope='module')
def data_b():
    return load_csv('/app/data/sales_data_segment_b.csv')


@pytest.fixture(scope='module')
def combined_data(data_a, data_b):
    return data_a + data_b


@pytest.fixture(scope='module')
def tree_a(config, data_a):
    builder = StarTreeBuilder(config)
    builder.build(data_a)
    return builder.get_tree()


@pytest.fixture(scope='module')
def tree_b(config, data_b):
    builder = StarTreeBuilder(config)
    builder.build(data_b)
    return builder.get_tree()


@pytest.fixture(scope='module')
def merged_tree(tree_a, tree_b, config):
    return merge_star_trees(tree_a, tree_b, config)


@pytest.fixture(scope='module')
def engine_a(tree_a, config):
    return StarTreeQueryEngine(tree_a, config)


@pytest.fixture(scope='module')
def merged_engine(merged_tree, config):
    return StarTreeQueryEngine(merged_tree, config)


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

class TestTreeStructure:

    def test_root_document_count(self, tree_a, data_a):
        assert tree_a.document_count == len(data_a)

    def test_root_has_region_children(self, tree_a):
        non_star = {k for k in tree_a.children if k != '*'}
        assert non_star == {'NA', 'EU', 'APAC', 'LATAM', 'MEA'}

    def test_star_node_at_root(self, tree_a):
        """5 regions >= threshold 5 => star exists at root."""
        assert '*' in tree_a.children

    def test_star_node_doc_count_matches_root(self, tree_a):
        assert tree_a.children['*'].document_count == tree_a.document_count

    def test_non_star_children_sum_to_parent(self, tree_a):
        total = sum(c.document_count
                    for k, c in tree_a.children.items() if k != '*')
        assert total == tree_a.document_count

    def test_category_star_exists(self, tree_a):
        """7 categories >= threshold 5 => star exists at category level."""
        na = tree_a.children['NA']
        assert '*' in na.children

    def test_channel_no_star(self, tree_a):
        """4 channels < threshold 5 => no star at channel level."""
        na = tree_a.children['NA']
        elec = na.children['electronics']
        if len(elec.children) > 0:
            assert '*' not in elec.children

    def test_star_constant_value(self):
        assert STAR == '*'


# ---------------------------------------------------------------------------
# DNA point query tests — hardcoded expected values
# ---------------------------------------------------------------------------

class TestDNAPointQueries:

    def test_total_revenue_dna(self, engine_a):
        result = engine_a.query({}, 'revenue', 'SUM')
        assert result == pytest.approx(DNA_TOTAL_REVENUE_A, rel=1e-6)

    def test_total_count_dna(self, engine_a):
        result = engine_a.query({}, 'revenue', 'COUNT')
        assert result == pytest.approx(DNA_TOTAL_COUNT_A, rel=1e-6)

    def test_na_revenue_dna(self, engine_a):
        result = engine_a.query({'region': 'NA'}, 'revenue', 'SUM')
        assert result == pytest.approx(DNA_NA_REVENUE_SUM, rel=1e-6)

    def test_eu_elec_count_dna(self, engine_a):
        result = engine_a.query(
            {'region': 'EU', 'category': 'electronics'}, 'revenue', 'COUNT')
        assert result == pytest.approx(DNA_EU_ELEC_COUNT, rel=1e-6)

    def test_apac_food_web_min_dna(self, engine_a):
        result = engine_a.query(
            {'region': 'APAC', 'category': 'food', 'channel': 'web'},
            'revenue', 'MIN')
        assert result == pytest.approx(DNA_APAC_FOOD_WEB_MIN, rel=1e-6)

    def test_eu_discount_avg_dna(self, engine_a):
        result = engine_a.query({'region': 'EU'}, 'discount', 'AVG')
        assert result == pytest.approx(DNA_EU_DISCOUNT_AVG, rel=1e-6)

    def test_sports_qty_sum_dna(self, engine_a):
        result = engine_a.query({'category': 'sports'}, 'quantity', 'SUM')
        assert result == pytest.approx(DNA_SPORTS_QTY_SUM, rel=1e-6)

    def test_na_sat_revenue_dna(self, engine_a):
        result = engine_a.query(
            {'region': 'NA', 'day_of_week': 'sat'}, 'revenue', 'SUM')
        assert result == pytest.approx(DNA_NA_SAT_REVENUE, rel=1e-6)

    def test_mon_qty_count_dna(self, engine_a):
        result = engine_a.query({'day_of_week': 'mon'}, 'quantity', 'COUNT')
        assert result == pytest.approx(DNA_MON_QTY_COUNT, rel=1e-6)

    def test_global_min_revenue_dna(self, engine_a):
        result = engine_a.query({}, 'revenue', 'MIN')
        assert result == pytest.approx(DNA_GLOBAL_MIN_REV, rel=1e-6)

    def test_na_clothing_mobile_fri_max_dna(self, engine_a):
        result = engine_a.query(
            {'region': 'NA', 'category': 'clothing',
             'channel': 'mobile', 'day_of_week': 'fri'},
            'revenue', 'MAX')
        assert result == pytest.approx(DNA_NA_CLOTH_MOB_FRI_MAX, rel=1e-6)

    def test_latam_home_wholesale_sum_dna(self, engine_a):
        result = engine_a.query(
            {'region': 'LATAM', 'category': 'home', 'channel': 'wholesale'},
            'revenue', 'SUM')
        assert result == pytest.approx(DNA_LATAM_HOME_WHSL_SUM, rel=1e-6)

    def test_nonexistent_value_returns_none(self, engine_a):
        result = engine_a.query({'region': 'NONEXISTENT'}, 'revenue', 'SUM')
        assert result is None


# ---------------------------------------------------------------------------
# Brute-force cross-check point queries
# ---------------------------------------------------------------------------

class TestBruteForcePointQueries:

    def test_unconstrained_sum_revenue(self, engine_a, data_a):
        expected = brute_force_query(data_a, {}, 'revenue', 'SUM')
        result = engine_a.query({}, 'revenue', 'SUM')
        assert result == pytest.approx(expected, rel=1e-6)

    def test_two_constraints_count(self, engine_a, data_a):
        c = {'region': 'EU', 'category': 'electronics'}
        expected = brute_force_query(data_a, c, 'revenue', 'COUNT')
        result = engine_a.query(c, 'revenue', 'COUNT')
        assert result == pytest.approx(expected, rel=1e-6)

    def test_three_constraints_min(self, engine_a, data_a):
        c = {'region': 'APAC', 'category': 'food', 'channel': 'web'}
        expected = brute_force_query(data_a, c, 'revenue', 'MIN')
        result = engine_a.query(c, 'revenue', 'MIN')
        assert result == pytest.approx(expected, rel=1e-6)

    def test_skip_middle_dimensions(self, engine_a, data_a):
        c = {'region': 'NA', 'day_of_week': 'sat'}
        expected = brute_force_query(data_a, c, 'revenue', 'SUM')
        result = engine_a.query(c, 'revenue', 'SUM')
        assert result == pytest.approx(expected, rel=1e-6)

    def test_only_last_dimension(self, engine_a, data_a):
        c = {'day_of_week': 'mon'}
        expected = brute_force_query(data_a, c, 'quantity', 'COUNT')
        result = engine_a.query(c, 'quantity', 'COUNT')
        assert result == pytest.approx(expected, rel=1e-6)

    def test_channel_constraint_no_star(self, engine_a, data_a):
        """Channel level has no star node; queries must still work."""
        c = {'region': 'LATAM', 'category': 'home', 'channel': 'wholesale'}
        expected = brute_force_query(data_a, c, 'revenue', 'SUM')
        result = engine_a.query(c, 'revenue', 'SUM')
        assert result == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# DNA group-by query tests — hardcoded expected values
# ---------------------------------------------------------------------------

class TestDNAGroupByQueries:

    def test_group_by_region_revenue_dna(self, engine_a):
        result = engine_a.group_by_query({}, 'region', 'revenue', 'SUM')
        assert set(result.keys()) == set(DNA_GB_REGION_REVENUE.keys())
        for k in DNA_GB_REGION_REVENUE:
            assert result[k] == pytest.approx(
                DNA_GB_REGION_REVENUE[k], rel=1e-6), f"region={k}"

    def test_group_by_category_na_dna(self, engine_a):
        result = engine_a.group_by_query(
            {'region': 'NA'}, 'category', 'revenue', 'SUM')
        assert set(result.keys()) == set(DNA_GB_CAT_NA_REVENUE.keys())
        for k in DNA_GB_CAT_NA_REVENUE:
            assert result[k] == pytest.approx(
                DNA_GB_CAT_NA_REVENUE[k], rel=1e-6), f"category={k}"


# ---------------------------------------------------------------------------
# Brute-force cross-check group-by queries
# ---------------------------------------------------------------------------

class TestBruteForceGroupByQueries:

    def _compare_group_by(self, result, expected):
        assert set(result.keys()) == set(expected.keys()), \
            f"Key mismatch: got {set(result.keys())}, expected {set(expected.keys())}"
        for k in expected:
            assert result[k] == pytest.approx(expected[k], rel=1e-6), \
                f"Mismatch for key '{k}'"

    def test_group_by_channel_count(self, engine_a, data_a):
        expected = brute_force_group_by(
            data_a, {'region': 'EU'}, 'channel', 'quantity', 'COUNT')
        result = engine_a.group_by_query(
            {'region': 'EU'}, 'channel', 'quantity', 'COUNT')
        self._compare_group_by(result, expected)

    def test_group_by_day_avg(self, engine_a, data_a):
        c = {'region': 'APAC', 'channel': 'web'}
        expected = brute_force_group_by(data_a, c, 'day_of_week', 'discount', 'AVG')
        result = engine_a.group_by_query(c, 'day_of_week', 'discount', 'AVG')
        self._compare_group_by(result, expected)

    def test_group_by_first_dim_constrained_later(self, engine_a, data_a):
        expected = brute_force_group_by(
            data_a, {'channel': 'store'}, 'region', 'revenue', 'MAX')
        result = engine_a.group_by_query(
            {'channel': 'store'}, 'region', 'revenue', 'MAX')
        self._compare_group_by(result, expected)

    def test_group_by_category_avg_discount(self, engine_a, data_a):
        expected = brute_force_group_by(
            data_a, {}, 'category', 'discount', 'AVG')
        result = engine_a.group_by_query(
            {}, 'category', 'discount', 'AVG')
        self._compare_group_by(result, expected)


# ---------------------------------------------------------------------------
# DNA merge tests — hardcoded expected values
# ---------------------------------------------------------------------------

class TestDNAMerge:

    def test_merged_document_count(self, merged_tree):
        assert merged_tree.document_count == 50000

    def test_merged_total_revenue_dna(self, merged_engine):
        result = merged_engine.query({}, 'revenue', 'SUM')
        assert result == pytest.approx(DNA_MERGED_TOTAL_REV, rel=1e-6)

    def test_merged_na_elec_count_dna(self, merged_engine):
        result = merged_engine.query(
            {'region': 'NA', 'category': 'electronics'}, 'revenue', 'COUNT')
        assert result == pytest.approx(DNA_MERGED_NA_ELEC_COUNT, rel=1e-6)

    def test_merged_eu_discount_avg_dna(self, merged_engine):
        """AVG after merge must weight by count, not average two averages."""
        result = merged_engine.query({'region': 'EU'}, 'discount', 'AVG')
        assert result == pytest.approx(DNA_MERGED_EU_DISC_AVG, rel=1e-6)

    def test_merged_books_web_min_dna(self, merged_engine):
        result = merged_engine.query(
            {'category': 'books', 'channel': 'web'}, 'revenue', 'MIN')
        assert result == pytest.approx(DNA_MERGED_BOOKS_WEB_MIN, rel=1e-6)

    def test_merged_books_web_max_dna(self, merged_engine):
        result = merged_engine.query(
            {'category': 'books', 'channel': 'web'}, 'revenue', 'MAX')
        assert result == pytest.approx(DNA_MERGED_BOOKS_WEB_MAX, rel=1e-6)

    def test_merged_gb_region_revenue_dna(self, merged_engine):
        result = merged_engine.group_by_query(
            {}, 'region', 'revenue', 'SUM')
        assert set(result.keys()) == set(DNA_MERGED_GB_REGION_REV.keys())
        for k in DNA_MERGED_GB_REGION_REV:
            assert result[k] == pytest.approx(
                DNA_MERGED_GB_REGION_REV[k], rel=1e-6), f"region={k}"

    def test_merged_gb_cat_mobile_disc_avg_dna(self, merged_engine):
        result = merged_engine.group_by_query(
            {'channel': 'mobile'}, 'category', 'discount', 'AVG')
        assert set(result.keys()) == set(DNA_MERGED_GB_CAT_MOB_DISC_AVG.keys())
        for k in DNA_MERGED_GB_CAT_MOB_DISC_AVG:
            assert result[k] == pytest.approx(
                DNA_MERGED_GB_CAT_MOB_DISC_AVG[k], rel=1e-6), f"cat={k}"

    def test_merged_star_node_present(self, merged_tree):
        assert '*' in merged_tree.children

    def test_merged_non_star_sum(self, merged_tree):
        total = sum(c.document_count
                    for k, c in merged_tree.children.items() if k != '*')
        assert total == merged_tree.document_count


# ---------------------------------------------------------------------------
# Brute-force cross-check merge queries
# ---------------------------------------------------------------------------

class TestBruteForceMerge:

    def test_merged_unconstrained_sum(self, merged_engine, combined_data):
        expected = brute_force_query(combined_data, {}, 'revenue', 'SUM')
        result = merged_engine.query({}, 'revenue', 'SUM')
        assert result == pytest.approx(expected, rel=1e-6)

    def test_merged_constrained_count(self, merged_engine, combined_data):
        c = {'region': 'NA', 'category': 'electronics'}
        expected = brute_force_query(combined_data, c, 'revenue', 'COUNT')
        result = merged_engine.query(c, 'revenue', 'COUNT')
        assert result == pytest.approx(expected, rel=1e-6)

    def test_merged_group_by_category_avg(self, merged_engine, combined_data):
        c = {'channel': 'mobile'}
        expected = brute_force_group_by(
            combined_data, c, 'category', 'discount', 'AVG')
        result = merged_engine.group_by_query(
            c, 'category', 'discount', 'AVG')
        assert set(result.keys()) == set(expected.keys())
        for k in expected:
            assert result[k] == pytest.approx(expected[k], rel=1e-6)
