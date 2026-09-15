
import json
import os

import duckdb


def _compute_expected():
    """Compute expected values from clean TPC-H SF=0.1 data (ground truth)."""
    work = duckdb.connect()
    work.execute("LOAD tpch")
    work.execute("CALL dbgen(sf=0.1)")

    # Q1: revenue_by_region
    rev = work.execute("""
        SELECT r_name, ROUND(SUM(l_extendedprice * (1 - l_discount)), 2) as revenue
        FROM lineitem
        JOIN orders ON l_orderkey = o_orderkey
        JOIN customer ON o_custkey = c_custkey
        JOIN nation ON c_nationkey = n_nationkey
        JOIN region ON n_regionkey = r_regionkey
        GROUP BY r_name
        ORDER BY r_name
    """).fetchall()
    revenue_by_region = {str(r): float(v) for r, v in rev}

    # Q2: top_supplier_by_availability
    sup = work.execute("""
        SELECT s_name
        FROM partsupp
        JOIN supplier ON ps_suppkey = s_suppkey
        GROUP BY s_name
        ORDER BY SUM(ps_availqty) DESC, s_name ASC
        LIMIT 1
    """).fetchone()
    top_supplier = str(sup[0]).strip()

    # Q3: returned_revenue_fraction
    frac = work.execute("""
        SELECT ROUND(
            SUM(CASE WHEN l_returnflag = 'R'
                THEN l_extendedprice * (1 - l_discount) ELSE 0 END) /
            SUM(l_extendedprice * (1 - l_discount)),
            6
        )
        FROM lineitem
    """).fetchone()
    returned_fraction = float(frac[0])

    # Q4: urgent_order_revenue_1995
    urg = work.execute("""
        SELECT ROUND(SUM(o_totalprice), 2)
        FROM orders
        WHERE o_orderpriority = '1-URGENT'
          AND o_orderdate >= DATE '1995-01-01'
          AND o_orderdate < DATE '1996-01-01'
    """).fetchone()
    urgent_revenue = float(urg[0])

    # Q5: avg_supplycost_europe
    avg_sc = work.execute("""
        SELECT ROUND(AVG(ps_supplycost), 2)
        FROM partsupp
        JOIN supplier ON ps_suppkey = s_suppkey
        JOIN nation ON s_nationkey = n_nationkey
        JOIN region ON n_regionkey = r_regionkey
        WHERE r_name = 'EUROPE'
    """).fetchone()
    avg_supplycost = float(avg_sc[0])

    # Q6: priority_fulfillment_rate (1995 orders)
    rates = work.execute("""
        SELECT o_orderpriority,
               ROUND(
                   SUM(CASE WHEN l_receiptdate <= l_commitdate THEN 1 ELSE 0 END)::DOUBLE /
                   COUNT(*)::DOUBLE,
                   4
               ) as fulfillment_rate
        FROM lineitem
        JOIN orders ON l_orderkey = o_orderkey
        WHERE o_orderdate >= DATE '1995-01-01' AND o_orderdate < DATE '1996-01-01'
        GROUP BY o_orderpriority
        ORDER BY o_orderpriority
    """).fetchall()
    priority_rate = {str(p): float(r) for p, r in rates}

    work.close()

    return {
        'revenue_by_region': revenue_by_region,
        'top_supplier_by_availability': top_supplier,
        'returned_revenue_fraction': returned_fraction,
        'urgent_order_revenue_1995': urgent_revenue,
        'avg_supplycost_europe': avg_supplycost,
        'priority_fulfillment_rate': priority_rate,
    }


_cache = {}


def _get_expected():
    if not _cache:
        _cache.update(_compute_expected())
    return _cache


def _load_results():
    with open('/app/results.json') as f:
        return json.load(f)


class TestResultsExist:
    def test_file_exists(self):
        assert os.path.exists('/app/results.json'), "/app/results.json not found"

    def test_valid_json(self):
        data = _load_results()
        assert isinstance(data, dict), "results.json must be a JSON object"

    def test_has_all_keys(self):
        data = _load_results()
        required = [
            'revenue_by_region',
            'top_supplier_by_availability',
            'returned_revenue_fraction',
            'urgent_order_revenue_1995',
            'avg_supplycost_europe',
            'priority_fulfillment_rate',
        ]
        for key in required:
            assert key in data, f"Missing key: {key}"


class TestRevenueByRegion:
    """Tests correct lineitem price reconciliation (must detect and correct
    systematic price bias from fulfillment source)."""

    TOLERANCE = 2000.0  # tight enough to reject 5% inflation (~150K error)

    def test_is_dict(self):
        data = _load_results()
        assert isinstance(data['revenue_by_region'], dict)

    def test_has_five_regions(self):
        data = _load_results()
        assert len(data['revenue_by_region']) == 5, \
            f"Expected 5 regions, got {len(data['revenue_by_region'])}"

    def test_africa_revenue(self):
        data = _load_results()
        exp = _get_expected()['revenue_by_region']['AFRICA']
        actual = data['revenue_by_region'].get('AFRICA')
        assert actual is not None, "Missing region AFRICA"
        assert abs(float(actual) - exp) < self.TOLERANCE, \
            f"AFRICA: expected ~{exp:.2f}, got {actual}"

    def test_america_revenue(self):
        data = _load_results()
        exp = _get_expected()['revenue_by_region']['AMERICA']
        actual = data['revenue_by_region'].get('AMERICA')
        assert actual is not None, "Missing region AMERICA"
        assert abs(float(actual) - exp) < self.TOLERANCE, \
            f"AMERICA: expected ~{exp:.2f}, got {actual}"

    def test_asia_revenue(self):
        data = _load_results()
        exp = _get_expected()['revenue_by_region']['ASIA']
        actual = data['revenue_by_region'].get('ASIA')
        assert actual is not None, "Missing region ASIA"
        assert abs(float(actual) - exp) < self.TOLERANCE, \
            f"ASIA: expected ~{exp:.2f}, got {actual}"

    def test_europe_revenue(self):
        data = _load_results()
        exp = _get_expected()['revenue_by_region']['EUROPE']
        actual = data['revenue_by_region'].get('EUROPE')
        assert actual is not None, "Missing region EUROPE"
        assert abs(float(actual) - exp) < self.TOLERANCE, \
            f"EUROPE: expected ~{exp:.2f}, got {actual}"

    def test_middle_east_revenue(self):
        data = _load_results()
        exp = _get_expected()['revenue_by_region']['MIDDLE EAST']
        actual = data['revenue_by_region'].get('MIDDLE EAST')
        assert actual is not None, "Missing region MIDDLE EAST"
        assert abs(float(actual) - exp) < self.TOLERANCE, \
            f"MIDDLE EAST: expected ~{exp:.2f}, got {actual}"


class TestTopSupplierByAvailability:
    """Tests partsupp data recovery (table missing from warehouse)."""

    def test_correct_supplier(self):
        data = _load_results()
        exp = _get_expected()['top_supplier_by_availability']
        actual = str(data['top_supplier_by_availability']).strip()
        assert actual == exp, f"Expected '{exp}', got '{actual}'"


class TestReturnedRevenueFraction:
    """Tests recovery of deleted returned line items and correct price
    reconciliation. Fraction is ratio-based so it primarily tests
    row completeness, not absolute price accuracy."""

    TOLERANCE = 0.002

    def test_correct_fraction(self):
        data = _load_results()
        exp = _get_expected()['returned_revenue_fraction']
        actual = float(data['returned_revenue_fraction'])
        assert abs(actual - exp) < self.TOLERANCE, \
            f"Expected ~{exp:.6f}, got {actual:.6f}"


class TestUrgentOrderRevenue1995:
    """Tests order price correction (warehouse has truncated prices)."""

    TOLERANCE = 100.0  # truncation error is ~$2500, valid approach < $1

    def test_correct_value(self):
        data = _load_results()
        exp = _get_expected()['urgent_order_revenue_1995']
        actual = float(data['urgent_order_revenue_1995'])
        assert abs(actual - exp) < self.TOLERANCE, \
            f"Expected ~{exp:.2f}, got {actual:.2f}"


class TestAvgSupplycostEurope:
    """Tests partsupp recovery combined with geographic joins."""

    TOLERANCE = 1.0

    def test_correct_value(self):
        data = _load_results()
        exp = _get_expected()['avg_supplycost_europe']
        actual = float(data['avg_supplycost_europe'])
        assert abs(actual - exp) < self.TOLERANCE, \
            f"Expected ~{exp:.2f}, got {actual:.2f}"


class TestPriorityFulfillmentRate:
    """Tests lineitem completeness — missing rows change fulfillment rates."""

    TOLERANCE = 0.01

    def test_is_dict(self):
        data = _load_results()
        assert isinstance(data['priority_fulfillment_rate'], dict)

    def test_has_five_priorities(self):
        data = _load_results()
        assert len(data['priority_fulfillment_rate']) == 5, \
            f"Expected 5 priorities, got {len(data['priority_fulfillment_rate'])}"

    def test_urgent_rate(self):
        data = _load_results()
        exp = _get_expected()['priority_fulfillment_rate']['1-URGENT']
        actual = data['priority_fulfillment_rate'].get('1-URGENT')
        assert actual is not None, "Missing priority 1-URGENT"
        assert abs(float(actual) - exp) < self.TOLERANCE, \
            f"1-URGENT: expected ~{exp:.4f}, got {actual}"

    def test_high_rate(self):
        data = _load_results()
        exp = _get_expected()['priority_fulfillment_rate']['2-HIGH']
        actual = data['priority_fulfillment_rate'].get('2-HIGH')
        assert actual is not None, "Missing priority 2-HIGH"
        assert abs(float(actual) - exp) < self.TOLERANCE, \
            f"2-HIGH: expected ~{exp:.4f}, got {actual}"

    def test_medium_rate(self):
        data = _load_results()
        exp = _get_expected()['priority_fulfillment_rate']['3-MEDIUM']
        actual = data['priority_fulfillment_rate'].get('3-MEDIUM')
        assert actual is not None, "Missing priority 3-MEDIUM"
        assert abs(float(actual) - exp) < self.TOLERANCE, \
            f"3-MEDIUM: expected ~{exp:.4f}, got {actual}"

    def test_not_specified_rate(self):
        data = _load_results()
        exp = _get_expected()['priority_fulfillment_rate']['4-NOT SPECIFIED']
        actual = data['priority_fulfillment_rate'].get('4-NOT SPECIFIED')
        assert actual is not None, "Missing priority 4-NOT SPECIFIED"
        assert abs(float(actual) - exp) < self.TOLERANCE, \
            f"4-NOT SPECIFIED: expected ~{exp:.4f}, got {actual}"

    def test_low_rate(self):
        data = _load_results()
        exp = _get_expected()['priority_fulfillment_rate']['5-LOW']
        actual = data['priority_fulfillment_rate'].get('5-LOW')
        assert actual is not None, "Missing priority 5-LOW"
        assert abs(float(actual) - exp) < self.TOLERANCE, \
            f"5-LOW: expected ~{exp:.4f}, got {actual}"
