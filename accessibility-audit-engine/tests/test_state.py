
"""Verification tests for the Section 508 Conformance Audit Tool."""

import json
import os
import subprocess
import pytest


def load_report():
    with open('/app/report.json') as f:
        return json.load(f)


def get_findings(report, page, test_id=None, result=None):
    """Get findings for a page, optionally filtered by test_id and result."""
    if page not in report.get('pages', {}):
        return []
    findings = report['pages'][page].get('findings', [])
    if test_id:
        findings = [f for f in findings if f.get('test_id') == test_id]
    if result:
        findings = [f for f in findings if f.get('result') == result]
    return findings


def find_by_element(findings, element_substr):
    """Find findings whose element field contains a substring."""
    return [f for f in findings if element_substr.lower() in f.get('element', '').lower()]


# ─── Report Structure ───

class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists('/app/report.json'), "report.json must exist at /app/report.json"

    def test_report_valid_json(self):
        report = load_report()
        assert 'pages' in report, "Report must have a 'pages' key"

    def test_all_pages_present(self):
        report = load_report()
        for page in ['index.html', 'form.html', 'content.html', 'complex.html', 'styled.html']:
            assert page in report['pages'], f"{page} must be in report"

    def test_finding_structure(self):
        report = load_report()
        for page_name, page_data in report['pages'].items():
            assert 'findings' in page_data, f"{page_name} must have findings"
            for f in page_data['findings']:
                assert 'test_id' in f, f"Finding in {page_name} missing test_id"
                assert 'result' in f, f"Finding in {page_name} missing result"
                assert f['result'] in ('PASS', 'FAIL'), f"Result must be PASS or FAIL"
                assert 'wcag_sc' in f, f"Finding in {page_name} missing wcag_sc"
                assert 'element' in f, f"Finding in {page_name} missing element"


# ─── index.html Tests ───

class TestIndexPage:
    def test_missing_lang(self):
        """index.html has <html> without lang attribute -> 13.A FAIL"""
        report = load_report()
        lang_fails = get_findings(report, 'index.html', '13.A-LanguageOfPage', 'FAIL')
        assert len(lang_fails) >= 1, "Should detect missing lang on <html>"

    def test_contrast_failure_notice(self):
        """#notice has color #777777 on #fff (14px) -> ~4.48:1 < 4.5:1 -> FAIL"""
        report = load_report()
        contrast_fails = get_findings(report, 'index.html', '8.A-ContrastMinimum', 'FAIL')
        notice_fails = find_by_element(contrast_fails, 'notice')
        assert len(notice_fails) >= 1, "#notice (#777777, 14px) should fail contrast"

    def test_contrast_failure_terms(self):
        """#terms has color #969696 on #fff (19px bold) -> ~2.96:1 < 3:1 -> FAIL"""
        report = load_report()
        contrast_fails = get_findings(report, 'index.html', '8.A-ContrastMinimum', 'FAIL')
        terms_fails = find_by_element(contrast_fails, 'terms')
        assert len(terms_fails) >= 1, "#terms (#969696, 19px bold = large text) should fail contrast (2.96 < 3.0)"

    def test_contrast_pass_large_text(self):
        """h2#updates has color #949494 on #fff (24px) -> ~3.04:1 >= 3:1 -> PASS"""
        report = load_report()
        contrast_passes = get_findings(report, 'index.html', '8.A-ContrastMinimum', 'PASS')
        updates_passes = find_by_element(contrast_passes, 'updates')
        assert len(updates_passes) >= 1, "h2#updates (#949494, 24px large text) should pass contrast (3.04 >= 3.0)"

    def test_contrast_pass_sidebar(self):
        """#sidebar has color #767676 on #fff (14px) -> ~4.54:1 >= 4.5:1 -> PASS"""
        report = load_report()
        contrast_passes = get_findings(report, 'index.html', '8.A-ContrastMinimum', 'PASS')
        sidebar_passes = find_by_element(contrast_passes, 'sidebar')
        assert len(sidebar_passes) >= 1, "#sidebar (#767676, 14px) should pass contrast (4.54 >= 4.5)"

    def test_image_missing_alt(self):
        """img[src='chart-q4.png'] has no alt -> FAIL"""
        report = load_report()
        image_fails = get_findings(report, 'index.html', '6.A-MeaningfulImage', 'FAIL')
        chart_fails = find_by_element(image_fails, 'chart-q4')
        assert len(chart_fails) >= 1, "Image without alt attribute should fail 6.A"

    def test_image_role_conflict(self):
        """img with role=presentation and non-empty alt -> FAIL"""
        report = load_report()
        all_image_fails = [f for f in get_findings(report, 'index.html')
                          if '6.' in f.get('test_id', '') and f['result'] == 'FAIL']
        alert_fails = find_by_element(all_image_fails, 'alert-icon')
        assert len(alert_fails) >= 1, "Image with role=presentation and non-empty alt should be flagged"

    def test_image_correct_decorative(self):
        """img[src='decorative-line.png'] with alt='' and role=presentation -> PASS"""
        report = load_report()
        image_passes = [f for f in get_findings(report, 'index.html')
                       if '6.' in f.get('test_id', '') and f['result'] == 'PASS']
        deco_passes = find_by_element(image_passes, 'decorative-line')
        assert len(deco_passes) >= 1, "Correctly decorative image should pass"

    def test_image_correct_meaningful(self):
        """img[src='team-photo.jpg'] with descriptive alt -> PASS"""
        report = load_report()
        image_passes = [f for f in get_findings(report, 'index.html')
                       if '6.' in f.get('test_id', '') and f['result'] == 'PASS']
        team_passes = find_by_element(image_passes, 'team-photo')
        assert len(team_passes) >= 1, "Image with descriptive alt should pass"

    def test_link_no_name(self):
        """a[href='/data'] contains only img with alt='' -> no accessible name -> FAIL"""
        report = load_report()
        link_fails = get_findings(report, 'index.html', '14.A-LinkPurpose', 'FAIL')
        data_fails = find_by_element(link_fails, '/data')
        assert len(data_fails) >= 1, "Link with only empty-alt image should fail 14.A"

    def test_links_with_text(self):
        """Links with text content should PASS"""
        report = load_report()
        link_passes = get_findings(report, 'index.html', '14.A-LinkPurpose', 'PASS')
        assert len(link_passes) >= 2, "Links with text (reports, contact) should pass"


# ─── form.html Tests ───

class TestFormPage:
    def test_lang_present(self):
        """form.html has lang='en' -> 13.A PASS"""
        report = load_report()
        lang_passes = get_findings(report, 'form.html', '13.A-LanguageOfPage', 'PASS')
        assert len(lang_passes) >= 1, "form.html has lang='en' so should pass 13.A"

    def test_missing_title(self):
        """form.html has no <title> -> 11.A FAIL"""
        report = load_report()
        title_fails = get_findings(report, 'form.html', '11.A-PageTitle', 'FAIL')
        assert len(title_fails) >= 1, "form.html with no title element should fail 11.A"

    def test_form_name_passes(self):
        """Forms with labels should PASS: fullname (label[for]), search (aria-label),
        phone (title), submit-btn (text content)"""
        report = load_report()
        form_passes = get_findings(report, 'form.html', '10.A-FormName', 'PASS')
        assert len(form_passes) >= 3, "At least 3 form elements should pass (fullname, search, phone, submit-btn)"

    def test_form_name_failures(self):
        """Forms without labels should FAIL: email, state, comments, hidden-submit"""
        report = load_report()
        form_fails = get_findings(report, 'form.html', '10.A-FormName', 'FAIL')
        assert len(form_fails) >= 3, "At least 3 form elements should fail (email, state, comments, hidden-submit)"

    def test_form_label_for_id(self):
        """input#fullname has label[for='fullname'] -> PASS"""
        report = load_report()
        form_passes = get_findings(report, 'form.html', '10.A-FormName', 'PASS')
        fullname = find_by_element(form_passes, 'fullname')
        assert len(fullname) >= 1, "input#fullname with matching label should pass"

    def test_form_aria_label(self):
        """input#search has aria-label -> PASS"""
        report = load_report()
        form_passes = get_findings(report, 'form.html', '10.A-FormName', 'PASS')
        search = find_by_element(form_passes, 'search')
        assert len(search) >= 1, "input#search with aria-label should pass"

    def test_form_no_label(self):
        """input#email has no accessible name source -> FAIL"""
        report = load_report()
        form_fails = get_findings(report, 'form.html', '10.A-FormName', 'FAIL')
        email = find_by_element(form_fails, 'email')
        assert len(email) >= 1, "input#email with no label should fail"

    def test_iframe_missing_title(self):
        """iframe[src='widget.html'] has no title -> 15.A FAIL"""
        report = load_report()
        iframe_fails = get_findings(report, 'form.html', '15.A-IframeName', 'FAIL')
        assert len(iframe_fails) >= 1, "iframe without title should fail 15.A"

    def test_iframe_with_title(self):
        """iframe[src='help.html'] has title -> 15.A PASS"""
        report = load_report()
        iframe_passes = get_findings(report, 'form.html', '15.A-IframeName', 'PASS')
        assert len(iframe_passes) >= 1, "iframe with title should pass 15.A"


# ─── content.html Tests ───

class TestContentPage:
    def test_lang_pass(self):
        report = load_report()
        lang = get_findings(report, 'content.html', '13.A-LanguageOfPage', 'PASS')
        assert len(lang) >= 1

    def test_title_pass(self):
        report = load_report()
        title = get_findings(report, 'content.html', '11.A-PageTitle', 'PASS')
        assert len(title) >= 1

    def test_contrast_gray_bg_pass(self):
        """#dark-on-gray (#595959 on #f0f0f0) -> ~6.15:1 >= 4.5:1 -> PASS"""
        report = load_report()
        contrast_passes = get_findings(report, 'content.html', '8.A-ContrastMinimum', 'PASS')
        dark = find_by_element(contrast_passes, 'dark-on-gray')
        assert len(dark) >= 1, "#595959 on gray #f0f0f0 background should pass"

    def test_contrast_gray_bg_fail(self):
        """#light-on-gray (#8a8a8a on #f0f0f0) -> ~3.03:1 < 4.5:1 -> FAIL"""
        report = load_report()
        contrast_fails = get_findings(report, 'content.html', '8.A-ContrastMinimum', 'FAIL')
        light = find_by_element(contrast_fails, 'light-on-gray')
        assert len(light) >= 1, "#8a8a8a on gray #f0f0f0 background should fail"

    def test_link_aria_label(self):
        """a[href='/home'] has aria-label -> PASS"""
        report = load_report()
        link_passes = get_findings(report, 'content.html', '14.A-LinkPurpose', 'PASS')
        home = find_by_element(link_passes, '/home')
        assert len(home) >= 1, "Link with aria-label should pass"

    def test_link_aria_labelledby(self):
        """a[href='/resources'] has aria-labelledby -> PASS"""
        report = load_report()
        link_passes = get_findings(report, 'content.html', '14.A-LinkPurpose', 'PASS')
        resources = find_by_element(link_passes, '/resources')
        assert len(resources) >= 1, "Link with aria-labelledby should pass"

    def test_link_title_fallback(self):
        """a[href='/search'] has title (no text content) -> PASS"""
        report = load_report()
        link_passes = get_findings(report, 'content.html', '14.A-LinkPurpose', 'PASS')
        search = find_by_element(link_passes, '/search')
        assert len(search) >= 1, "Link with title fallback should pass"

    def test_link_empty(self):
        """a[href='/menu'] has no accessible name -> FAIL"""
        report = load_report()
        link_fails = get_findings(report, 'content.html', '14.A-LinkPurpose', 'FAIL')
        menu = find_by_element(link_fails, '/menu')
        assert len(menu) >= 1, "Empty link should fail"

    def test_image_missing_alt(self):
        """img[src='warning.svg'] has no alt -> FAIL"""
        report = load_report()
        img_fails = [f for f in get_findings(report, 'content.html')
                    if '6.' in f.get('test_id', '') and f['result'] == 'FAIL']
        warning = find_by_element(img_fails, 'warning')
        assert len(warning) >= 1, "Image without alt should fail"


# ─── complex.html Tests ───

class TestComplexPage:
    def test_lang_pass(self):
        report = load_report()
        lang = get_findings(report, 'complex.html', '13.A-LanguageOfPage', 'PASS')
        assert len(lang) >= 1

    def test_title_pass(self):
        report = load_report()
        title = get_findings(report, 'complex.html', '11.A-PageTitle', 'PASS')
        assert len(title) >= 1

    def test_nested_bg_contrast_pass(self):
        """#1a1a1a on inherited #d4d4d4 bg (section > div > p) -> ~11.7:1 -> PASS"""
        report = load_report()
        contrast_passes = get_findings(report, 'complex.html', '8.A-ContrastMinimum', 'PASS')
        deep_pass = find_by_element(contrast_passes, 'deep-contrast-pass')
        assert len(deep_pass) >= 1, "#1a1a1a on #d4d4d4 background should pass"

    def test_nested_bg_contrast_fail(self):
        """#a8a8a8 on inherited #d4d4d4 bg (section > div > p) -> ~1.6:1 -> FAIL"""
        report = load_report()
        contrast_fails = get_findings(report, 'complex.html', '8.A-ContrastMinimum', 'FAIL')
        deep_fail = find_by_element(contrast_fails, 'deep-contrast-fail')
        assert len(deep_fail) >= 1, "#a8a8a8 on #d4d4d4 background should fail"

    def test_bg_sensitive_fail(self):
        """#767676 on inherited #d4d4d4 bg -> ~3.07:1 < 4.5:1 -> FAIL.
        On white bg this would be ~4.54:1 PASS, so correct bg resolution is critical."""
        report = load_report()
        contrast_fails = get_findings(report, 'complex.html', '8.A-ContrastMinimum', 'FAIL')
        bgs = find_by_element(contrast_fails, 'bg-sensitive')
        assert len(bgs) >= 1, "#767676 on inherited #d4d4d4 must FAIL (3.07 < 4.5); white bg would wrongly PASS"

    def test_rgb_notation_fail(self):
        """rgb(160,160,160) on white -> ~2.6:1 -> FAIL"""
        report = load_report()
        contrast_fails = get_findings(report, 'complex.html', '8.A-ContrastMinimum', 'FAIL')
        rgb_fail = find_by_element(contrast_fails, 'rgb-func-fail')
        assert len(rgb_fail) >= 1, "rgb(160,160,160) on white should fail contrast (requires rgb() parsing)"

    def test_rgb_notation_pass(self):
        """rgb(40,40,40) on white -> ~14.7:1 -> PASS"""
        report = load_report()
        contrast_passes = get_findings(report, 'complex.html', '8.A-ContrastMinimum', 'PASS')
        rgb_pass = find_by_element(contrast_passes, 'rgb-func-pass')
        assert len(rgb_pass) >= 1, "rgb(40,40,40) on white should pass contrast (requires rgb() parsing)"

    def test_implicit_label_wrapping(self):
        """input#wrapped-field is inside a wrapping <label> -> PASS"""
        report = load_report()
        form_passes = get_findings(report, 'complex.html', '10.A-FormName', 'PASS')
        wrapped = find_by_element(form_passes, 'wrapped-field')
        assert len(wrapped) >= 1, "Input inside wrapping <label> should pass form name test (implicit label association)"

    def test_orphan_input_fail(self):
        """input#orphan-field has no accessible name source -> FAIL"""
        report = load_report()
        form_fails = get_findings(report, 'complex.html', '10.A-FormName', 'FAIL')
        orphan = find_by_element(form_fails, 'orphan-field')
        assert len(orphan) >= 1, "Input with no accessible name source should fail"

    def test_multi_id_labelledby(self):
        """input#multi-ref has aria-labelledby='lbl-prefix lbl-zipcode'.
        First ref is empty span, second has 'Billing ZIP Code' -> name derived from both -> PASS."""
        report = load_report()
        form_passes = get_findings(report, 'complex.html', '10.A-FormName', 'PASS')
        multi = find_by_element(form_passes, 'multi-ref')
        assert len(multi) >= 1, "Input with aria-labelledby referencing multiple IDs (including empty) should pass"

    def test_submit_value_name(self):
        """input[type=submit]#submit-val has value='Confirm Order' -> PASS"""
        report = load_report()
        form_passes = get_findings(report, 'complex.html', '10.A-FormName', 'PASS')
        submit = find_by_element(form_passes, 'submit-val')
        assert len(submit) >= 1, "Submit input with value attribute should pass form name test"

    def test_link_child_img_alt(self):
        """a[href='/dashboard'] contains img with alt='Dashboard Overview' -> PASS"""
        report = load_report()
        link_passes = get_findings(report, 'complex.html', '14.A-LinkPurpose', 'PASS')
        dash = find_by_element(link_passes, '/dashboard')
        assert len(dash) >= 1, "Link containing img with alt text should pass"

    def test_link_whitespace_only(self):
        """a[href='/void'] has only whitespace text -> FAIL"""
        report = load_report()
        link_fails = get_findings(report, 'complex.html', '14.A-LinkPurpose', 'FAIL')
        void = find_by_element(link_fails, '/void')
        assert len(void) >= 1, "Link with only whitespace text should fail"

    def test_image_no_alt(self):
        """img[src='unlabeled-photo.jpg'] has no alt -> FAIL"""
        report = load_report()
        img_fails = [f for f in get_findings(report, 'complex.html')
                    if '6.' in f.get('test_id', '') and f['result'] == 'FAIL']
        unlabeled = find_by_element(img_fails, 'unlabeled-photo')
        assert len(unlabeled) >= 1, "Image without alt attribute should fail"

    def test_decorative_image_no_role(self):
        """img[src='pixel.gif'] with alt='' (no role=presentation) -> PASS as decorative"""
        report = load_report()
        img_passes = [f for f in get_findings(report, 'complex.html')
                     if '6.' in f.get('test_id', '') and f['result'] == 'PASS']
        pixel = find_by_element(img_passes, 'pixel')
        assert len(pixel) >= 1, "Image with alt='' should pass as decorative"

    def test_meaningful_image(self):
        """img[src='org-chart.png'] with descriptive alt -> PASS"""
        report = load_report()
        img_passes = [f for f in get_findings(report, 'complex.html')
                     if '6.' in f.get('test_id', '') and f['result'] == 'PASS']
        org_chart = find_by_element(img_passes, 'org-chart')
        assert len(org_chart) >= 1, "Image with descriptive alt should pass"

    def test_iframe_with_title(self):
        report = load_report()
        iframe_passes = get_findings(report, 'complex.html', '15.A-IframeName', 'PASS')
        assert len(iframe_passes) >= 1

    def test_iframe_without_title(self):
        report = load_report()
        iframe_fails = get_findings(report, 'complex.html', '15.A-IframeName', 'FAIL')
        assert len(iframe_fails) >= 1


# ─── styled.html Tests (CSS <style> block handling) ───

class TestStyledPage:
    def test_lang_pass(self):
        report = load_report()
        lang = get_findings(report, 'styled.html', '13.A-LanguageOfPage', 'PASS')
        assert len(lang) >= 1

    def test_title_pass(self):
        report = load_report()
        title = get_findings(report, 'styled.html', '11.A-PageTitle', 'PASS')
        assert len(title) >= 1

    def test_css_contrast_caption_fail(self):
        """#css-caption-fail has class 'caption' -> color:#767676 via CSS,
        parent has class 'report-panel' -> bg:#cccccc via CSS.
        Contrast ~2.83:1 < 4.5:1 -> FAIL.
        Requires parsing <style> block CSS rules."""
        report = load_report()
        contrast_fails = get_findings(report, 'styled.html', '8.A-ContrastMinimum', 'FAIL')
        caption = find_by_element(contrast_fails, 'css-caption-fail')
        assert len(caption) >= 1, "CSS-styled #767676 on #cccccc bg should fail contrast (requires <style> parsing)"

    def test_css_contrast_body_pass(self):
        """#css-body-pass has class 'body-text' -> color:#222222 via CSS,
        on bg #cccccc -> ~9.90:1 >= 4.5:1 -> PASS."""
        report = load_report()
        contrast_passes = get_findings(report, 'styled.html', '8.A-ContrastMinimum', 'PASS')
        body = find_by_element(contrast_passes, 'css-body-pass')
        assert len(body) >= 1, "CSS-styled #222222 on #cccccc bg should pass contrast"

    def test_css_large_text_heading_pass(self):
        """#css-heading has class 'section-title' -> color:#444444, font-size:26px via CSS,
        on bg #cccccc. 26px is large text, contrast ~6.06:1 >= 3:1 -> PASS."""
        report = load_report()
        contrast_passes = get_findings(report, 'styled.html', '8.A-ContrastMinimum', 'PASS')
        heading = find_by_element(contrast_passes, 'css-heading')
        assert len(heading) >= 1, "CSS-styled large text heading should pass contrast"

    def test_image_with_alt_pass(self):
        report = load_report()
        img_passes = [f for f in get_findings(report, 'styled.html')
                     if '6.' in f.get('test_id', '') and f['result'] == 'PASS']
        chart = find_by_element(img_passes, 'perf-chart')
        assert len(chart) >= 1, "Image with descriptive alt should pass"

    def test_image_no_alt_fail(self):
        report = load_report()
        img_fails = [f for f in get_findings(report, 'styled.html')
                    if '6.' in f.get('test_id', '') and f['result'] == 'FAIL']
        untagged = find_by_element(img_fails, 'untagged-photo')
        assert len(untagged) >= 1, "Image without alt should fail"

    def test_link_pass(self):
        report = load_report()
        link_passes = get_findings(report, 'styled.html', '14.A-LinkPurpose', 'PASS')
        assert len(link_passes) >= 1, "Link with text should pass"

    def test_link_fail(self):
        report = load_report()
        link_fails = get_findings(report, 'styled.html', '14.A-LinkPurpose', 'FAIL')
        assert len(link_fails) >= 1, "Empty link should fail"

    def test_form_pass(self):
        report = load_report()
        form_passes = get_findings(report, 'styled.html', '10.A-FormName', 'PASS')
        search = find_by_element(form_passes, 'css-search')
        assert len(search) >= 1, "Input with label[for] should pass"

    def test_form_fail(self):
        report = load_report()
        form_fails = get_findings(report, 'styled.html', '10.A-FormName', 'FAIL')
        orphan = find_by_element(form_fails, 'css-orphan-input')
        assert len(orphan) >= 1, "Input with no label should fail"

    def test_iframe_pass(self):
        report = load_report()
        iframe_passes = get_findings(report, 'styled.html', '15.A-IframeName', 'PASS')
        assert len(iframe_passes) >= 1

    def test_iframe_fail(self):
        report = load_report()
        iframe_fails = get_findings(report, 'styled.html', '15.A-IframeName', 'FAIL')
        assert len(iframe_fails) >= 1


# ─── WCAG SC Mapping Tests ───

class TestWCAGMappings:
    def test_mappings_correct(self):
        """All findings must have correct WCAG SC mappings"""
        report = load_report()
        expected = {
            '6.A-MeaningfulImage': '1.1.1',
            '6.B-DecorativeImage': '1.1.1',
            '8.A-ContrastMinimum': '1.4.3',
            '10.A-FormName': '4.1.2',
            '11.A-PageTitle': '2.4.2',
            '13.A-LanguageOfPage': '3.1.1',
            '14.A-LinkPurpose': '2.4.4',
            '15.A-IframeName': '4.1.2',
        }
        for page_name, page_data in report['pages'].items():
            for f in page_data['findings']:
                tid = f['test_id']
                if tid in expected:
                    assert f['wcag_sc'] == expected[tid], \
                        f"{tid} should map to {expected[tid]}, got {f['wcag_sc']} in {page_name}"


# ─── Contrast Algorithm Precision Tests ───

class TestContrastPrecision:
    def test_boundary_767676_vs_777777(self):
        """#767676 on white = ~4.54:1 (PASS), #777777 on white = ~4.48:1 (FAIL).
        This tests correct sRGB linearization at the 4.5:1 boundary."""
        test_dir = '/tmp/contrast_boundary_test'
        os.makedirs(test_dir, exist_ok=True)

        html = '''<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Contrast Boundary</title></head>
<body style="background-color: #ffffff;">
    <p id="pass-barely" style="color: #767676; font-size: 14px;">Should pass 4.5:1</p>
    <p id="fail-barely" style="color: #777777; font-size: 14px;">Should fail 4.5:1</p>
</body>
</html>'''
        with open(os.path.join(test_dir, 'boundary.html'), 'w') as f:
            f.write(html)

        out = '/tmp/contrast_boundary_report.json'
        r = subprocess.run(['python3', '/app/audit.py', test_dir, out],
                          capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"Tool failed: {r.stderr}"

        with open(out) as f:
            report = json.load(f)
        findings = report['pages']['boundary.html']['findings']
        contrast = [f for f in findings if f.get('test_id') == '8.A-ContrastMinimum']

        pass_f = [f for f in contrast if 'pass-barely' in f.get('element', '')]
        fail_f = [f for f in contrast if 'fail-barely' in f.get('element', '')]

        assert len(pass_f) >= 1, "Should have a finding for #pass-barely"
        assert len(fail_f) >= 1, "Should have a finding for #fail-barely"
        assert pass_f[0]['result'] == 'PASS', "#767676 on white must PASS (ratio ~4.54 >= 4.5)"
        assert fail_f[0]['result'] == 'FAIL', "#777777 on white must FAIL (ratio ~4.48 < 4.5)"

    def test_large_text_thresholds(self):
        """Large text uses 3:1 threshold. Tests px-to-pt conversion and bold detection."""
        test_dir = '/tmp/large_text_test'
        os.makedirs(test_dir, exist_ok=True)

        html = '''<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Large Text</title></head>
<body style="background-color: #ffffff;">
    <p id="large-pass" style="color: #949494; font-size: 24px;">24px = 18pt, large text, ~3.04:1 >= 3:1</p>
    <p id="large-fail" style="color: #969696; font-size: 24px;">24px, ~2.96:1 < 3:1</p>
    <p id="bold-pass" style="color: #949494; font-size: 19px; font-weight: bold;">19px bold = ~14.25pt bold, large text, ~3.04:1</p>
    <p id="regular-fail" style="color: #949494; font-size: 14px;">14px = ~10.5pt, NOT large text, ~3.04:1 < 4.5:1</p>
</body>
</html>'''
        with open(os.path.join(test_dir, 'large.html'), 'w') as f:
            f.write(html)

        out = '/tmp/large_text_report.json'
        r = subprocess.run(['python3', '/app/audit.py', test_dir, out],
                          capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"Tool failed: {r.stderr}"

        with open(out) as f:
            report = json.load(f)
        findings = report['pages']['large.html']['findings']
        contrast = [f for f in findings if f.get('test_id') == '8.A-ContrastMinimum']

        lp = [f for f in contrast if 'large-pass' in f.get('element', '')]
        lf = [f for f in contrast if 'large-fail' in f.get('element', '')]
        bp = [f for f in contrast if 'bold-pass' in f.get('element', '')]
        rf = [f for f in contrast if 'regular-fail' in f.get('element', '')]

        assert len(lp) >= 1 and lp[0]['result'] == 'PASS', \
            "24px (#949494) is large text, 3.04:1 >= 3:1 -> PASS"
        assert len(lf) >= 1 and lf[0]['result'] == 'FAIL', \
            "24px (#969696) is large text, 2.96:1 < 3:1 -> FAIL"
        assert len(bp) >= 1 and bp[0]['result'] == 'PASS', \
            "19px bold (#949494) is large text (>=14pt bold), 3.04:1 >= 3:1 -> PASS"
        assert len(rf) >= 1 and rf[0]['result'] == 'FAIL', \
            "14px (#949494) is NOT large text, 3.04:1 < 4.5:1 -> FAIL"


# ─── Dynamic Audit Test (anti-cheat) ───

class TestDynamicAudit:
    def test_tool_on_new_page(self):
        """Create a completely new page and verify the tool produces correct results."""
        test_dir = '/tmp/dynamic_audit_test'
        os.makedirs(test_dir, exist_ok=True)

        html = '''<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Dynamic Test Page</title></head>
<body style="background-color: #ffffff;">
    <p id="fail-contrast" style="color: #aaaaaa; font-size: 16px;">Low contrast text</p>
    <p id="pass-contrast" style="color: #333333; font-size: 16px;">Good contrast text</p>
    <img src="photo.png">
    <img src="deco.png" alt="" role="none">
    <a href="/nowhere"></a>
    <a href="/somewhere">Valid Link Text</a>
    <input type="text" id="noname">
    <label for="named">Full Name</label>
    <input type="text" id="named">
    <iframe src="x.html"></iframe>
    <iframe src="y.html" title="Help"></iframe>
</body>
</html>'''
        with open(os.path.join(test_dir, 'dynamic.html'), 'w') as f:
            f.write(html)

        out = '/tmp/dynamic_report.json'
        r = subprocess.run(['python3', '/app/audit.py', test_dir, out],
                          capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"Tool failed: {r.stderr}"
        assert os.path.exists(out)

        with open(out) as f:
            report = json.load(f)

        findings = report['pages']['dynamic.html']['findings']

        # 13.A PASS
        lang = [f for f in findings if f.get('test_id') == '13.A-LanguageOfPage']
        assert any(f['result'] == 'PASS' for f in lang), "Should pass 13.A (lang=en)"

        # 11.A PASS
        title = [f for f in findings if f.get('test_id') == '11.A-PageTitle']
        assert any(f['result'] == 'PASS' for f in title), "Should pass 11.A (has title)"

        # 8.A: #aaaaaa FAIL, #333333 PASS
        contrast = [f for f in findings if f.get('test_id') == '8.A-ContrastMinimum']
        fail_c = find_by_element(contrast, 'fail-contrast')
        pass_c = find_by_element(contrast, 'pass-contrast')
        assert any(f['result'] == 'FAIL' for f in fail_c), "#aaaaaa on white should fail contrast"
        assert any(f['result'] == 'PASS' for f in pass_c), "#333333 on white should pass contrast"

        # 6: photo.png FAIL (no alt)
        imgs = [f for f in findings if '6.' in f.get('test_id', '')]
        img_fails = [f for f in imgs if f['result'] == 'FAIL']
        assert len(img_fails) >= 1, "Image without alt should fail"

        # 6.B: deco.png PASS
        img_passes = [f for f in imgs if f['result'] == 'PASS']
        deco = find_by_element(img_passes, 'deco')
        assert len(deco) >= 1, "Decorative image with alt='' and role=none should pass"

        # 14.A: empty link FAIL, valid link PASS
        links = [f for f in findings if f.get('test_id') == '14.A-LinkPurpose']
        assert any(f['result'] == 'FAIL' for f in links), "Empty link should fail"
        assert any(f['result'] == 'PASS' for f in links), "Link with text should pass"

        # 10.A: noname FAIL, named PASS
        forms = [f for f in findings if f.get('test_id') == '10.A-FormName']
        assert any(f['result'] == 'FAIL' for f in forms), "Unlabeled input should fail"
        assert any(f['result'] == 'PASS' for f in forms), "Labeled input should pass"

        # 15.A: x.html FAIL, y.html PASS
        iframes = [f for f in findings if f.get('test_id') == '15.A-IframeName']
        assert any(f['result'] == 'FAIL' for f in iframes), "Iframe without title should fail"
        assert any(f['result'] == 'PASS' for f in iframes), "Iframe with title should pass"


class TestDynamicEdgeCases:
    def test_rgb_nested_bg_and_implicit_labels(self):
        """Dynamic test combining rgb() colors, nested background inheritance,
        implicit label wrapping, and multi-ID aria-labelledby with empty first ref."""
        test_dir = '/tmp/edge_case_test'
        os.makedirs(test_dir, exist_ok=True)

        html = '''<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Edge Cases</title></head>
<body style="background-color: #ffffff;">
    <div style="background-color: #cccccc;">
        <p id="nested-rgb" style="color: rgb(80, 80, 80); font-size: 16px;">RGB on nested bg</p>
    </div>
    <label>Email Address <input type="text" id="label-wrapped"></label>
    <input type="text" id="no-label">
    <span id="ref-a"></span> <span id="ref-b">Full Name</span>
    <input type="text" id="dual-ref" aria-labelledby="ref-a ref-b">
</body>
</html>'''
        with open(os.path.join(test_dir, 'edge.html'), 'w') as f:
            f.write(html)

        out = '/tmp/edge_report.json'
        r = subprocess.run(['python3', '/app/audit.py', test_dir, out],
                          capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"Tool failed: {r.stderr}"

        with open(out) as f:
            report = json.load(f)

        findings = report['pages']['edge.html']['findings']

        # Contrast: rgb(80,80,80) on inherited #cccccc -> ~5.0:1 -> PASS
        contrast = [f for f in findings if f.get('test_id') == '8.A-ContrastMinimum']
        nested_rgb = find_by_element(contrast, 'nested-rgb')
        assert len(nested_rgb) >= 1, "Should have finding for nested-rgb"
        assert nested_rgb[0]['result'] == 'PASS', "rgb(80,80,80) on #cccccc should pass (~5.0:1 >= 4.5)"

        # Form: wrapping label -> PASS
        forms = [f for f in findings if f.get('test_id') == '10.A-FormName']
        wrapped = find_by_element(forms, 'label-wrapped')
        assert len(wrapped) >= 1, "Should have finding for label-wrapped"
        assert wrapped[0]['result'] == 'PASS', "Input inside wrapping label should pass"

        # Form: no label -> FAIL
        no_label = find_by_element(forms, 'no-label')
        assert len(no_label) >= 1, "Should have finding for no-label"
        assert no_label[0]['result'] == 'FAIL', "Input with no label should fail"

        # Form: dual aria-labelledby (first empty, second has text) -> PASS
        dual = find_by_element(forms, 'dual-ref')
        assert len(dual) >= 1, "Should have finding for dual-ref"
        assert dual[0]['result'] == 'PASS', "Input with multi-ID labelledby (first empty) should still pass"


class TestDynamicCSSAudit:
    def test_tool_handles_style_blocks(self):
        """Create a page with <style> block CSS and verify the tool handles it."""
        test_dir = '/tmp/css_dynamic_test'
        os.makedirs(test_dir, exist_ok=True)

        html = '''<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>CSS Test</title>
<style>
    .container { background-color: #dddddd; }
    .fail-text { color: #999999; font-size: 16px; }
    .pass-text { color: #111111; font-size: 16px; }
</style>
</head>
<body style="background-color: #ffffff;">
    <div class="container">
        <p id="css-dynamic-fail" class="fail-text">Low contrast via CSS</p>
        <p id="css-dynamic-pass" class="pass-text">High contrast via CSS</p>
    </div>
</body>
</html>'''
        with open(os.path.join(test_dir, 'css.html'), 'w') as f:
            f.write(html)

        out = '/tmp/css_dynamic_report.json'
        r = subprocess.run(['python3', '/app/audit.py', test_dir, out],
                          capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"Tool failed: {r.stderr}"

        with open(out) as f:
            report = json.load(f)

        findings = report['pages']['css.html']['findings']
        contrast = [f for f in findings if f.get('test_id') == '8.A-ContrastMinimum']

        fail_f = find_by_element(contrast, 'css-dynamic-fail')
        pass_f = find_by_element(contrast, 'css-dynamic-pass')

        assert len(fail_f) >= 1, "Should detect contrast finding for CSS-styled element"
        assert fail_f[0]['result'] == 'FAIL', "#999999 on #dddddd via CSS should fail contrast"
        assert len(pass_f) >= 1, "Should detect contrast finding for CSS-styled element"
        assert pass_f[0]['result'] == 'PASS', "#111111 on #dddddd via CSS should pass contrast"


# ─── Tool Existence ───

class TestToolExists:
    def test_audit_script_exists(self):
        assert os.path.exists('/app/audit.py'), "Audit tool must exist at /app/audit.py"

    def test_audit_script_executable(self):
        r = subprocess.run(['python3', '/app/audit.py', '--help'],
                          capture_output=True, text=True, timeout=10)
        # Tool should either show help or complain about missing args, not crash on import
        assert r.returncode is not None, "Tool should be runnable"
