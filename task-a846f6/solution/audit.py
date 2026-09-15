#!/usr/bin/env python3
"""
Section 508 ICT Baseline Conformance Audit Tool

Analyses HTML files against a subset of the ICT Testing Baseline v3.1
and produces a structured JSON conformance report.
"""

import sys
import os
import json
import re
import glob as glob_mod
from bs4 import BeautifulSoup


# ── colour helpers ────────────────────────────────────────────────────

NAMED_COLOURS = {
    'white': (255, 255, 255), 'black': (0, 0, 0),
    'red': (255, 0, 0), 'green': (0, 128, 0), 'blue': (0, 0, 255),
    'yellow': (255, 255, 0), 'cyan': (0, 255, 255),
    'magenta': (255, 0, 255), 'gray': (128, 128, 128),
    'grey': (128, 128, 128), 'silver': (192, 192, 192),
    'maroon': (128, 0, 0), 'olive': (128, 128, 0),
    'navy': (0, 0, 128), 'teal': (0, 128, 128),
    'purple': (128, 0, 128), 'orange': (255, 165, 0),
}


def parse_colour(s):
    """Return (R, G, B) from a CSS colour string, or None."""
    s = s.strip().lower()
    if s in NAMED_COLOURS:
        return NAMED_COLOURS[s]
    m = re.match(r'^#([0-9a-f]{6})$', s)
    if m:
        h = m.group(1)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    m = re.match(r'^#([0-9a-f]{3})$', s)
    if m:
        h = m.group(1)
        return int(h[0]*2, 16), int(h[1]*2, 16), int(h[2]*2, 16)
    m = re.match(r'^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$', s)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None


def _linearise(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(r, g, b):
    return 0.2126 * _linearise(r) + 0.7152 * _linearise(g) + 0.0722 * _linearise(b)


def contrast_ratio(l1, l2):
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# ── inline-style helpers ──────────────────────────────────────────────

def parse_styles(style_str):
    props = {}
    if not style_str:
        return props
    for part in style_str.split(';'):
        if ':' in part:
            k, v = part.split(':', 1)
            props[k.strip().lower()] = v.strip()
    return props


def font_size_pt(styles):
    fs = styles.get('font-size', '')
    m = re.match(r'(\d+(?:\.\d+)?)\s*(pt|px|em|rem)', fs)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2)
    if unit == 'pt':
        return val
    if unit == 'px':
        return val * 0.75
    if unit in ('em', 'rem'):
        return val * 12.0
    return None


def is_large_text(element, styles):
    pt = font_size_pt(styles)
    if pt is None:
        # headings without explicit size count as large
        return element.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6')
    fw = styles.get('font-weight', '')
    bold = (fw in ('bold', '700', '800', '900')
            or element.name in ('b', 'strong', 'h1', 'h2', 'h3',
                                'h4', 'h5', 'h6'))
    if pt >= 18:
        return True
    if pt >= 14 and bold:
        return True
    return False


# ── accessible-name computation ───────────────────────────────────────

def _acc_name_from_labelledby(el, soup):
    lb = el.get('aria-labelledby')
    if not lb:
        return None
    parts = []
    for ref_id in lb.split():
        ref = soup.find(id=ref_id)
        if ref:
            parts.append(ref.get_text(strip=True))
    result = ' '.join(parts)
    return result if result else None


def acc_name_img(img, soup):
    n = _acc_name_from_labelledby(img, soup)
    if n:
        return n
    al = img.get('aria-label', '')
    if al and al.strip():
        return al.strip()
    alt = img.get('alt')
    if alt is not None:
        return alt  # may be ''
    t = img.get('title', '')
    if t and t.strip():
        return t.strip()
    return None


def acc_name_form(el, soup):
    n = _acc_name_from_labelledby(el, soup)
    if n:
        return n
    al = el.get('aria-label', '')
    if al and al.strip():
        return al.strip()
    # <label for="id">
    el_id = el.get('id')
    if el_id:
        label = soup.find('label', attrs={'for': el_id})
        if label:
            txt = label.get_text(strip=True)
            if txt:
                return txt
    # wrapping <label>
    parent = el.parent
    while parent:
        if parent.name == 'label':
            txt = parent.get_text(strip=True)
            if txt:
                return txt
            break
        parent = parent.parent
    # title attribute
    t = el.get('title', '')
    if t and t.strip():
        return t.strip()
    # button text content
    if el.name == 'button':
        txt = el.get_text(strip=True)
        if txt:
            return txt
    if el.name == 'input' and el.get('type', '') in ('submit', 'button', 'reset'):
        v = el.get('value', '')
        if v:
            return v
    return None


def acc_name_link(el, soup):
    n = _acc_name_from_labelledby(el, soup)
    if n:
        return n
    al = el.get('aria-label', '')
    if al and al.strip():
        return al.strip()
    # text content including child img alt
    parts = []
    for child in el.descendants:
        if isinstance(child, str):
            s = child.strip()
            if s:
                parts.append(s)
        elif getattr(child, 'name', None) == 'img':
            a = child.get('alt')
            if a:
                parts.append(a)
    result = ' '.join(parts)
    if result:
        return result
    t = el.get('title', '')
    if t and t.strip():
        return t.strip()
    return None


# ── filename pattern ──────────────────────────────────────────────────

_FILENAME_RE = re.compile(
    r'.*\.(png|jpe?g|gif|svg|bmp|webp|tiff|ico)\s*$', re.IGNORECASE)


def is_filename_alt(text):
    return bool(_FILENAME_RE.match(text.strip()))


# ── individual baseline tests ────────────────────────────────────────

def check_15a(soup):
    html = soup.find('html')
    if not html or not (html.get('lang') or '').strip():
        return [{
            'test_id': '15.A-LanguagePage', 'wcag_sc': '3.1.1',
            'element': '<html>',
            'message': 'The html element is missing a lang attribute',
        }]
    return []


def check_11a(soup):
    title = soup.find('title')
    if not title or not title.get_text(strip=True):
        return [{
            'test_id': '11.A-PageTitled', 'wcag_sc': '2.4.2',
            'element': '<title>',
            'message': 'Page is missing a non-empty title element',
        }]
    return []


def check_6a(soup):
    violations = []
    for img in soup.find_all('img'):
        role = (img.get('role') or '').lower()
        if role in ('presentation', 'none'):
            continue
        alt = img.get('alt')
        if alt is not None and alt == '':
            continue
        if img.get('aria-hidden') == 'true':
            continue
        name = acc_name_img(img, soup)
        src = img.get('src', '?')
        if name is None:
            violations.append({
                'test_id': '6.A-MeaningfulImage', 'wcag_sc': '1.1.1',
                'element': f'<img src="{src}">',
                'message': 'Image has no text alternative',
            })
        elif is_filename_alt(name):
            violations.append({
                'test_id': '6.A-MeaningfulImage', 'wcag_sc': '1.1.1',
                'element': f'<img src="{src}" alt="{name}">',
                'message': f'Image text alternative is a filename: "{name}"',
            })
    return violations


def check_6b(soup):
    violations = []
    for img in soup.find_all('img'):
        role = (img.get('role') or '').lower()
        if role not in ('presentation', 'none'):
            continue
        alt = img.get('alt', '')
        aria = img.get('aria-label', '')
        if alt and alt.strip():
            violations.append({
                'test_id': '6.B-DecorativeImage', 'wcag_sc': '1.1.1',
                'element': f'<img src="{img.get("src","?")}" role="{role}" alt="{alt}">',
                'message': f'Image has role="{role}" but non-empty alt text',
            })
        elif aria and aria.strip():
            violations.append({
                'test_id': '6.B-DecorativeImage', 'wcag_sc': '1.1.1',
                'element': f'<img src="{img.get("src","?")}" role="{role}" aria-label="{aria}">',
                'message': f'Image has role="{role}" but non-empty aria-label',
            })
    return violations


def check_8a(soup):
    violations = []
    for el in soup.find_all(style=True):
        styles = parse_styles(el.get('style', ''))
        fg_s = styles.get('color')
        bg_s = styles.get('background-color') or styles.get('background')
        if not fg_s or not bg_s:
            continue
        fg = parse_colour(fg_s)
        bg = parse_colour(bg_s)
        if fg is None or bg is None:
            continue
        ratio = contrast_ratio(relative_luminance(*fg),
                               relative_luminance(*bg))
        large = is_large_text(el, styles)
        threshold = 3.0 if large else 4.5
        if ratio < threshold:
            txt = el.get_text(strip=True)[:50]
            ttype = 'large' if large else 'normal'
            violations.append({
                'test_id': '8.A-Contrast', 'wcag_sc': '1.4.3',
                'element': f'<{el.name}> "{txt}"',
                'message': (f'Contrast ratio {ratio:.2f}:1 below '
                            f'{threshold}:1 for {ttype} text '
                            f'(fg={fg_s}, bg={bg_s})'),
            })
    return violations


def check_10a(soup):
    violations = []
    SKIP_TYPES = ('hidden', 'submit', 'button', 'reset', 'image')
    for ctrl in soup.find_all(['input', 'select', 'textarea']):
        itype = (ctrl.get('type', 'text').lower()
                 if ctrl.name == 'input' else None)
        if itype in SKIP_TYPES:
            continue
        style = (ctrl.get('style') or '').replace(' ', '')
        if 'display:none' in style or 'visibility:hidden' in style:
            continue
        if not acc_name_form(ctrl, soup):
            tstr = itype or ctrl.name
            violations.append({
                'test_id': '10.A-FormName', 'wcag_sc': '4.1.2',
                'element': f'<{ctrl.name} type="{tstr}" name="{ctrl.get("name","")}">',
                'message': 'Form control has no accessible name',
            })
    for btn in soup.find_all('button'):
        if not acc_name_form(btn, soup):
            violations.append({
                'test_id': '10.A-FormName', 'wcag_sc': '4.1.2',
                'element': '<button>',
                'message': 'Button has no accessible name',
            })
    return violations


def check_14a(soup):
    violations = []
    for a in soup.find_all('a', href=True):
        name = acc_name_link(a, soup)
        if not name or not name.strip():
            violations.append({
                'test_id': '14.A-LinkPurpose', 'wcag_sc': '2.4.4',
                'element': f'<a href="{a.get("href","")}">',
                'message': 'Link has no accessible name',
            })
    return violations


def check_12b(soup):
    violations = []
    for table in soup.find_all('table'):
        role = (table.get('role') or '').lower()
        if role in ('presentation', 'none'):
            continue
        rows = table.find_all('tr')
        if len(rows) < 2:
            continue
        ths = table.find_all('th')
        aria_hdrs = table.find_all(
            attrs={'role': re.compile(r'columnheader|rowheader')})
        if not ths and not aria_hdrs:
            violations.append({
                'test_id': '12.B-DataTableHeaderAssociation',
                'wcag_sc': '1.3.1',
                'element': '<table>',
                'message': 'Data table has no header cells',
            })
    return violations


def check_21d(soup):
    violations = []
    for audio in soup.find_all('audio'):
        if audio.get('autoplay') is not None:
            if audio.get('controls') is None:
                violations.append({
                    'test_id': '21.D-AudioControl', 'wcag_sc': '1.4.2',
                    'element': f'<audio src="{audio.get("src","?")}" autoplay>',
                    'message': 'Audio auto-plays without controls',
                })
    for video in soup.find_all('video'):
        if video.get('autoplay') is not None:
            if video.get('controls') is None and video.get('muted') is None:
                violations.append({
                    'test_id': '21.D-AudioControl', 'wcag_sc': '1.4.2',
                    'element': f'<video autoplay>',
                    'message': 'Video auto-plays without controls or muted',
                })
    return violations


# ── applicability (when zero violations) ──────────────────────────────

def _applicable(test_id, soup):
    """Return 'pass' if relevant content exists, else 'not_applicable'."""
    if test_id in ('15.A-LanguagePage', '11.A-PageTitled'):
        return 'pass'
    if test_id == '6.A-MeaningfulImage':
        for img in soup.find_all('img'):
            role = (img.get('role') or '').lower()
            if role in ('presentation', 'none'):
                continue
            if img.get('alt') == '':
                continue
            if img.get('aria-hidden') == 'true':
                continue
            return 'pass'
        return 'not_applicable'
    if test_id == '6.B-DecorativeImage':
        for img in soup.find_all('img'):
            role = (img.get('role') or '').lower()
            if role in ('presentation', 'none') or img.get('alt') == '':
                return 'pass'
        return 'not_applicable'
    if test_id == '8.A-Contrast':
        for el in soup.find_all(style=True):
            styles = parse_styles(el.get('style', ''))
            bg = styles.get('background-color') or styles.get('background')
            if styles.get('color') and bg:
                return 'pass'
        return 'not_applicable'
    if test_id == '10.A-FormName':
        skip = ('hidden', 'submit', 'button', 'reset', 'image')
        for ctrl in soup.find_all(['input', 'select', 'textarea']):
            itype = (ctrl.get('type', 'text').lower()
                     if ctrl.name == 'input' else None)
            if itype not in skip:
                return 'pass'
        return 'not_applicable'
    if test_id == '14.A-LinkPurpose':
        return 'pass' if soup.find_all('a', href=True) else 'not_applicable'
    if test_id == '12.B-DataTableHeaderAssociation':
        for t in soup.find_all('table'):
            role = (t.get('role') or '').lower()
            if role in ('presentation', 'none'):
                continue
            if len(t.find_all('tr')) >= 2:
                return 'pass'
        return 'not_applicable'
    if test_id == '21.D-AudioControl':
        for a in soup.find_all(['audio', 'video']):
            if a.get('autoplay') is not None:
                return 'pass'
        return 'not_applicable'
    return 'pass'


# ── page-level audit ──────────────────────────────────────────────────

CHECKS = [
    ('15.A-LanguagePage', check_15a),
    ('11.A-PageTitled', check_11a),
    ('6.A-MeaningfulImage', check_6a),
    ('6.B-DecorativeImage', check_6b),
    ('8.A-Contrast', check_8a),
    ('10.A-FormName', check_10a),
    ('14.A-LinkPurpose', check_14a),
    ('12.B-DataTableHeaderAssociation', check_12b),
    ('21.D-AudioControl', check_21d),
]

NI_DEPENDS = ['21.D-AudioControl']


def audit_page(path):
    with open(path, encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')

    all_violations = []
    results = {}
    for tid, fn in CHECKS:
        vs = fn(soup)
        all_violations.extend(vs)
        results[tid] = 'fail' if vs else _applicable(tid, soup)

    # composite NonInterference
    ni_fail = any(results.get(d) == 'fail' for d in NI_DEPENDS)
    results['3.A-NonInterference'] = 'fail' if ni_fail else 'pass'

    return {'violations': all_violations, 'test_results': results}


# ── main ──────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) != 3:
        print('Usage: python3 audit.py <pages_dir> <output.json>')
        sys.exit(1)

    pages_dir, out_path = sys.argv[1], sys.argv[2]
    html_files = sorted(glob_mod.glob(os.path.join(pages_dir, '*.html')))

    report = {
        'pages': {},
        'summary': {
            'total_pages': len(html_files),
            'total_violations': 0,
            'violations_by_test': {},
            'non_interference_results': {},
        },
    }

    for fp in html_files:
        fname = os.path.basename(fp)
        result = audit_page(fp)
        report['pages'][fname] = result
        for v in result['violations']:
            tid = v['test_id']
            report['summary']['violations_by_test'][tid] = (
                report['summary']['violations_by_test'].get(tid, 0) + 1)
            report['summary']['total_violations'] += 1
        report['summary']['non_interference_results'][fname] = (
            result['test_results'].get('3.A-NonInterference', 'pass'))

    with open(out_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f'Audit complete: {report["summary"]["total_pages"]} pages, '
          f'{report["summary"]["total_violations"]} violations')


if __name__ == '__main__':
    main()
