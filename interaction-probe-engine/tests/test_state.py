
import json
import os
import pytest

REPORT_PATH = '/app/output/report.json'


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), \
        "report.json not found at /app/output/report.json — probe may not have run"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


# ── Schema and structure ──────────────────────────────────────────────

class TestReportSchema:
    def test_has_pages(self, report):
        assert 'pages' in report

    def test_has_aggregate(self, report):
        assert 'aggregate' in report

    def test_all_pages_present(self, report):
        for name in ['kinetics.html', 'network.html', 'timeseries.html']:
            assert name in report['pages'], f"Missing page: {name}"

    def test_page_structure(self, report):
        for name, page in report['pages'].items():
            assert 'total_interactive' in page, f"{name}: missing total_interactive"
            assert 'responsive' in page, f"{name}: missing responsive"
            assert 'interaction_rate' in page, f"{name}: missing interaction_rate"
            assert 'elements' in page, f"{name}: missing elements"
            assert isinstance(page['elements'], list), f"{name}: elements not a list"
            assert len(page['elements']) > 0, f"{name}: elements list is empty"

    def test_element_structure(self, report):
        for name, page in report['pages'].items():
            for elem in page['elements']:
                assert 'selector' in elem, f"{name}: element missing selector"
                assert 'tag' in elem, f"{name}: element missing tag"
                assert 'action_type' in elem, f"{name}: element missing action_type"
                assert 'mutations_count' in elem, f"{name}: element missing mutations_count"
                assert 'responsive' in elem, f"{name}: element missing responsive"

    def test_aggregate_structure(self, report):
        agg = report['aggregate']
        assert 'total_interactive' in agg
        assert 'total_responsive' in agg
        assert 'interaction_rate' in agg


# ── Kinetics page ────────────────────────────────────────────────────

class TestKineticsPage:
    def test_minimum_element_count(self, report):
        page = report['pages']['kinetics.html']
        # At least: 3 inputs + 1 select + 2 buttons = 6
        assert page['total_interactive'] >= 5, \
            f"Expected >=5 interactive elements, got {page['total_interactive']}"

    def test_has_responsive_elements(self, report):
        page = report['pages']['kinetics.html']
        assert page['responsive'] >= 3, \
            f"Expected >=3 responsive elements, got {page['responsive']}"

    def test_button_found(self, report):
        tags = [e['tag'].lower() for e in report['pages']['kinetics.html']['elements']]
        assert 'button' in tags, "No button element discovered"

    def test_select_found(self, report):
        tags = [e['tag'].lower() for e in report['pages']['kinetics.html']['elements']]
        assert 'select' in tags, "No select element discovered"

    def test_input_found(self, report):
        tags = [e['tag'].lower() for e in report['pages']['kinetics.html']['elements']]
        assert 'input' in tags, "No input element discovered"


# ── Network page (shadow DOM, delegation, decoys) ────────────────────

class TestNetworkPage:
    def test_minimum_element_count(self, report):
        page = report['pages']['network.html']
        # At minimum: analyze button + search input + directed checkbox + shadow range
        assert page['total_interactive'] >= 4, \
            f"Expected >=4 interactive elements, got {page['total_interactive']}"

    def test_shadow_dom_discovered(self, report):
        """The shadow DOM range slider inside <weight-slider> must be found."""
        page = report['pages']['network.html']
        elements = page['elements']
        # The only range input in network.html is inside the shadow DOM.
        has_range = any(
            e.get('action_type', '').lower() == 'range'
            for e in elements
        )
        has_shadow_selector = any(
            '>>>' in e.get('selector', '') or
            'shadow' in e.get('selector', '').lower() or
            'weight' in e.get('selector', '').lower() or
            'slider' in e.get('selector', '').lower() or
            'edge-weight' in e.get('selector', '').lower()
            for e in elements
        )
        assert has_range or has_shadow_selector, \
            "Shadow DOM range slider not discovered — no range action_type or shadow selector found"

    def test_decoy_not_responsive(self, report):
        """The #preview-pane decoy must not be marked responsive if discovered."""
        page = report['pages']['network.html']
        for e in page['elements']:
            sel = e.get('selector', '').lower()
            if 'preview' in sel:
                assert not e['responsive'], \
                    "Decoy element #preview-pane incorrectly marked as responsive"

    def test_has_responsive_elements(self, report):
        page = report['pages']['network.html']
        assert page['responsive'] >= 3, \
            f"Expected >=3 responsive elements, got {page['responsive']}"


# ── Time series page (debounce, disabled, radios) ────────────────────

class TestTimeseriesPage:
    def test_minimum_element_count(self, report):
        page = report['pages']['timeseries.html']
        assert page['total_interactive'] >= 5, \
            f"Expected >=5 interactive elements, got {page['total_interactive']}"

    def test_radio_buttons_found(self, report):
        page = report['pages']['timeseries.html']
        radio_count = sum(
            1 for e in page['elements']
            if e.get('tag', '').lower() == 'input'
            and e.get('action_type', '').lower() in ('radio', 'check', 'click')
        )
        assert radio_count >= 2, \
            f"Expected >=2 radio buttons, found {radio_count}"

    def test_debounced_input_responsive(self, report):
        """The window-size input has a debounced handler — must be detected."""
        page = report['pages']['timeseries.html']
        responsive_inputs = [
            e for e in page['elements']
            if e.get('tag', '').lower() == 'input'
            and e.get('responsive', False)
            and e.get('action_type', '').lower() in ('input', 'type', 'change', 'range', 'fill')
        ]
        assert len(responsive_inputs) >= 1, \
            "No responsive text/number input found — debounced handler not detected"

    def test_disabled_buttons_handling(self, report):
        """Disabled buttons should not all be marked responsive."""
        page = report['pages']['timeseries.html']
        buttons = [e for e in page['elements'] if e.get('tag', '').lower() == 'button']
        responsive_btns = [b for b in buttons if b.get('responsive', False)]
        # Page has 4 buttons, 2 disabled. Either:
        # - disabled are found but non-responsive (responsive < total buttons)
        # - disabled are excluded (total buttons <= 2)
        assert len(responsive_btns) < len(buttons) or len(buttons) <= 2, \
            "All buttons marked responsive despite #process and #export being disabled"


# ── Metrics correctness ─────────────────────────────────────────────

class TestMetrics:
    def test_per_page_ir_computation(self, report):
        for name, page in report['pages'].items():
            total = page['total_interactive']
            resp = page['responsive']
            expected = resp / total if total > 0 else 0
            assert abs(page['interaction_rate'] - expected) < 0.02, \
                f"{name}: IR {page['interaction_rate']} != expected {expected:.4f}"

    def test_aggregate_totals(self, report):
        agg = report['aggregate']
        total = sum(p['total_interactive'] for p in report['pages'].values())
        resp = sum(p['responsive'] for p in report['pages'].values())
        assert agg['total_interactive'] == total, \
            f"Aggregate total_interactive {agg['total_interactive']} != sum {total}"
        assert agg['total_responsive'] == resp, \
            f"Aggregate total_responsive {agg['total_responsive']} != sum {resp}"

    def test_aggregate_ir(self, report):
        agg = report['aggregate']
        expected = agg['total_responsive'] / agg['total_interactive'] \
            if agg['total_interactive'] > 0 else 0
        assert abs(agg['interaction_rate'] - expected) < 0.02, \
            f"Aggregate IR {agg['interaction_rate']} != expected {expected:.4f}"

    def test_responsive_leq_total(self, report):
        for name, page in report['pages'].items():
            assert page['responsive'] <= page['total_interactive'], \
                f"{name}: responsive ({page['responsive']}) > total ({page['total_interactive']})"

    def test_ir_range(self, report):
        for name, page in report['pages'].items():
            assert 0 <= page['interaction_rate'] <= 1, \
                f"{name}: IR out of [0,1]: {page['interaction_rate']}"
        assert 0 <= report['aggregate']['interaction_rate'] <= 1


# ── Action types ─────────────────────────────────────────────────────

class TestActionTypes:
    VALID = frozenset({
        'click', 'input', 'change', 'select', 'check', 'radio',
        'range', 'slide', 'toggle', 'focus', 'hover', 'type',
        'keyboard', 'fill', 'submit', 'drag',
    })

    def test_valid_action_types(self, report):
        for name, page in report['pages'].items():
            for e in page['elements']:
                assert e['action_type'].lower() in self.VALID, \
                    f"{name}: unknown action_type '{e['action_type']}'"

    def test_diverse_action_types(self, report):
        all_types = set()
        for page in report['pages'].values():
            for e in page['elements']:
                all_types.add(e['action_type'].lower())
        assert len(all_types) >= 3, \
            f"Only {len(all_types)} distinct action types: {all_types}"

    def test_mutation_counts_consistent(self, report):
        """Responsive elements must have positive mutation counts."""
        for name, page in report['pages'].items():
            for e in page['elements']:
                if e.get('responsive'):
                    assert e.get('mutations_count', 0) > 0, \
                        f"{name}: responsive element {e['selector']} has 0 mutations"
