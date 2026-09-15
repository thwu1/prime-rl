
import subprocess
import os
import pytest

APP_DIR = "/app"
SRC_DIR = os.path.join(APP_DIR, "src")


def run_node(expr, cwd=APP_DIR):
    """Execute a Node.js expression and return (stdout, returncode)."""
    result = subprocess.run(
        ["node", "-e", expr],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=10,
    )
    return result.stdout.strip(), result.returncode


def read_src(filename):
    """Read a source file from /app/src/."""
    filepath = os.path.join(SRC_DIR, filename)
    with open(filepath, "r") as f:
        return f.read()


def check_syntax(filename):
    """Verify a source file is syntactically valid JS."""
    filepath = os.path.join(SRC_DIR, filename)
    result = subprocess.run(
        ["node", "--check", filepath],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# 1. Toggle removal: feature-pricing-v2 must not appear in any source file
# ---------------------------------------------------------------------------
class TestToggleRemoved:
    @pytest.mark.parametrize(
        "filename",
        [
            "pricing.js",
            "checkout.js",
            "dashboard.js",
            "analytics.js",
            "api.js",
            "notifications.js",
            "settings.js",
            "reports.js",
        ],
    )
    def test_no_pricing_v2_reference(self, filename):
        content = read_src(filename)
        assert "feature-pricing-v2" not in content, (
            f"{filename} still contains 'feature-pricing-v2'"
        )


# ---------------------------------------------------------------------------
# 2. Other toggles must be preserved
# ---------------------------------------------------------------------------
class TestOtherTogglesPreserved:
    def test_free_shipping_preserved_in_pricing(self):
        content = read_src("pricing.js")
        assert "feature-free-shipping" in content

    def test_search_refinement_preserved_in_settings(self):
        content = read_src("settings.js")
        assert "feature-search-refinement" in content


# ---------------------------------------------------------------------------
# 3. Behavioral correctness after transformation
# ---------------------------------------------------------------------------
class TestBehavior:
    def test_pricing_discount_returns_015(self):
        out, rc = run_node(
            "const m = require('./src/pricing'); console.log(m.getDiscount())"
        )
        assert rc == 0
        assert float(out) == pytest.approx(0.15)

    def test_pricing_shipping_rate_returns_599(self):
        out, rc = run_node(
            "const m = require('./src/pricing'); console.log(m.getShippingRate())"
        )
        assert rc == 0
        assert float(out) == pytest.approx(5.99)

    def test_checkout_tax_100_returns_725(self):
        out, rc = run_node(
            "const m = require('./src/checkout'); console.log(m.getTax(100))"
        )
        assert rc == 0
        assert float(out) == pytest.approx(7.25)

    def test_dashboard_layout_returns_new_flex(self):
        out, rc = run_node(
            "const m = require('./src/dashboard'); console.log(m.getDashboardLayout())"
        )
        assert rc == 0
        assert out == "new-flex"

    def test_analytics_endpoint_returns_v2(self):
        out, rc = run_node(
            "const m = require('./src/analytics'); console.log(m.getTrackingEndpoint())"
        )
        assert rc == 0
        assert out == "/v2/track"

    def test_api_version_returns_v2(self):
        out, rc = run_node(
            "const m = require('./src/api'); console.log(m.getApiVersion())"
        )
        assert rc == 0
        assert out == "v2"

    def test_notification_format_modern(self):
        out, rc = run_node(
            "const m = require('./src/notifications'); "
            "console.log(m.formatNotification('hello'))"
        )
        assert rc == 0
        assert out == "[MODERN] hello"

    def test_settings_show_feature_enabled(self):
        out, rc = run_node(
            "const m = require('./src/settings'); "
            "console.log(m.shouldShowFeature(true))"
        )
        assert rc == 0
        assert out == "true"

    def test_settings_show_feature_disabled(self):
        out, rc = run_node(
            "const m = require('./src/settings'); "
            "console.log(m.shouldShowFeature(false))"
        )
        assert rc == 0
        assert out == "false"

    def test_settings_show_search_returns_false(self):
        out, rc = run_node(
            "const m = require('./src/settings'); "
            "console.log(m.shouldShowSearch())"
        )
        assert rc == 0
        # featureToggle stub returns false, so search toggle is inactive
        assert out == "false"

    def test_report_config_format(self):
        out, rc = run_node(
            "const m = require('./src/reports'); "
            "console.log(m.getReportConfig().format)"
        )
        assert rc == 0
        assert out == "detailed"

    def test_report_config_version(self):
        out, rc = run_node(
            "const m = require('./src/reports'); "
            "console.log(m.getReportConfig().version)"
        )
        assert rc == 0
        assert out == "2"

    def test_generate_report(self):
        out, rc = run_node(
            "const m = require('./src/reports'); "
            "console.log(m.generateReport('test'))"
        )
        assert rc == 0
        assert out == "ENHANCED REPORT: enhanced(test)"


# ---------------------------------------------------------------------------
# 4. Unused function cleanup
# ---------------------------------------------------------------------------
class TestUnusedFunctionCleanup:
    def test_checkout_no_calculateTaxOld(self):
        content = read_src("checkout.js")
        assert "calculateTaxOld" not in content

    def test_checkout_still_has_calculateTaxNew(self):
        content = read_src("checkout.js")
        assert "calculateTaxNew" in content

    def test_notifications_no_legacyFormat(self):
        content = read_src("notifications.js")
        assert "legacyFormat" not in content

    def test_notifications_still_has_modernFormat(self):
        content = read_src("notifications.js")
        assert "modernFormat" in content

    def test_reports_no_processLegacy(self):
        content = read_src("reports.js")
        assert "processLegacy" not in content

    def test_reports_still_has_processEnhanced(self):
        content = read_src("reports.js")
        assert "processEnhanced" in content


# ---------------------------------------------------------------------------
# 5. Unused import cleanup
# ---------------------------------------------------------------------------
class TestUnusedImportCleanup:
    @pytest.mark.parametrize(
        "filename",
        [
            "checkout.js",
            "dashboard.js",
            "analytics.js",
            "api.js",
            "notifications.js",
            "reports.js",
        ],
    )
    def test_featureToggle_import_removed(self, filename):
        content = read_src(filename)
        # These files no longer use any toggle, so the require must be gone
        assert "featureToggle" not in content, (
            f"{filename} still has featureToggle reference (import not cleaned)"
        )

    def test_pricing_import_preserved(self):
        """pricing.js still uses feature-free-shipping, so import must stay."""
        content = read_src("pricing.js")
        assert "featureToggle" in content
        assert "require" in content

    def test_settings_import_preserved(self):
        """settings.js still uses feature-search-refinement, so import must stay."""
        content = read_src("settings.js")
        assert "featureToggle" in content
        assert "require" in content


# ---------------------------------------------------------------------------
# 6. Variable cleanup (inlined variables should be gone)
# ---------------------------------------------------------------------------
class TestVariableCleanup:
    def test_analytics_no_isPricingV2_variable(self):
        content = read_src("analytics.js")
        assert "isPricingV2" not in content

    def test_notifications_no_useLegacy_variable(self):
        content = read_src("notifications.js")
        assert "useLegacy" not in content

    def test_reports_no_usePricingV2_variable(self):
        content = read_src("reports.js")
        assert "usePricingV2" not in content

    def test_reports_no_isEnabled_alias(self):
        """The import alias 'isEnabled' should be fully removed."""
        content = read_src("reports.js")
        assert "isEnabled" not in content


# ---------------------------------------------------------------------------
# 7. featureToggle utility must not be modified
# ---------------------------------------------------------------------------
class TestUtilityUntouched:
    def test_utility_exists(self):
        assert os.path.exists(os.path.join(SRC_DIR, "utils", "featureToggle.js"))

    def test_utility_functional(self):
        out, rc = run_node(
            "const { featureToggle } = require('./src/utils/featureToggle'); "
            "console.log(typeof featureToggle)"
        )
        assert rc == 0
        assert out == "function"

    def test_utility_returns_false(self):
        out, rc = run_node(
            "const { featureToggle } = require('./src/utils/featureToggle'); "
            "console.log(featureToggle('anything'))"
        )
        assert rc == 0
        assert out == "false"


# ---------------------------------------------------------------------------
# 8. All source files are syntactically valid after transformation
# ---------------------------------------------------------------------------
class TestSyntaxValidity:
    @pytest.mark.parametrize(
        "filename",
        [
            "pricing.js",
            "checkout.js",
            "dashboard.js",
            "analytics.js",
            "api.js",
            "notifications.js",
            "settings.js",
            "reports.js",
        ],
    )
    def test_valid_javascript(self, filename):
        assert check_syntax(filename), f"{filename} has syntax errors"


# ---------------------------------------------------------------------------
# 9. Logical AND simplification in settings.js
# ---------------------------------------------------------------------------
class TestLogicalAndSimplification:
    def test_settings_no_standalone_toggle_and(self):
        """The toggle in 'featureToggle(...) && isEnabled' must be removed,
        leaving just 'isEnabled' as the if-condition."""
        content = read_src("settings.js")
        # The toggle call for pricing-v2 should be gone
        assert "feature-pricing-v2" not in content
        # But isEnabled should still be referenced as a condition
        assert "isEnabled" in content
