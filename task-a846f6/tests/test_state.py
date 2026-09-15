
import json
import os
import subprocess
import tempfile
import pytest

REPORT_PATH = '/app/report.json'


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


# ── Report structure ──────────────────────────────────────────────────

class TestReportStructure:
    def test_has_pages_key(self, report):
        assert 'pages' in report, "Report missing 'pages' key"

    def test_has_summary_key(self, report):
        assert 'summary' in report, "Report missing 'summary' key"

    def test_summary_has_required_fields(self, report):
        s = report['summary']
        for field in ('total_pages', 'total_violations',
                      'violations_by_test', 'non_interference_results'):
            assert field in s, f"Summary missing '{field}'"

    def test_page_entries_have_required_fields(self, report):
        for name, data in report['pages'].items():
            assert 'violations' in data, f"{name}: missing 'violations'"
            assert 'test_results' in data, f"{name}: missing 'test_results'"

    def test_violations_have_required_fields(self, report):
        for name, data in report['pages'].items():
            for i, v in enumerate(data['violations']):
                for field in ('test_id', 'wcag_sc', 'element', 'message'):
                    assert field in v, (
                        f"{name} violation #{i}: missing '{field}'")


# ── Page inventory ────────────────────────────────────────────────────

class TestPageInventory:
    def test_total_pages(self, report):
        assert report['summary']['total_pages'] == 6

    def test_all_pages_present(self, report):
        expected = {'dashboard.html', 'reports.html', 'registration.html',
                    'articles.html', 'gallery.html', 'portal.html'}
        assert set(report['pages'].keys()) == expected


# ── Per-page violation counts ─────────────────────────────────────────

class TestViolationCounts:
    def test_total_violations(self, report):
        assert report['summary']['total_violations'] == 18

    def test_dashboard_zero(self, report):
        assert len(report['pages']['dashboard.html']['violations']) == 0

    def test_reports_four(self, report):
        assert len(report['pages']['reports.html']['violations']) == 4

    def test_registration_five(self, report):
        assert len(report['pages']['registration.html']['violations']) == 5

    def test_articles_two(self, report):
        assert len(report['pages']['articles.html']['violations']) == 2

    def test_gallery_four(self, report):
        assert len(report['pages']['gallery.html']['violations']) == 4

    def test_portal_three(self, report):
        assert len(report['pages']['portal.html']['violations']) == 3


# ── Violations-by-test summary ────────────────────────────────────────

class TestViolationsByTest:
    def _vbt(self, report):
        return report['summary']['violations_by_test']

    def test_language(self, report):
        assert self._vbt(report).get('15.A-LanguagePage', 0) == 2

    def test_page_titled(self, report):
        assert self._vbt(report).get('11.A-PageTitled', 0) == 1

    def test_meaningful_image(self, report):
        assert self._vbt(report).get('6.A-MeaningfulImage', 0) == 2

    def test_decorative_image(self, report):
        assert self._vbt(report).get('6.B-DecorativeImage', 0) == 3

    def test_contrast(self, report):
        assert self._vbt(report).get('8.A-Contrast', 0) == 2

    def test_form_name(self, report):
        assert self._vbt(report).get('10.A-FormName', 0) == 3

    def test_link_purpose(self, report):
        assert self._vbt(report).get('14.A-LinkPurpose', 0) == 3

    def test_table_headers(self, report):
        assert self._vbt(report).get('12.B-DataTableHeaderAssociation', 0) == 1

    def test_audio_control(self, report):
        assert self._vbt(report).get('21.D-AudioControl', 0) == 1


# ── Test results per page (pass / fail / not_applicable) ─────────────

class TestResultsDashboard:
    """dashboard.html should pass all applicable tests, no failures."""

    def test_no_failures(self, report):
        results = report['pages']['dashboard.html']['test_results']
        failing = [t for t, r in results.items() if r == 'fail']
        assert failing == [], f"Expected no failures, got: {failing}"


class TestResultsReports:
    def test_language_fail(self, report):
        r = report['pages']['reports.html']['test_results']
        assert r.get('15.A-LanguagePage') == 'fail'

    def test_meaningful_image_fail(self, report):
        r = report['pages']['reports.html']['test_results']
        assert r.get('6.A-MeaningfulImage') == 'fail'

    def test_decorative_image_fail(self, report):
        r = report['pages']['reports.html']['test_results']
        assert r.get('6.B-DecorativeImage') == 'fail'

    def test_title_passes(self, report):
        r = report['pages']['reports.html']['test_results']
        assert r.get('11.A-PageTitled') == 'pass'


class TestResultsRegistration:
    def test_form_fail(self, report):
        r = report['pages']['registration.html']['test_results']
        assert r.get('10.A-FormName') == 'fail'

    def test_link_fail(self, report):
        r = report['pages']['registration.html']['test_results']
        assert r.get('14.A-LinkPurpose') == 'fail'

    def test_language_passes(self, report):
        r = report['pages']['registration.html']['test_results']
        assert r.get('15.A-LanguagePage') == 'pass'


class TestResultsArticles:
    def test_title_fail(self, report):
        r = report['pages']['articles.html']['test_results']
        assert r.get('11.A-PageTitled') == 'fail'

    def test_table_fail(self, report):
        r = report['pages']['articles.html']['test_results']
        assert r.get('12.B-DataTableHeaderAssociation') == 'fail'

    def test_language_passes(self, report):
        r = report['pages']['articles.html']['test_results']
        assert r.get('15.A-LanguagePage') == 'pass'


class TestResultsGallery:
    def test_contrast_fail(self, report):
        r = report['pages']['gallery.html']['test_results']
        assert r.get('8.A-Contrast') == 'fail'

    def test_decorative_fail(self, report):
        r = report['pages']['gallery.html']['test_results']
        assert r.get('6.B-DecorativeImage') == 'fail'

    def test_language_passes(self, report):
        r = report['pages']['gallery.html']['test_results']
        assert r.get('15.A-LanguagePage') == 'pass'


class TestResultsPortal:
    def test_language_fail(self, report):
        r = report['pages']['portal.html']['test_results']
        assert r.get('15.A-LanguagePage') == 'fail'

    def test_link_fail(self, report):
        r = report['pages']['portal.html']['test_results']
        assert r.get('14.A-LinkPurpose') == 'fail'

    def test_audio_fail(self, report):
        r = report['pages']['portal.html']['test_results']
        assert r.get('21.D-AudioControl') == 'fail'

    def test_noninterference_fail(self, report):
        r = report['pages']['portal.html']['test_results']
        assert r.get('3.A-NonInterference') == 'fail'

    def test_title_passes(self, report):
        r = report['pages']['portal.html']['test_results']
        assert r.get('11.A-PageTitled') == 'pass'


# ── NonInterference composite results ─────────────────────────────────

class TestNonInterference:
    def test_portal_fails(self, report):
        ni = report['summary']['non_interference_results']
        assert ni.get('portal.html') == 'fail'

    def test_dashboard_passes(self, report):
        ni = report['summary']['non_interference_results']
        assert ni.get('dashboard.html') == 'pass'

    def test_reports_passes(self, report):
        ni = report['summary']['non_interference_results']
        assert ni.get('reports.html') == 'pass'

    def test_registration_passes(self, report):
        ni = report['summary']['non_interference_results']
        assert ni.get('registration.html') == 'pass'

    def test_articles_passes(self, report):
        ni = report['summary']['non_interference_results']
        assert ni.get('articles.html') == 'pass'

    def test_gallery_passes(self, report):
        ni = report['summary']['non_interference_results']
        assert ni.get('gallery.html') == 'pass'


# ── Violation detail checks ───────────────────────────────────────────

class TestViolationDetails:
    """Verify specific violations have correct test IDs and WCAG references."""

    def test_reports_language_violation(self, report):
        vs = report['pages']['reports.html']['violations']
        lang = [v for v in vs if v['test_id'] == '15.A-LanguagePage']
        assert len(lang) == 1
        assert lang[0]['wcag_sc'] == '3.1.1'

    def test_reports_image_violations(self, report):
        vs = report['pages']['reports.html']['violations']
        imgs = [v for v in vs if v['test_id'] == '6.A-MeaningfulImage']
        assert len(imgs) == 2
        for v in imgs:
            assert v['wcag_sc'] == '1.1.1'

    def test_reports_decorative_violation(self, report):
        vs = report['pages']['reports.html']['violations']
        decs = [v for v in vs if v['test_id'] == '6.B-DecorativeImage']
        assert len(decs) == 1
        assert decs[0]['wcag_sc'] == '1.1.1'

    def test_registration_form_violations(self, report):
        vs = report['pages']['registration.html']['violations']
        forms = [v for v in vs if v['test_id'] == '10.A-FormName']
        assert len(forms) == 3

    def test_registration_link_violations(self, report):
        vs = report['pages']['registration.html']['violations']
        links = [v for v in vs if v['test_id'] == '14.A-LinkPurpose']
        assert len(links) == 2

    def test_articles_title_violation(self, report):
        vs = report['pages']['articles.html']['violations']
        titles = [v for v in vs if v['test_id'] == '11.A-PageTitled']
        assert len(titles) == 1
        assert titles[0]['wcag_sc'] == '2.4.2'

    def test_articles_table_violation(self, report):
        vs = report['pages']['articles.html']['violations']
        tables = [v for v in vs if v['test_id'] == '12.B-DataTableHeaderAssociation']
        assert len(tables) == 1
        assert tables[0]['wcag_sc'] == '1.3.1'

    def test_gallery_contrast_violations(self, report):
        vs = report['pages']['gallery.html']['violations']
        contrast = [v for v in vs if v['test_id'] == '8.A-Contrast']
        assert len(contrast) == 2
        for v in contrast:
            assert v['wcag_sc'] == '1.4.3'

    def test_gallery_decorative_violations(self, report):
        vs = report['pages']['gallery.html']['violations']
        decs = [v for v in vs if v['test_id'] == '6.B-DecorativeImage']
        assert len(decs) == 2

    def test_portal_audio_violation(self, report):
        vs = report['pages']['portal.html']['violations']
        audio = [v for v in vs if v['test_id'] == '21.D-AudioControl']
        assert len(audio) == 1
        assert audio[0]['wcag_sc'] == '1.4.2'

    def test_portal_link_violation(self, report):
        vs = report['pages']['portal.html']['violations']
        links = [v for v in vs if v['test_id'] == '14.A-LinkPurpose']
        assert len(links) == 1

    def test_portal_language_violation(self, report):
        vs = report['pages']['portal.html']['violations']
        lang = [v for v in vs if v['test_id'] == '15.A-LanguagePage']
        assert len(lang) == 1


# ══════════════════════════════════════════════════════════════════════
# DNA (Dynamic Novel Assessment) TESTS
#
# These tests generate novel HTML pages AT TEST TIME that do NOT exist
# in the task's /app/pages/ directory.  They invoke the audit tool via
# subprocess on this unseen content and verify the output, preventing
# any hardcoded-answer strategy.
# ══════════════════════════════════════════════════════════════════════


def _run_audit_on_html(pages_dict):
    """Helper: write HTML pages to a temp dir, run /app/audit.py,
    return the parsed JSON report.  Each DNA test calls subprocess
    independently."""
    with tempfile.TemporaryDirectory(prefix="dna_") as td:
        pages_dir = os.path.join(td, "pages")
        os.makedirs(pages_dir)
        for name, content in pages_dict.items():
            with open(os.path.join(pages_dir, name), "w",
                       encoding="utf-8") as f:
                f.write(content)
        rpt_path = os.path.join(td, "report.json")

        result = subprocess.run(
            ["python3", "/app/audit.py", pages_dir, rpt_path],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, (
            f"audit.py failed on novel DNA pages:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        with open(rpt_path) as f:
            return json.load(f)


# ── Novel HTML content (not present in /app/pages/) ──────────────────

_DNA_CLEAN = '''\
<!DOCTYPE html>
<html lang="es">
<head><title>Prueba Limpia</title></head>
<body>
<h1>Contenido Principal</h1>
<img src="logotipo.svg" alt="Logotipo corporativo">
<img src="separador.png" alt="" role="presentation">
<p style="color: #333333; background-color: #ffffff;">Texto con buen contraste.</p>
<form>
  <label for="buscar">Buscar:</label>
  <input type="text" id="buscar" name="q">
</form>
<a href="/inicio">Ir al inicio</a>
<table>
  <thead><tr><th>Columna A</th><th>Columna B</th></tr></thead>
  <tbody>
    <tr><td>Dato 1</td><td>Dato 2</td></tr>
    <tr><td>Dato 3</td><td>Dato 4</td></tr>
  </tbody>
</table>
</body>
</html>'''

_DNA_BROKEN = '''\
<!DOCTYPE html>
<html>
<head></head>
<body>
<audio src="background_music.ogg" autoplay></audio>
<img src="photo_001.jpg">
<img src="chart.png" alt="chart.png">
<form>
  <input type="text" name="field_x">
  <select name="dropdown_y"><option>Option A</option></select>
</form>
<a href="/dead_end"></a>
<a href="/icon_link"><img src="arrow_icon.png" alt=""></a>
<table>
  <tr><td>Row1Col1</td><td>Row1Col2</td></tr>
  <tr><td>Row2Col1</td><td>Row2Col2</td></tr>
</table>
</body>
</html>'''

_DNA_MIXED = '''\
<!DOCTYPE html>
<html lang="ja">
<head><title>\u30c6\u30b9\u30c8\u30da\u30fc\u30b8</title></head>
<body>
<h1>\u30b3\u30f3\u30c6\u30f3\u30c4</h1>
<img src="ornament.svg" role="none" aria-label="Decorative ornament graphic">
<img src="ruling_line.gif" role="presentation" alt="Fancy ruling line separator">
<p style="color: #808080; background-color: #ffffff;">Normal gray text on white</p>
<h2 style="color: #808080; background-color: #ffffff; font-size: 20pt;">Large heading same gray</h2>
<a href="/home">\u30db\u30fc\u30e0\u3078</a>
</body>
</html>'''

_DNA_ARIA = '''\
<!DOCTYPE html>
<html lang="en">
<head><title>ARIA Label Resolution</title></head>
<body>
<h1>Accessible Name Priority Test</h1>
<span id="fname-lbl">First Name</span>
<span id="lname-lbl">Last Name</span>
<form>
  <input type="text" name="fname" aria-labelledby="fname-lbl">
  <input type="text" name="lname" aria-labelledby="lname-lbl">
  <input type="text" name="unlabeled_field">
</form>
<a href="/about" aria-label="Learn more about our mission">About</a>
<img src="infographic_q3.png" aria-labelledby="img-desc">
<span id="img-desc">Sales data infographic for Q3 2024</span>
</body>
</html>'''


# ── Shared multi-page DNA fixture ────────────────────────────────────

@pytest.fixture(scope="module")
def dna_report(tmp_path_factory):
    """Generate four novel HTML pages and run the audit tool on them."""
    dna_dir = tmp_path_factory.mktemp("dna_novel")
    pages = dna_dir / "pages"
    pages.mkdir()
    report_path = dna_dir / "dna_report.json"

    for name, content in [
        ("dna_clean.html", _DNA_CLEAN),
        ("dna_broken.html", _DNA_BROKEN),
        ("dna_mixed.html", _DNA_MIXED),
        ("dna_aria.html", _DNA_ARIA),
    ]:
        (pages / name).write_text(content, encoding="utf-8")

    result = subprocess.run(
        ["python3", "/app/audit.py", str(pages), str(report_path)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"audit.py failed on DNA pages:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    with open(report_path) as f:
        return json.load(f)


# ── DNA: summary checks ─────────────────────────────────────────────

def test_dna_total_pages(dna_report):
    assert dna_report["summary"]["total_pages"] == 4


def test_dna_total_violations(dna_report):
    # clean=0  broken=10  mixed=3  aria=1  → 14
    assert dna_report["summary"]["total_violations"] == 14


# ── DNA: dna_clean.html — fully compliant, 0 violations ─────────────

def test_dna_clean_zero_violations(dna_report):
    assert len(dna_report["pages"]["dna_clean.html"]["violations"]) == 0


def test_dna_clean_no_failures(dna_report):
    r = dna_report["pages"]["dna_clean.html"]["test_results"]
    failing = [t for t, v in r.items() if v == "fail"]
    assert failing == [], f"Expected no failures, got {failing}"


def test_dna_clean_lang_pass(dna_report):
    r = dna_report["pages"]["dna_clean.html"]["test_results"]
    assert r["15.A-LanguagePage"] == "pass"


def test_dna_clean_title_pass(dna_report):
    r = dna_report["pages"]["dna_clean.html"]["test_results"]
    assert r["11.A-PageTitled"] == "pass"


def test_dna_clean_ni_pass(dna_report):
    ni = dna_report["summary"]["non_interference_results"]
    assert ni["dna_clean.html"] == "pass"


# ── DNA: dna_broken.html — 10 violations across 7 test IDs ──────────

def test_dna_broken_violation_count(dna_report):
    assert len(dna_report["pages"]["dna_broken.html"]["violations"]) == 10


def test_dna_broken_lang_fail(dna_report):
    r = dna_report["pages"]["dna_broken.html"]["test_results"]
    assert r["15.A-LanguagePage"] == "fail"


def test_dna_broken_title_fail(dna_report):
    r = dna_report["pages"]["dna_broken.html"]["test_results"]
    assert r["11.A-PageTitled"] == "fail"


def test_dna_broken_meaningful_image_count(dna_report):
    vs = dna_report["pages"]["dna_broken.html"]["violations"]
    assert len([v for v in vs if v["test_id"] == "6.A-MeaningfulImage"]) == 2


def test_dna_broken_form_count(dna_report):
    vs = dna_report["pages"]["dna_broken.html"]["violations"]
    assert len([v for v in vs if v["test_id"] == "10.A-FormName"]) == 2


def test_dna_broken_link_count(dna_report):
    vs = dna_report["pages"]["dna_broken.html"]["violations"]
    assert len([v for v in vs if v["test_id"] == "14.A-LinkPurpose"]) == 2


def test_dna_broken_table_fail(dna_report):
    r = dna_report["pages"]["dna_broken.html"]["test_results"]
    assert r["12.B-DataTableHeaderAssociation"] == "fail"


def test_dna_broken_audio_fail(dna_report):
    r = dna_report["pages"]["dna_broken.html"]["test_results"]
    assert r["21.D-AudioControl"] == "fail"


def test_dna_broken_ni_fail(dna_report):
    r = dna_report["pages"]["dna_broken.html"]["test_results"]
    assert r["3.A-NonInterference"] == "fail"


def test_dna_broken_ni_summary(dna_report):
    ni = dna_report["summary"]["non_interference_results"]
    assert ni["dna_broken.html"] == "fail"


# ── DNA: dna_mixed.html — 3 violations: 2 decorative + 1 contrast ───

def test_dna_mixed_violation_count(dna_report):
    assert len(dna_report["pages"]["dna_mixed.html"]["violations"]) == 3


def test_dna_mixed_decorative_fail(dna_report):
    r = dna_report["pages"]["dna_mixed.html"]["test_results"]
    assert r["6.B-DecorativeImage"] == "fail"


def test_dna_mixed_decorative_count(dna_report):
    vs = dna_report["pages"]["dna_mixed.html"]["violations"]
    assert len([v for v in vs if v["test_id"] == "6.B-DecorativeImage"]) == 2


def test_dna_mixed_contrast_fail(dna_report):
    r = dna_report["pages"]["dna_mixed.html"]["test_results"]
    assert r["8.A-Contrast"] == "fail"


def test_dna_mixed_contrast_count(dna_report):
    vs = dna_report["pages"]["dna_mixed.html"]["violations"]
    # #808080 on #fff = ratio ~3.95 — fails 4.5:1 for normal <p> text
    # Same colours on <h2 font-size:20pt> = large text, passes 3.0:1
    assert len([v for v in vs if v["test_id"] == "8.A-Contrast"]) == 1


def test_dna_mixed_lang_pass(dna_report):
    r = dna_report["pages"]["dna_mixed.html"]["test_results"]
    assert r["15.A-LanguagePage"] == "pass"


def test_dna_mixed_ni_pass(dna_report):
    ni = dna_report["summary"]["non_interference_results"]
    assert ni["dna_mixed.html"] == "pass"


# ── DNA: dna_aria.html — 1 violation: unlabelled form control ────────

def test_dna_aria_violation_count(dna_report):
    assert len(dna_report["pages"]["dna_aria.html"]["violations"]) == 1


def test_dna_aria_form_fail(dna_report):
    r = dna_report["pages"]["dna_aria.html"]["test_results"]
    assert r["10.A-FormName"] == "fail"


def test_dna_aria_form_violation_is_unlabeled(dna_report):
    vs = dna_report["pages"]["dna_aria.html"]["violations"]
    form_vs = [v for v in vs if v["test_id"] == "10.A-FormName"]
    assert len(form_vs) == 1


def test_dna_aria_image_pass(dna_report):
    r = dna_report["pages"]["dna_aria.html"]["test_results"]
    assert r["6.A-MeaningfulImage"] == "pass"


def test_dna_aria_link_pass(dna_report):
    r = dna_report["pages"]["dna_aria.html"]["test_results"]
    assert r["14.A-LinkPurpose"] == "pass"


def test_dna_aria_lang_pass(dna_report):
    r = dna_report["pages"]["dna_aria.html"]["test_results"]
    assert r["15.A-LanguagePage"] == "pass"


def test_dna_aria_ni_pass(dna_report):
    ni = dna_report["summary"]["non_interference_results"]
    assert ni["dna_aria.html"] == "pass"


# ── DNA: cross-page violation-by-test counts ─────────────────────────

def test_dna_vbt_language(dna_report):
    vbt = dna_report["summary"]["violations_by_test"]
    assert vbt.get("15.A-LanguagePage", 0) == 1


def test_dna_vbt_title(dna_report):
    vbt = dna_report["summary"]["violations_by_test"]
    assert vbt.get("11.A-PageTitled", 0) == 1


def test_dna_vbt_meaningful_image(dna_report):
    vbt = dna_report["summary"]["violations_by_test"]
    assert vbt.get("6.A-MeaningfulImage", 0) == 2


def test_dna_vbt_decorative_image(dna_report):
    vbt = dna_report["summary"]["violations_by_test"]
    assert vbt.get("6.B-DecorativeImage", 0) == 2


def test_dna_vbt_contrast(dna_report):
    vbt = dna_report["summary"]["violations_by_test"]
    assert vbt.get("8.A-Contrast", 0) == 1


def test_dna_vbt_form(dna_report):
    vbt = dna_report["summary"]["violations_by_test"]
    assert vbt.get("10.A-FormName", 0) == 3


def test_dna_vbt_link(dna_report):
    vbt = dna_report["summary"]["violations_by_test"]
    assert vbt.get("14.A-LinkPurpose", 0) == 2


def test_dna_vbt_table(dna_report):
    vbt = dna_report["summary"]["violations_by_test"]
    assert vbt.get("12.B-DataTableHeaderAssociation", 0) == 1


def test_dna_vbt_audio(dna_report):
    vbt = dna_report["summary"]["violations_by_test"]
    assert vbt.get("21.D-AudioControl", 0) == 1


# ══════════════════════════════════════════════════════════════════════
# STANDALONE DNA TESTS
#
# Each test below independently generates a novel HTML page, invokes
# /app/audit.py via subprocess.run, and verifies the output against
# independently computed expectations.  This prevents any strategy
# that merely hardcodes the multi-page DNA report above.
# ══════════════════════════════════════════════════════════════════════


def test_dna_standalone_contrast_fail():
    """Novel page: #cccccc text on #ffffff = ratio ~1.61, clearly fails
    4.5:1 threshold for normal text.  Verify the tool detects it."""
    html = ('<!DOCTYPE html>\n'
            '<html lang="en"><head><title>Contrast DNA</title></head>\n'
            '<body>\n'
            '<p style="color: #cccccc; background-color: #ffffff;">'
            'Very low contrast</p>\n'
            '</body></html>')
    rpt = _run_audit_on_html({"contrast_fail.html": html})
    vs = rpt["pages"]["contrast_fail.html"]["violations"]
    contrast_vs = [v for v in vs if v["test_id"] == "8.A-Contrast"]
    assert len(contrast_vs) == 1, (
        f"Expected 1 contrast violation for #cccccc on #fff, got {len(contrast_vs)}")
    assert contrast_vs[0]["wcag_sc"] == "1.4.3"


def test_dna_standalone_contrast_large_text_pass():
    """Novel page: #808080 on #ffffff = ratio ~3.95.  Fails 4.5:1 for
    normal text but PASSES 3.0:1 for large text (font-size: 24pt).
    The tool must correctly identify large text and use the relaxed
    threshold."""
    html = ('<!DOCTYPE html>\n'
            '<html lang="en"><head><title>Large Text DNA</title></head>\n'
            '<body>\n'
            '<p style="color: #808080; background-color: #ffffff; '
            'font-size: 24pt;">Large text passes contrast</p>\n'
            '</body></html>')
    rpt = _run_audit_on_html({"large_pass.html": html})
    vs = rpt["pages"]["large_pass.html"]["violations"]
    contrast_vs = [v for v in vs if v["test_id"] == "8.A-Contrast"]
    assert len(contrast_vs) == 0, (
        "24pt text at ratio ~3.95 should pass the 3.0:1 large-text threshold")


def test_dna_standalone_contrast_heading_implicit_large():
    """Novel page: <h3> without explicit font-size should be treated as
    large text.  #808080 on #ffffff (ratio ~3.95) passes at 3.0:1."""
    html = ('<!DOCTYPE html>\n'
            '<html lang="en"><head><title>Heading DNA</title></head>\n'
            '<body>\n'
            '<h3 style="color: #808080; background-color: #ffffff;">'
            'Heading is large text</h3>\n'
            '</body></html>')
    rpt = _run_audit_on_html({"heading_large.html": html})
    vs = rpt["pages"]["heading_large.html"]["violations"]
    contrast_vs = [v for v in vs if v["test_id"] == "8.A-Contrast"]
    assert len(contrast_vs) == 0, (
        "Headings without explicit font-size should be treated as large text")


def test_dna_standalone_aria_labelledby_resolution():
    """Novel page: two inputs — one with aria-labelledby pointing to a
    span (should resolve → pass), one unlabeled (should fail).
    Tests the W3C accessible name priority algorithm."""
    html = ('<!DOCTYPE html>\n'
            '<html lang="en"><head><title>ARIA DNA</title></head>\n'
            '<body>\n'
            '<span id="email-lbl">Email address</span>\n'
            '<form>\n'
            '  <input type="text" name="email" aria-labelledby="email-lbl">\n'
            '  <input type="text" name="unlabeled">\n'
            '</form>\n'
            '</body></html>')
    rpt = _run_audit_on_html({"aria_res.html": html})
    vs = rpt["pages"]["aria_res.html"]["violations"]
    form_vs = [v for v in vs if v["test_id"] == "10.A-FormName"]
    assert len(form_vs) == 1, (
        "Only the unlabeled input should fail; aria-labelledby must resolve")
    r = rpt["pages"]["aria_res.html"]["test_results"]
    assert r["10.A-FormName"] == "fail"


def test_dna_standalone_filename_alt_detection():
    """Novel page: image with alt text that is a filename pattern.
    The tool must detect this as a 6.A-MeaningfulImage violation."""
    html = ('<!DOCTYPE html>\n'
            '<html lang="en"><head><title>Filename DNA</title></head>\n'
            '<body>\n'
            '<img src="quarterly_results.png" alt="quarterly_results.png">\n'
            '</body></html>')
    rpt = _run_audit_on_html({"fname_alt.html": html})
    vs = rpt["pages"]["fname_alt.html"]["violations"]
    img_vs = [v for v in vs if v["test_id"] == "6.A-MeaningfulImage"]
    assert len(img_vs) == 1, (
        "Image with filename as alt text should be a 6.A violation")
    assert img_vs[0]["wcag_sc"] == "1.1.1"


def test_dna_standalone_decorative_conflict():
    """Novel page: image with role=none but non-empty aria-label.
    This is a 6.B-DecorativeImage violation (conflicting semantics)."""
    html = ('<!DOCTYPE html>\n'
            '<html lang="en"><head><title>Decorative DNA</title></head>\n'
            '<body>\n'
            '<img src="flourish.svg" role="none" '
            'aria-label="Ornamental flourish design">\n'
            '</body></html>')
    rpt = _run_audit_on_html({"deco_conflict.html": html})
    vs = rpt["pages"]["deco_conflict.html"]["violations"]
    dec_vs = [v for v in vs if v["test_id"] == "6.B-DecorativeImage"]
    assert len(dec_vs) == 1, (
        "Decorative image with non-empty aria-label is a 6.B violation")
    assert dec_vs[0]["wcag_sc"] == "1.1.1"


def test_dna_standalone_composite_noninterference():
    """Novel page: auto-playing audio without controls triggers both
    21.D-AudioControl failure AND 3.A-NonInterference composite failure.
    Tests the dependency graph between baseline tests."""
    html = ('<!DOCTYPE html>\n'
            '<html lang="en"><head><title>NI DNA</title></head>\n'
            '<body>\n'
            '<audio src="ambient.mp3" autoplay></audio>\n'
            '<p>Content with auto-playing audio</p>\n'
            '</body></html>')
    rpt = _run_audit_on_html({"ni_fail.html": html})
    r = rpt["pages"]["ni_fail.html"]["test_results"]
    assert r["21.D-AudioControl"] == "fail", (
        "Auto-playing audio without controls must fail 21.D")
    assert r["3.A-NonInterference"] == "fail", (
        "NonInterference must fail when 21.D-AudioControl fails")
    ni = rpt["summary"]["non_interference_results"]
    assert ni["ni_fail.html"] == "fail"


def test_dna_standalone_empty_link():
    """Novel page: anchor element with no text content and no aria-label.
    Must be detected as a 14.A-LinkPurpose violation."""
    html = ('<!DOCTYPE html>\n'
            '<html lang="en"><head><title>Link DNA</title></head>\n'
            '<body>\n'
            '<a href="/nowhere"></a>\n'
            '<a href="/valid">Valid link text</a>\n'
            '</body></html>')
    rpt = _run_audit_on_html({"empty_link.html": html})
    vs = rpt["pages"]["empty_link.html"]["violations"]
    link_vs = [v for v in vs if v["test_id"] == "14.A-LinkPurpose"]
    assert len(link_vs) == 1, (
        "Only the empty link should fail; the valid link should pass")
    assert link_vs[0]["wcag_sc"] == "2.4.4"


def test_dna_standalone_data_table_no_headers():
    """Novel page: table with 3 rows but no <th> elements.
    Must be detected as a 12.B-DataTableHeaderAssociation violation."""
    html = ('<!DOCTYPE html>\n'
            '<html lang="en"><head><title>Table DNA</title></head>\n'
            '<body>\n'
            '<table>\n'
            '  <tr><td>A1</td><td>B1</td></tr>\n'
            '  <tr><td>A2</td><td>B2</td></tr>\n'
            '  <tr><td>A3</td><td>B3</td></tr>\n'
            '</table>\n'
            '</body></html>')
    rpt = _run_audit_on_html({"table_nohdr.html": html})
    vs = rpt["pages"]["table_nohdr.html"]["violations"]
    tbl_vs = [v for v in vs if v["test_id"] == "12.B-DataTableHeaderAssociation"]
    assert len(tbl_vs) == 1
    assert tbl_vs[0]["wcag_sc"] == "1.3.1"


def test_dna_standalone_clean_page_zero_violations():
    """Novel fully-compliant page with every element type present.
    Verifies the tool does not produce false positives on clean content."""
    html = ('<!DOCTYPE html>\n'
            '<html lang="fr"><head><title>Page Propre</title></head>\n'
            '<body>\n'
            '<h1>Bienvenue</h1>\n'
            '<img src="logo.svg" alt="Logo du site">\n'
            '<img src="spacer.gif" alt="" role="presentation">\n'
            '<p style="color: #000000; background-color: #ffffff;">'
            'Texte noir sur blanc</p>\n'
            '<form>\n'
            '  <label for="nom">Nom:</label>\n'
            '  <input type="text" id="nom" name="nom">\n'
            '</form>\n'
            '<a href="/accueil">Accueil</a>\n'
            '<table>\n'
            '  <thead><tr><th>Col 1</th><th>Col 2</th></tr></thead>\n'
            '  <tbody><tr><td>X</td><td>Y</td></tr>\n'
            '  <tr><td>Z</td><td>W</td></tr></tbody>\n'
            '</table>\n'
            '</body></html>')
    rpt = _run_audit_on_html({"clean_fr.html": html})
    vs = rpt["pages"]["clean_fr.html"]["violations"]
    assert len(vs) == 0, (
        f"Clean page should have 0 violations, got {len(vs)}: "
        f"{[v['test_id'] for v in vs]}")
    r = rpt["pages"]["clean_fr.html"]["test_results"]
    failing = [t for t, v in r.items() if v == "fail"]
    assert failing == [], f"Clean page should have no failures: {failing}"
