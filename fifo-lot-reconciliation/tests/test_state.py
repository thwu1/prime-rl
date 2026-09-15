
import subprocess
import re


JOURNAL = "/app/portfolio.journal"


def run_hledger(*args):
    """Run an hledger command and return (stdout, stderr, returncode)."""
    cmd = ["hledger", "-f", JOURNAL] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout, result.stderr, result.returncode


def sum_commodity(stdout, commodity):
    """Sum all integer amounts of a given commodity from hledger balance output."""
    total = 0
    for line in stdout.strip().split("\n"):
        match = re.search(r"(-?\d+)\s+" + re.escape(commodity), line)
        if match:
            total += int(match.group(1))
    return total


def parse_dollar_amount(text):
    """Extract the first dollar amount from hledger output text.

    Handles formats like $91330.00, $-600.00, -$600.00
    """
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("---") or line.startswith("==="):
            continue
        cleaned = line.replace(",", "")
        match = re.search(r"-?\$-?[\d]+\.?\d*", cleaned)
        if match:
            return float(match.group().replace("$", ""))
    return None


# ---------------------------------------------------------------------------
# Validity
# ---------------------------------------------------------------------------
class TestJournalValidity:
    def test_journal_parses_without_errors(self):
        """The journal must parse and pass all checks."""
        stdout, stderr, rc = run_hledger("check")
        assert rc == 0, f"hledger check failed:\n{stderr}"

    def test_balance_report_succeeds(self):
        """hledger bal must run without errors."""
        stdout, stderr, rc = run_hledger("bal")
        assert rc == 0, f"hledger bal failed:\n{stderr}"


# ---------------------------------------------------------------------------
# Cash balance
# ---------------------------------------------------------------------------
class TestCashBalance:
    def test_cash_balance(self):
        """Cash balance must be $91,330.00."""
        stdout, stderr, rc = run_hledger("bal", "assets:broker:cash", "-N")
        assert rc == 0, f"hledger failed:\n{stderr}"
        amount = parse_dollar_amount(stdout)
        assert amount is not None and abs(amount - 91330.0) < 0.01, (
            f"Expected cash $91,330.00, got:\n{stdout}"
        )


# ---------------------------------------------------------------------------
# APEX lot positions
# ---------------------------------------------------------------------------
class TestApexPositions:
    def test_total_apex_shares(self):
        """Total APEX holdings should be 330 shares."""
        stdout, stderr, rc = run_hledger(
            "bal", "assets:broker:apex", "-N", "--flat"
        )
        assert rc == 0, f"hledger failed:\n{stderr}"
        total = sum_commodity(stdout, "APEX")
        assert total == 330, f"Expected 330 APEX total, got {total}\n{stdout}"

    def test_gift_lot_depleted(self):
        """Gift lot (2020-06-15) must be fully sold: 0 APEX remaining."""
        stdout, stderr, rc = run_hledger(
            "bal", "assets:broker:apex:2020-06-15", "-N", "--flat", "-E"
        )
        assert rc == 0, f"hledger failed:\n{stderr}"
        total = sum_commodity(stdout, "APEX")
        assert total == 0, (
            f"Gift lot 2020-06-15 should be 0 APEX, got {total}\n{stdout}"
        )

    def test_jan_lot_has_250_shares(self):
        """Jan 15 lot (post-split) should have 250 APEX."""
        stdout, stderr, rc = run_hledger(
            "bal", "assets:broker:apex:2024-01-15", "-N", "--flat"
        )
        assert rc == 0, f"hledger failed:\n{stderr}"
        total = sum_commodity(stdout, "APEX")
        assert total == 250, (
            f"Jan 15 post-split lot should have 250 APEX, got {total}\n{stdout}"
        )

    def test_wash_lot_has_80_shares(self):
        """Wash sale replacement lot (2024-08-20) should have 80 APEX."""
        stdout, stderr, rc = run_hledger(
            "bal", "assets:broker:apex:2024-08-20", "-N", "--flat"
        )
        assert rc == 0, f"hledger failed:\n{stderr}"
        total = sum_commodity(stdout, "APEX")
        assert total == 80, (
            f"Wash sale lot 2024-08-20 should have 80 APEX, got {total}\n{stdout}"
        )


# ---------------------------------------------------------------------------
# BOLT lot positions
# ---------------------------------------------------------------------------
class TestBoltPositions:
    def test_total_bolt_shares(self):
        """Total BOLT holdings should be 210 shares."""
        stdout, stderr, rc = run_hledger(
            "bal", "assets:broker:bolt", "-N", "--flat"
        )
        assert rc == 0, f"hledger failed:\n{stderr}"
        total = sum_commodity(stdout, "BOLT")
        assert total == 210, f"Expected 210 BOLT total, got {total}\n{stdout}"

    def test_bolt_lot1_has_170(self):
        """BOLT lot 1 (2024-03-01) should have 170 BOLT."""
        stdout, stderr, rc = run_hledger(
            "bal", "assets:broker:bolt:2024-03-01", "-N", "--flat"
        )
        assert rc == 0, f"hledger failed:\n{stderr}"
        total = sum_commodity(stdout, "BOLT")
        assert total == 170, (
            f"BOLT lot 2024-03-01 should have 170, got {total}\n{stdout}"
        )

    def test_bolt_lot2_has_40(self):
        """BOLT lot 2 (2024-11-15) should have 40 BOLT."""
        stdout, stderr, rc = run_hledger(
            "bal", "assets:broker:bolt:2024-11-15", "-N", "--flat"
        )
        assert rc == 0, f"hledger failed:\n{stderr}"
        total = sum_commodity(stdout, "BOLT")
        assert total == 40, (
            f"BOLT lot 2024-11-15 should have 40, got {total}\n{stdout}"
        )


# ---------------------------------------------------------------------------
# Capital gains
# ---------------------------------------------------------------------------
class TestCapitalGains:
    def test_short_term_gains(self):
        """Net realized short-term gains must be $600.00.

        This value uniquely confirms the wash sale was applied correctly:
        without wash sale adjustment the ST gains would be $360, not $600.
        """
        stdout, stderr, rc = run_hledger(
            "bal", "revenues:gains:short-term", "-N"
        )
        assert rc == 0, f"hledger failed:\n{stderr}"
        amount = parse_dollar_amount(stdout)
        assert amount is not None and abs(abs(amount) - 600.0) < 0.01, (
            f"Expected $600.00 short-term gains, got:\n{stdout}"
        )

    def test_long_term_gains(self):
        """Net realized long-term gains must be $1,750.00.

        Only correct if the gift lot (donor date 2020-06-15) is classified
        as long-term using the donor's holding period.
        """
        stdout, stderr, rc = run_hledger(
            "bal", "revenues:gains:long-term", "-N"
        )
        assert rc == 0, f"hledger failed:\n{stderr}"
        amount = parse_dollar_amount(stdout)
        assert amount is not None and abs(abs(amount) - 1750.0) < 0.01, (
            f"Expected $1,750.00 long-term gains, got:\n{stdout}"
        )

    def test_total_realized_gains(self):
        """Total realized gains (ST + LT) must be $2,350.00."""
        stdout, stderr, rc = run_hledger("bal", "revenues:gains")
        assert rc == 0, f"hledger failed:\n{stderr}"
        normalized = stdout.replace(",", "")
        assert "2350" in normalized, (
            f"Expected total gains $2,350.00, got:\n{stdout}"
        )

    def test_gains_are_credit(self):
        """Net gains should be negative (credit) in revenue accounts."""
        stdout, stderr, rc = run_hledger("bal", "revenues:gains")
        assert rc == 0, f"hledger failed:\n{stderr}"
        normalized = stdout.replace(",", "")
        assert "-" in normalized and "2350" in normalized, (
            f"Gains should be negative (credit), got:\n{stdout}"
        )

    def test_gains_separated_by_holding_period(self):
        """Short-term and long-term gains must be in separate accounts."""
        stdout, stderr, rc = run_hledger(
            "bal", "revenues:gains", "-N", "--flat"
        )
        assert rc == 0, f"hledger failed:\n{stderr}"
        assert "short-term" in stdout and "long-term" in stdout, (
            f"Must have both short-term and long-term gains accounts:\n{stdout}"
        )


# ---------------------------------------------------------------------------
# Wash sale
# ---------------------------------------------------------------------------
class TestWashSale:
    def test_wash_lot_adjusted_basis(self):
        """The wash sale lot must use adjusted basis $26.00/share.

        Market price was $23.00, but $240 disallowed loss / 80 shares = $3.00
        adjustment, making the per-share basis $26.00.
        """
        stdout, stderr, rc = run_hledger(
            "bal", "assets:broker:apex:2024-08-20", "-N", "--flat"
        )
        assert rc == 0, f"hledger failed:\n{stderr}"
        assert "$26" in stdout, (
            f"Wash sale lot should have adjusted basis $26.00/share "
            f"in account name, got:\n{stdout}"
        )

    def test_no_unadjusted_wash_basis(self):
        """No Aug 20 lot should use the raw market price $23.00 as basis."""
        stdout, stderr, rc = run_hledger(
            "bal", "assets:broker:apex:2024-08-20", "-N", "--flat"
        )
        assert rc == 0, f"hledger failed:\n{stderr}"
        for line in stdout.split("\n"):
            if "2024-08-20" in line:
                assert "$23" not in line, (
                    f"Wash sale lot must NOT use unadjusted $23 basis:\n{line}"
                )


# ---------------------------------------------------------------------------
# Stock split
# ---------------------------------------------------------------------------
class TestStockSplit:
    def test_equity_adjustments_for_split(self):
        """The stock split must create equity:adjustments of 250 APEX."""
        stdout, stderr, rc = run_hledger(
            "bal", "equity:adjustments", "-N", "-E"
        )
        assert rc == 0, f"hledger failed:\n{stderr}"
        total = sum_commodity(stdout, "APEX")
        assert abs(total) == 250, (
            f"Split should produce 250 APEX in equity:adjustments, "
            f"got {total}\n{stdout}"
        )

    def test_pre_split_lot_depleted(self):
        """The pre-split $50.00 lot must have 0 APEX remaining.

        All 200 shares should have been moved to the post-split $25.00 lot.
        """
        stdout, stderr, rc = run_hledger(
            "bal", "assets:broker:apex", "-N", "--flat", "-E"
        )
        assert rc == 0, f"hledger failed:\n{stderr}"
        for line in stdout.split("\n"):
            if "$50" in line and "APEX" in line:
                match = re.search(r"(\d+)\s+APEX", line)
                if match and int(match.group(1)) > 0:
                    assert False, (
                        f"Pre-split lot $50.00 still has APEX shares:\n{line}"
                    )


# ---------------------------------------------------------------------------
# Dividends
# ---------------------------------------------------------------------------
class TestDividend:
    def test_dividend_is_revenue(self):
        """Dividend income of $180.00 must appear in revenues:dividends."""
        stdout, stderr, rc = run_hledger(
            "bal", "revenues:dividends", "-N"
        )
        assert rc == 0, f"hledger failed:\n{stderr}"
        amount = parse_dollar_amount(stdout)
        assert amount is not None and abs(abs(amount) - 180.0) < 0.01, (
            f"Expected $180.00 in revenues:dividends, got:\n{stdout}"
        )


# ---------------------------------------------------------------------------
# Lot tracking discipline
# ---------------------------------------------------------------------------
class TestNoParentPostings:
    def test_no_apex_parent_postings(self):
        """No shares should be posted to the bare parent assets:broker:apex."""
        stdout, stderr, rc = run_hledger(
            "reg", "assets:broker:apex", "-w", "200"
        )
        assert rc == 0, f"hledger failed:\n{stderr}"
        for line in stdout.split("\n"):
            if ("assets:broker:apex " in line
                    and "assets:broker:apex:" not in line):
                assert False, (
                    f"Found posting to parent account assets:broker:apex "
                    f"instead of a lot subaccount:\n{line}"
                )

    def test_no_bolt_parent_postings(self):
        """No shares should be posted to the bare parent assets:broker:bolt."""
        stdout, stderr, rc = run_hledger(
            "reg", "assets:broker:bolt", "-w", "200"
        )
        assert rc == 0, f"hledger failed:\n{stderr}"
        for line in stdout.split("\n"):
            if ("assets:broker:bolt " in line
                    and "assets:broker:bolt:" not in line):
                assert False, (
                    f"Found posting to parent account assets:broker:bolt "
                    f"instead of a lot subaccount:\n{line}"
                )
