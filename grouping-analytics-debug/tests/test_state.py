
import pytest
import psycopg2
from decimal import Decimal


@pytest.fixture(scope="module")
def db():
    conn = psycopg2.connect(dbname="analytics_db", user="postgres")
    conn.autocommit = True
    yield conn
    conn.close()


def q(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Function: margin_category — correct formula and boundary behavior
# ---------------------------------------------------------------------------
class TestMarginCategory:
    def test_standard_margin(self, db):
        """(1200-800)/1200*100 = 33.33% → 'standard', NOT 'high' (markup=50%)"""
        rows = q(db, "SELECT margin_category(800, 1200)")
        assert rows[0][0] == "standard", (
            f"margin_category(800,1200) should be 'standard' (33.33% margin), "
            f"got '{rows[0][0]}'"
        )

    def test_high_margin(self, db):
        """(2200-900)/2200*100 = 59.09% → 'high'"""
        rows = q(db, "SELECT margin_category(900, 2200)")
        assert rows[0][0] == "high"

    def test_premium_boundary(self, db):
        """(1500-600)/1500*100 = exactly 60% → 'premium' (boundary is < 60 for high)"""
        rows = q(db, "SELECT margin_category(600, 1500)")
        assert rows[0][0] == "premium", (
            f"Exactly 60% should map to 'premium', got '{rows[0][0]}'"
        )

    def test_low_margin(self, db):
        """(850-750)/850*100 = 11.76% → 'low'"""
        rows = q(db, "SELECT margin_category(750, 850)")
        assert rows[0][0] == "low"

    def test_premium_margin(self, db):
        """(350-100)/350*100 = 71.43% → 'premium'"""
        rows = q(db, "SELECT margin_category(100, 350)")
        assert rows[0][0] == "premium"

    def test_zero_revenue(self, db):
        rows = q(db, "SELECT margin_category(100, 0)")
        assert rows[0][0] == "undefined"


# ---------------------------------------------------------------------------
# View: v_sales_enriched — correct arg order, running total frame
# ---------------------------------------------------------------------------
class TestSalesEnriched:
    def test_row_count(self, db):
        rows = q(db, "SELECT COUNT(*) FROM v_sales_enriched")
        assert rows[0][0] == 24

    def test_margin_tier_standard(self, db):
        """id=1: amount=1200, cost=800 → margin 33.33% → 'standard'"""
        rows = q(db, "SELECT margin_tier FROM v_sales_enriched WHERE id = 1")
        assert rows[0][0] == "standard"

    def test_margin_tier_premium_boundary(self, db):
        """id=19: amount=1500, cost=600 → margin exactly 60% → 'premium'"""
        rows = q(db, "SELECT margin_tier FROM v_sales_enriched WHERE id = 19")
        assert rows[0][0] == "premium"

    def test_margin_tier_high(self, db):
        """id=7: amount=2200, cost=900 → margin 59.09% → 'high'"""
        rows = q(db, "SELECT margin_tier FROM v_sales_enriched WHERE id = 7")
        assert rows[0][0] == "high"

    def test_margin_tier_low(self, db):
        """id=2: amount=850, cost=750 → margin 11.76% → 'low'"""
        rows = q(db, "SELECT margin_tier FROM v_sales_enriched WHERE id = 2")
        assert rows[0][0] == "low"

    def test_running_total_first_north(self, db):
        """First North sale (earliest date) should have running_total = its own amount"""
        rows = q(db, "SELECT running_total FROM v_sales_enriched WHERE id = 1")
        assert rows[0][0] == Decimal("1200.00")

    def test_running_total_mid_north(self, db):
        """id=3 (North, Feb 10): running_total = 1200+850+350 = 2400"""
        rows = q(db, "SELECT running_total FROM v_sales_enriched WHERE id = 3")
        assert rows[0][0] == Decimal("2400.00")

    def test_running_total_last_north(self, db):
        """id=20 (North, May 25): last North sale, running_total = 4885"""
        rows = q(db, "SELECT running_total FROM v_sales_enriched WHERE id = 20")
        assert rows[0][0] == Decimal("4885.00")

    def test_running_total_varies_within_region(self, db):
        """Running total should differ across rows — not be the partition total."""
        rows = q(db,
            "SELECT COUNT(DISTINCT running_total) FROM v_sales_enriched "
            "WHERE region = 'North'")
        assert rows[0][0] == 8, (
            "Each North row should have a different running total (8 distinct values)"
        )

    def test_running_total_mid_south(self, db):
        """id=8 (South, Feb 22, 3rd South sale): running_total = 2200+520+1650 = 4370"""
        rows = q(db, "SELECT running_total FROM v_sales_enriched WHERE id = 8")
        assert rows[0][0] == Decimal("4370.00")


# ---------------------------------------------------------------------------
# View: v_cube_analysis — CUBE not ROLLUP, correct labels
# ---------------------------------------------------------------------------
class TestCubeAnalysis:
    def test_row_count_is_16(self, db):
        rows = q(db, "SELECT COUNT(*) FROM v_cube_analysis")
        assert rows[0][0] == 16, (
            f"CUBE(region,category) produces 16 rows, got {rows[0][0]}"
        )

    def test_has_category_subtotals(self, db):
        """CUBE produces category-only subtotals (g_region=1, g_category=0)."""
        rows = q(db,
            "SELECT COUNT(*) FROM v_cube_analysis "
            "WHERE g_region = 1 AND g_category = 0")
        assert rows[0][0] == 3

    def test_region_subtotal_label(self, db):
        """g_region=0, g_category=1 → GROUPING=1 → 'by_region'."""
        rows = q(db,
            "SELECT DISTINCT level_label FROM v_cube_analysis "
            "WHERE g_region = 0 AND g_category = 1")
        assert len(rows) == 1
        assert rows[0][0] == "by_region", (
            f"Region subtotals should be labeled 'by_region', got '{rows[0][0]}'"
        )

    def test_category_subtotal_label(self, db):
        """g_region=1, g_category=0 → GROUPING=2 → 'by_category'."""
        rows = q(db,
            "SELECT DISTINCT level_label FROM v_cube_analysis "
            "WHERE g_region = 1 AND g_category = 0")
        assert len(rows) == 1
        assert rows[0][0] == "by_category", (
            f"Category subtotals should be labeled 'by_category', got '{rows[0][0]}'"
        )

    def test_grand_total(self, db):
        rows = q(db,
            "SELECT total_revenue, total_cost, num_txns FROM v_cube_analysis "
            "WHERE g_region = 1 AND g_category = 1")
        assert len(rows) == 1
        assert rows[0][0] == Decimal("18395.00")
        assert rows[0][1] == Decimal("9915.00")
        assert int(rows[0][2]) == 24

    def test_electronics_category_total(self, db):
        """Category subtotal for Electronics: 13150."""
        rows = q(db,
            "SELECT total_revenue FROM v_cube_analysis "
            "WHERE g_region = 1 AND g_category = 0 AND category = 'Electronics'")
        assert len(rows) == 1
        assert rows[0][0] == Decimal("13150.00")


# ---------------------------------------------------------------------------
# View: v_channel_metrics — case-sensitive, DISTINCT, strict >
# ---------------------------------------------------------------------------
class TestChannelMetrics:
    def test_row_count(self, db):
        rows = q(db, "SELECT COUNT(*) FROM v_channel_metrics")
        assert rows[0][0] == 4

    def test_north_online_revenue(self, db):
        """North online: 1200+350+120+1500 = 3170 (case-sensitive 'online')."""
        rows = q(db,
            "SELECT online_revenue FROM v_channel_metrics WHERE region = 'North'")
        assert rows[0][0] == Decimal("3170.00")

    def test_grand_online_revenue(self, db):
        rows = q(db,
            "SELECT online_revenue FROM v_channel_metrics WHERE region IS NULL")
        assert rows[0][0] == Decimal("11250.00")

    def test_north_retail_revenue(self, db):
        """North retail: 850+480+95+290 = 1715."""
        rows = q(db,
            "SELECT retail_revenue FROM v_channel_metrics WHERE region = 'North'")
        assert rows[0][0] == Decimal("1715.00")

    def test_grand_num_categories(self, db):
        """COUNT(DISTINCT category) across all rows = 3, not 24."""
        rows = q(db,
            "SELECT num_categories FROM v_channel_metrics WHERE region IS NULL")
        assert int(rows[0][0]) == 3

    def test_north_high_qty(self, db):
        """North high_qty (strict > 5): rows with qty 8,10,7 → 480+120+95 = 695."""
        rows = q(db,
            "SELECT high_qty_revenue FROM v_channel_metrics WHERE region = 'North'")
        assert rows[0][0] == Decimal("695.00"), (
            f"Expected 695 (qty>5), got {rows[0][0]}"
        )

    def test_grand_high_qty(self, db):
        rows = q(db,
            "SELECT high_qty_revenue FROM v_channel_metrics WHERE region IS NULL")
        assert rows[0][0] == Decimal("4175.00")

    def test_north_profit_margin(self, db):
        """North: (4885-2895)*100/4885 = 40.74."""
        rows = q(db,
            "SELECT profit_margin_pct FROM v_channel_metrics WHERE region = 'North'")
        assert rows[0][0] == Decimal("40.74")

    def test_grand_profit_margin(self, db):
        """Grand: (18395-9915)*100/18395 = 46.10."""
        rows = q(db,
            "SELECT profit_margin_pct FROM v_channel_metrics WHERE region IS NULL")
        assert rows[0][0] == Decimal("46.10")


# ---------------------------------------------------------------------------
# View: v_threshold_regions — correct threshold and denominator
# ---------------------------------------------------------------------------
class TestThresholdRegions:
    def test_row_count(self, db):
        rows = q(db, "SELECT COUNT(*) FROM v_threshold_regions")
        assert rows[0][0] == 2, (
            f"Only South (7600) and grand total (18395) exceed threshold ~6132, "
            f"got {rows[0][0]} rows"
        )

    def test_south_included(self, db):
        rows = q(db,
            "SELECT region FROM v_threshold_regions WHERE region = 'South'")
        assert len(rows) == 1

    def test_grand_included(self, db):
        rows = q(db,
            "SELECT region FROM v_threshold_regions WHERE region IS NULL")
        assert len(rows) == 1

    def test_north_excluded(self, db):
        rows = q(db,
            "SELECT region FROM v_threshold_regions WHERE region = 'North'")
        assert len(rows) == 0, "North (4885) < threshold (~6132)"

    def test_west_excluded(self, db):
        rows = q(db,
            "SELECT region FROM v_threshold_regions WHERE region = 'West'")
        assert len(rows) == 0, "West (5910) < threshold (~6132)"

    def test_south_pct(self, db):
        """South pct_of_total: 7600*100/18395 = 41.32 (denominator is revenue)."""
        rows = q(db,
            "SELECT pct_of_total FROM v_threshold_regions WHERE region = 'South'")
        assert rows[0][0] == Decimal("41.32")

    def test_grand_pct(self, db):
        """Grand total pct_of_total must be 100.00."""
        rows = q(db,
            "SELECT pct_of_total FROM v_threshold_regions WHERE region IS NULL")
        assert rows[0][0] == Decimal("100.00")


# ---------------------------------------------------------------------------
# View: v_quarterly_growth — from-scratch implementation
# ---------------------------------------------------------------------------
class TestQuarterlyGrowth:
    def test_row_count(self, db):
        rows = q(db, "SELECT COUNT(*) FROM v_quarterly_growth")
        assert rows[0][0] == 8, (
            f"Expected 8 rows (5 detail + 2 quarter subtotals + 1 grand), "
            f"got {rows[0][0]}"
        )

    def test_q1_north_revenue(self, db):
        """Q1 North: 1200+850+350+480+120+95 = 3095."""
        rows = q(db,
            "SELECT total_revenue FROM v_quarterly_growth "
            "WHERE quarter_num = 1 AND region = 'North'")
        assert len(rows) == 1
        assert rows[0][0] == Decimal("3095.00")

    def test_q1_south_revenue(self, db):
        """Q1 South: 2200+1650+520+710+180+240 = 5500."""
        rows = q(db,
            "SELECT total_revenue FROM v_quarterly_growth "
            "WHERE quarter_num = 1 AND region = 'South'")
        assert len(rows) == 1
        assert rows[0][0] == Decimal("5500.00")

    def test_q2_west_revenue(self, db):
        """Q2 West: 1800+950+620+430+310+150+550+1100 = 5910."""
        rows = q(db,
            "SELECT total_revenue FROM v_quarterly_growth "
            "WHERE quarter_num = 2 AND region = 'West'")
        assert len(rows) == 1
        assert rows[0][0] == Decimal("5910.00")

    def test_q2_subtotal_revenue(self, db):
        """Q2 quarter subtotal: 1790+2100+5910 = 9800."""
        rows = q(db,
            "SELECT total_revenue FROM v_quarterly_growth "
            "WHERE quarter_num = 2 AND g_region = 1 AND g_quarter = 0")
        assert len(rows) == 1
        assert rows[0][0] == Decimal("9800.00")

    def test_north_growth(self, db):
        """North Q1→Q2: (1790-3095)/3095*100 = -42.16."""
        rows = q(db,
            "SELECT growth_rate_pct FROM v_quarterly_growth "
            "WHERE quarter_num = 2 AND region = 'North'")
        assert len(rows) == 1
        assert rows[0][0] == Decimal("-42.16")

    def test_south_growth(self, db):
        """South Q1→Q2: (2100-5500)/5500*100 = -61.82."""
        rows = q(db,
            "SELECT growth_rate_pct FROM v_quarterly_growth "
            "WHERE quarter_num = 2 AND region = 'South'")
        assert len(rows) == 1
        assert rows[0][0] == Decimal("-61.82")

    def test_subtotal_growth(self, db):
        """Quarter subtotal Q1→Q2: (9800-8595)/8595*100 = 14.02."""
        rows = q(db,
            "SELECT growth_rate_pct FROM v_quarterly_growth "
            "WHERE quarter_num = 2 AND g_region = 1 AND g_quarter = 0")
        assert len(rows) == 1
        assert rows[0][0] == Decimal("14.02")

    def test_west_no_prior(self, db):
        """West has no Q1 data, so Q2 growth should be NULL."""
        rows = q(db,
            "SELECT growth_rate_pct FROM v_quarterly_growth "
            "WHERE quarter_num = 2 AND region = 'West'")
        assert len(rows) == 1
        assert rows[0][0] is None

    def test_grand_total(self, db):
        """Grand total row: revenue=18395, growth=NULL."""
        rows = q(db,
            "SELECT total_revenue, growth_rate_pct FROM v_quarterly_growth "
            "WHERE g_quarter = 1")
        assert len(rows) == 1
        assert rows[0][0] == Decimal("18395.00")
        assert rows[0][1] is None

    def test_q1_north_margin(self, db):
        """Q1 North margin: (3095-2115)/3095*100 = 31.66."""
        rows = q(db,
            "SELECT profit_margin_pct FROM v_quarterly_growth "
            "WHERE quarter_num = 1 AND region = 'North'")
        assert rows[0][0] == Decimal("31.66")

    def test_q2_subtotal_margin(self, db):
        """Q2 subtotal margin: (9800-4950)/9800*100 = 49.49."""
        rows = q(db,
            "SELECT profit_margin_pct FROM v_quarterly_growth "
            "WHERE quarter_num = 2 AND g_region = 1 AND g_quarter = 0")
        assert rows[0][0] == Decimal("49.49")


# ---------------------------------------------------------------------------
# View: v_ranked_tiers — correct partition, filter, cascading deps
# ---------------------------------------------------------------------------
class TestRankedTiers:
    def test_row_count(self, db):
        rows = q(db, "SELECT COUNT(*) FROM v_ranked_tiers")
        assert rows[0][0] == 12, (
            f"Top 3 per 4 tiers = 12 rows, got {rows[0][0]}"
        )

    def test_all_tiers_present(self, db):
        rows = q(db,
            "SELECT COUNT(DISTINCT margin_tier) FROM v_ranked_tiers")
        assert rows[0][0] == 4

    def test_high_tier_top(self, db):
        """Electronics dominates high tier: 2200 is rank 1."""
        rows = q(db,
            "SELECT amount, region FROM v_ranked_tiers "
            "WHERE margin_tier = 'high' AND tier_rank = 1")
        assert len(rows) == 1
        assert rows[0][0] == Decimal("2200.00")
        assert rows[0][1] == "South"

    def test_premium_tier_top(self, db):
        """Premium top: 1500 (North Electronics, 60% margin boundary)."""
        rows = q(db,
            "SELECT amount FROM v_ranked_tiers "
            "WHERE margin_tier = 'premium' AND tier_rank = 1")
        assert len(rows) == 1
        assert rows[0][0] == Decimal("1500.00")

    def test_standard_tier_top(self, db):
        """Standard top: 1650 (South Electronics)."""
        rows = q(db,
            "SELECT amount FROM v_ranked_tiers "
            "WHERE margin_tier = 'standard' AND tier_rank = 1")
        assert len(rows) == 1
        assert rows[0][0] == Decimal("1650.00")

    def test_low_tier_top(self, db):
        """Low top: 850 (North Electronics retail)."""
        rows = q(db,
            "SELECT amount FROM v_ranked_tiers "
            "WHERE margin_tier = 'low' AND tier_rank = 1")
        assert len(rows) == 1
        assert rows[0][0] == Decimal("850.00")

    def test_tier_rank_max_is_3(self, db):
        """No row should have tier_rank > 3."""
        rows = q(db,
            "SELECT MAX(tier_rank) FROM v_ranked_tiers")
        assert int(rows[0][0]) == 3
