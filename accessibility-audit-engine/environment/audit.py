#!/usr/bin/env python3
"""
Section 508 Conformance Audit Tool
Scans HTML files for ICT Testing Baseline conformance issues.
"""

import json
import os
import re
import sys

from bs4 import BeautifulSoup, NavigableString


# ── Color and Contrast ──

def parse_color(color_str):
    """Parse a CSS color string to (R, G, B) tuple with values 0-255."""
    if not color_str:
        return None
    color_str = color_str.strip().lower()
    if color_str.startswith('#'):
        h = color_str[1:]
        if len(h) == 3:
            h = h[0]*2 + h[1]*2 + h[2]*2
        if len(h) == 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    named = {
        'white': (255, 255, 255), 'black': (0, 0, 0),
        'red': (255, 0, 0), 'green': (0, 128, 0), 'blue': (0, 0, 255),
        'gray': (128, 128, 128), 'grey': (128, 128, 128),
        'silver': (192, 192, 192), 'navy': (0, 0, 128),
        'maroon': (128, 0, 0), 'purple': (128, 0, 128),
        'teal': (0, 128, 128), 'olive': (128, 128, 0),
        'aqua': (0, 255, 255), 'fuchsia': (255, 0, 255),
        'lime': (0, 255, 0), 'yellow': (255, 255, 0),
        'orange': (255, 165, 0),
    }
    return named.get(color_str)


def srgb_to_linear(channel_8bit):
    """Convert an 8-bit sRGB channel value to linear light."""
    v = channel_8bit / 255.0
    if v <= 0.04045:
        return v / 12.92
    return ((v + 0.055) / 1.055) ** 2.2


def relative_luminance(r, g, b):
    """Compute relative luminance per WCAG definition."""
    return (0.2126 * srgb_to_linear(r)
          + 0.7152 * srgb_to_linear(g)
          + 0.0722 * srgb_to_linear(b))


def contrast_ratio(lum1, lum2):
    lighter = max(lum1, lum2)
    darker = min(lum1, lum2)
    return (lighter + 0.05) / (darker + 0.05)


# ── CSS / Style Utilities ──

def parse_inline_styles(style_attr):
    if not style_attr:
        return {}
    result = {}
    for decl in style_attr.split(';'):
        if ':' in decl:
            prop, _, val = decl.partition(':')
            result[prop.strip().lower()] = val.strip()
    return result


def get_effective_bg_color(element):
    """Find the background color for an element by checking it and its parent."""
    styles = parse_inline_styles(element.get('style', ''))
    bg_str = styles.get('background-color')
    if bg_str:
        color = parse_color(bg_str)
        if color:
            return color
    parent = getattr(element, 'parent', None)
    if parent and hasattr(parent, 'get'):
        p_styles = parse_inline_styles(parent.get('style', ''))
        bg_str = p_styles.get('background-color')
        if bg_str:
            color = parse_color(bg_str)
            if color:
                return color
    return (255, 255, 255)


def get_font_size_px(styles):
    fs = styles.get('font-size', '')
    if not fs:
        return 16.0
    m = re.match(r'([\d.]+)\s*(px|pt|em|rem|%)', fs)
    if m:
        val = float(m.group(1))
        unit = m.group(2)
        if unit == 'px':
            return val
        if unit == 'pt':
            return val * 4.0 / 3.0
        if unit in ('em', 'rem'):
            return val * 16.0
        if unit == '%':
            return val / 100.0 * 16.0
    return 16.0


def is_bold(styles):
    fw = styles.get('font-weight', '').strip()
    if fw in ('bold', 'bolder'):
        return True
    try:
        return int(fw) >= 700
    except (ValueError, TypeError):
        return False


def is_large_text(font_size_px, bold):
    """Check if text qualifies as large text per WCAG.
    Large text is at least 18 point or 14 point bold."""
    if font_size_px >= 24.0:
        return True
    return False


# ── Element Identification ──

def element_id(el):
    tag = el.name
    if el.get('id'):
        return f"{tag}#{el['id']}"
    for attr in ('src', 'href', 'name'):
        if el.get(attr):
            return f'{tag}[{attr}="{el[attr]}"]'
    if el.get('type'):
        return f'{tag}[type="{el["type"]}"]'
    return tag


# ── Accessible Name Computation ──

def accessible_name_from_labelledby(el, soup):
    """Resolve aria-labelledby reference."""
    ref = el.get('aria-labelledby', '').strip()
    if not ref:
        return ''
    rid = ref.split()[0]
    target = soup.find(id=rid)
    if target:
        return target.get_text(strip=True)
    return ''


def accessible_name_for_link(a_tag, soup):
    name = accessible_name_from_labelledby(a_tag, soup)
    if name:
        return name
    al = a_tag.get('aria-label', '').strip()
    if al:
        return al
    text_parts = []
    for child in a_tag.descendants:
        if isinstance(child, NavigableString):
            text_parts.append(str(child))
        elif hasattr(child, 'name') and child.name == 'img':
            alt = child.get('alt', '')
            if alt:
                text_parts.append(alt)
    combined = ''.join(text_parts).strip()
    if combined:
        return combined
    t = a_tag.get('title', '').strip()
    if t:
        return t
    return ''


def accessible_name_for_form(el, soup):
    name = accessible_name_from_labelledby(el, soup)
    if name:
        return name
    al = el.get('aria-label', '').strip()
    if al:
        return al
    el_id = el.get('id', '')
    if el_id:
        label = soup.find('label', attrs={'for': el_id})
        if label:
            lt = label.get_text(strip=True)
            if lt:
                return lt
    if el.name == 'button':
        txt = el.get_text(strip=True)
        if txt:
            return txt
    t = el.get('title', '').strip()
    if t:
        return t
    if el.name == 'input' and el.get('type', '') in ('submit', 'reset', 'button'):
        v = el.get('value', '').strip()
        if v:
            return v
    p = el.get('placeholder', '').strip()
    if p:
        return p
    return ''


# ── Baseline Tests ──

def test_13a_language(soup):
    findings = []
    html_tag = soup.find('html')
    if not html_tag:
        findings.append({'test_id': '13.A-LanguageOfPage', 'result': 'FAIL',
            'wcag_sc': '3.1.1', 'element': 'html', 'message': 'No html element found'})
        return findings
    lang = (html_tag.get('lang') or '').strip()
    if lang:
        findings.append({'test_id': '13.A-LanguageOfPage', 'result': 'PASS',
            'wcag_sc': '3.1.1', 'element': 'html',
            'message': f'Page language set to "{lang}"'})
    else:
        findings.append({'test_id': '13.A-LanguageOfPage', 'result': 'FAIL',
            'wcag_sc': '3.1.1', 'element': 'html',
            'message': 'html element is missing lang attribute'})
    return findings


def test_11a_page_title(soup):
    findings = []
    title_tag = soup.find('title')
    if title_tag and title_tag.get_text(strip=True):
        findings.append({'test_id': '11.A-PageTitle', 'result': 'PASS',
            'wcag_sc': '2.4.2', 'element': 'title',
            'message': f'Page title: "{title_tag.get_text(strip=True)}"'})
    else:
        findings.append({'test_id': '11.A-PageTitle', 'result': 'FAIL',
            'wcag_sc': '2.4.2', 'element': 'head',
            'message': 'Page is missing a title element or title is empty'})
    return findings


def test_6_images(soup):
    findings = []
    for img in soup.find_all('img'):
        eid = element_id(img)
        alt = img.get('alt')
        role = (img.get('role') or '').strip().lower()
        if alt is None:
            findings.append({'test_id': '6.A-MeaningfulImage', 'result': 'FAIL',
                'wcag_sc': '1.1.1', 'element': eid,
                'message': 'Image is missing alt attribute entirely'})
        elif alt.strip() == '':
            if role in ('presentation', 'none'):
                findings.append({'test_id': '6.B-DecorativeImage', 'result': 'PASS',
                    'wcag_sc': '1.1.1', 'element': eid,
                    'message': 'Decorative image correctly hidden with empty alt and role'})
            elif img.get('aria-hidden', '').lower() == 'true':
                findings.append({'test_id': '6.B-DecorativeImage', 'result': 'PASS',
                    'wcag_sc': '1.1.1', 'element': eid,
                    'message': 'Decorative image hidden with aria-hidden="true"'})
            else:
                findings.append({'test_id': '6.B-DecorativeImage', 'result': 'PASS',
                    'wcag_sc': '1.1.1', 'element': eid,
                    'message': 'Image marked as decorative with empty alt'})
        else:
            if role in ('presentation', 'none'):
                findings.append({'test_id': '6.A-MeaningfulImage', 'result': 'FAIL',
                    'wcag_sc': '1.1.1', 'element': eid,
                    'message': f'Conflict: image has role="{role}" but non-empty alt text'})
            else:
                findings.append({'test_id': '6.A-MeaningfulImage', 'result': 'PASS',
                    'wcag_sc': '1.1.1', 'element': eid,
                    'message': 'Image has descriptive text alternative'})
    return findings


TEXT_TAGS = {'p', 'span', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
             'li', 'td', 'th', 'dt', 'dd', 'label', 'strong', 'em',
             'b', 'i', 'blockquote', 'figcaption', 'cite', 'abbr'}


def test_8a_contrast(soup):
    """Baseline 8.A - Contrast Minimum."""
    findings = []
    for elem in soup.find_all(TEXT_TAGS):
        text = elem.get_text(strip=True)
        if not text:
            continue
        styles = parse_inline_styles(elem.get('style', ''))
        fg_str = styles.get('color')
        if not fg_str:
            continue
        fg = parse_color(fg_str)
        if not fg:
            continue
        bg = get_effective_bg_color(elem)
        fg_lum = relative_luminance(*fg)
        bg_lum = relative_luminance(*bg)
        ratio = contrast_ratio(fg_lum, bg_lum)
        fsz = get_font_size_px(styles)
        bld = is_bold(styles)
        large = is_large_text(fsz, bld)
        req = 3.0 if large else 4.5
        eid = element_id(elem)
        if ratio >= req:
            findings.append({'test_id': '8.A-ContrastMinimum', 'result': 'PASS',
                'wcag_sc': '1.4.3', 'element': eid,
                'message': f'Contrast {ratio:.2f}:1 meets {"3:1 (large text)" if large else "4.5:1"} requirement'})
        else:
            findings.append({'test_id': '8.A-ContrastMinimum', 'result': 'FAIL',
                'wcag_sc': '1.4.3', 'element': eid,
                'message': f'Contrast {ratio:.2f}:1 below {"3:1 (large text)" if large else "4.5:1"} requirement'})
    return findings


def test_10a_form_names(soup):
    findings = []
    for elem in soup.find_all(['input', 'select', 'textarea', 'button']):
        if elem.name == 'input' and (elem.get('type') or '').lower() == 'hidden':
            continue
        eid = element_id(elem)
        name = accessible_name_for_form(elem, soup)
        if name:
            findings.append({'test_id': '10.A-FormName', 'result': 'PASS',
                'wcag_sc': '4.1.2', 'element': eid,
                'message': f'Form component has accessible name: "{name}"'})
        else:
            findings.append({'test_id': '10.A-FormName', 'result': 'FAIL',
                'wcag_sc': '4.1.2', 'element': eid,
                'message': 'Form component has no accessible name'})
    return findings


def test_14a_links(soup):
    findings = []
    for a in soup.find_all('a', href=True):
        eid = element_id(a)
        name = accessible_name_for_link(a, soup)
        if name:
            findings.append({'test_id': '14.A-LinkPurpose', 'result': 'PASS',
                'wcag_sc': '2.4.4', 'element': eid,
                'message': f'Link has accessible name: "{name}"'})
        else:
            findings.append({'test_id': '14.A-LinkPurpose', 'result': 'FAIL',
                'wcag_sc': '2.4.4', 'element': eid,
                'message': 'Link has no accessible name'})
    return findings


def test_15a_iframes(soup):
    findings = []
    for iframe in soup.find_all('iframe'):
        eid = element_id(iframe)
        title = (iframe.get('title') or '').strip()
        if title:
            findings.append({'test_id': '15.A-IframeName', 'result': 'PASS',
                'wcag_sc': '4.1.2', 'element': eid,
                'message': f'Iframe has title: "{title}"'})
        else:
            findings.append({'test_id': '15.A-IframeName', 'result': 'FAIL',
                'wcag_sc': '4.1.2', 'element': eid,
                'message': 'Iframe is missing title attribute'})
    return findings


# ── Main ──

def audit_page(filepath):
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        html = f.read()
    soup = BeautifulSoup(html, 'html.parser')
    findings = []
    findings.extend(test_13a_language(soup))
    findings.extend(test_11a_page_title(soup))
    findings.extend(test_6_images(soup))
    findings.extend(test_8a_contrast(soup))
    findings.extend(test_10a_form_names(soup))
    findings.extend(test_14a_links(soup))
    findings.extend(test_15a_iframes(soup))
    return findings


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 audit.py <pages_directory> <output_json>")
        print("Scans HTML files and generates a Section 508 conformance report.")
        sys.exit(1 if len(sys.argv) > 1 and sys.argv[1] != '--help' else 0)
    pages_dir = sys.argv[1]
    output_path = sys.argv[2]
    if not os.path.isdir(pages_dir):
        print(f"Error: {pages_dir} is not a directory")
        sys.exit(1)
    report = {"pages": {}}
    for filename in sorted(os.listdir(pages_dir)):
        if filename.lower().endswith('.html'):
            filepath = os.path.join(pages_dir, filename)
            findings = audit_page(filepath)
            report["pages"][filename] = {"findings": findings}
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)
    total = sum(len(p['findings']) for p in report['pages'].values())
    fails = sum(1 for p in report['pages'].values()
                for f in p['findings'] if f['result'] == 'FAIL')
    print(f"Report written to {output_path}")
    print(f"Audited {len(report['pages'])} page(s): {total} findings, {fails} failure(s)")


if __name__ == '__main__':
    main()
