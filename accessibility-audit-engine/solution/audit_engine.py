#!/usr/bin/env python3

"""
Section 508 Conformance Audit Engine — Reference Solution
Implements ICT Testing Baseline tests 6, 8, 10, 11, 13, 14, 15 for web HTML pages.
Handles both inline styles and <style> block CSS.
"""

import json
import os
import re
import sys

from bs4 import BeautifulSoup, NavigableString

try:
    import tinycss2
    HAS_TINYCSS2 = True
except ImportError:
    HAS_TINYCSS2 = False


# ──────────────────────────────────────────────
# CSS <style> Block Parsing
# ──────────────────────────────────────────────

def parse_css_rules(soup):
    """Parse CSS rules from <style> elements in the document."""
    rules = []
    for style_tag in soup.find_all('style'):
        css_text = style_tag.string or ''
        if HAS_TINYCSS2:
            parsed = tinycss2.parse_stylesheet(css_text, skip_comments=True)
            for rule in parsed:
                if rule.type == 'qualified-rule':
                    selector_str = tinycss2.serialize(rule.prelude).strip()
                    declarations = tinycss2.parse_declaration_list(rule.content)
                    props = {}
                    for decl in declarations:
                        if decl.type == 'declaration':
                            props[decl.lower_name] = tinycss2.serialize(decl.value).strip()
                    if props:
                        rules.append((selector_str, props))
        else:
            for match in re.finditer(r'([^{}]+)\{([^}]+)\}', css_text):
                sel = match.group(1).strip()
                props_str = match.group(2).strip()
                props = {}
                for decl in props_str.split(';'):
                    if ':' in decl:
                        k, _, v = decl.partition(':')
                        props[k.strip().lower()] = v.strip()
                if props:
                    rules.append((sel, props))
    return rules


def selector_matches(element, selector):
    """Check if a simple CSS selector matches a BeautifulSoup element."""
    selector = selector.strip()
    if not hasattr(element, 'name') or not element.name:
        return False

    if ',' in selector:
        return any(selector_matches(element, s.strip()) for s in selector.split(','))

    if selector.startswith('#') and '.' not in selector and ' ' not in selector:
        return element.get('id') == selector[1:]

    if '.' in selector and ' ' not in selector:
        parts = selector.split('.')
        tag_part = parts[0].strip()
        class_parts = [p.strip() for p in parts[1:] if p.strip()]
        if tag_part and element.name != tag_part:
            return False
        elem_classes = element.get('class', [])
        if isinstance(elem_classes, str):
            elem_classes = elem_classes.split()
        return all(c in elem_classes for c in class_parts)

    if re.match(r'^[a-zA-Z][a-zA-Z0-9]*$', selector):
        return element.name == selector.lower()

    return False


def get_css_styles(element, css_rules):
    """Get CSS styles from <style> rules matching an element."""
    merged = {}
    for sel, props in css_rules:
        if selector_matches(element, sel):
            merged.update(props)
    return merged


def get_effective_styles(element, css_rules):
    """Merge CSS and inline styles. Inline takes precedence."""
    styles = get_css_styles(element, css_rules)
    inline = parse_inline_styles(element.get('style', ''))
    styles.update(inline)
    return styles


# ──────────────────────────────────────────────
# Color and Contrast Utilities (WCAG 2.x)
# ──────────────────────────────────────────────

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

    m = re.match(r'rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', color_str)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))

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
    return ((v + 0.055) / 1.055) ** 2.4


def relative_luminance(r, g, b):
    """Compute relative luminance per WCAG 2.x definition."""
    return (0.2126 * srgb_to_linear(r)
          + 0.7152 * srgb_to_linear(g)
          + 0.0722 * srgb_to_linear(b))


def contrast_ratio(lum1, lum2):
    """Compute contrast ratio between two luminance values."""
    lighter = max(lum1, lum2)
    darker = min(lum1, lum2)
    return (lighter + 0.05) / (darker + 0.05)


# ──────────────────────────────────────────────
# CSS / Style Utilities
# ──────────────────────────────────────────────

def parse_inline_styles(style_attr):
    """Parse an inline style attribute string into a property dict."""
    if not style_attr:
        return {}
    result = {}
    for decl in style_attr.split(';'):
        if ':' in decl:
            prop, _, val = decl.partition(':')
            result[prop.strip().lower()] = val.strip()
    return result


def get_effective_bg_color(element, css_rules=None):
    """Walk up the DOM to find the nearest ancestor with background-color.
    Checks both inline styles and CSS rules."""
    if css_rules is None:
        css_rules = []
    current = element
    while current:
        if hasattr(current, 'get'):
            inline = parse_inline_styles(current.get('style', ''))
            bg_str = inline.get('background-color')
            if bg_str:
                color = parse_color(bg_str)
                if color:
                    return color
            if css_rules:
                css_props = get_css_styles(current, css_rules)
                bg_str = css_props.get('background-color')
                if bg_str:
                    color = parse_color(bg_str)
                    if color:
                        return color
        current = getattr(current, 'parent', None)
    return (255, 255, 255)


def get_font_size_px(styles):
    """Extract font-size in pixels from a style dict."""
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
    """Determine if font-weight qualifies as bold (>=700)."""
    fw = styles.get('font-weight', '').strip()
    if fw in ('bold', 'bolder'):
        return True
    try:
        return int(fw) >= 700
    except (ValueError, TypeError):
        return False


def is_large_text(font_size_px, bold):
    """Check whether text qualifies as 'large text' per WCAG.
    Large text: >= 18pt (24px) OR >= 14pt (~18.66px) and bold.
    """
    if font_size_px >= 24.0:
        return True
    if bold and font_size_px >= 18.66:
        return True
    return False


# ──────────────────────────────────────────────
# Element Identification
# ──────────────────────────────────────────────

def element_id(el):
    """Build a human-readable element identifier."""
    tag = el.name
    if el.get('id'):
        return f"{tag}#{el['id']}"
    for attr in ('src', 'href', 'name'):
        if el.get(attr):
            return f'{tag}[{attr}="{el[attr]}"]'
    if el.get('type'):
        return f'{tag}[type="{el["type"]}"]'
    return tag


# ──────────────────────────────────────────────
# Accessible Name Computation
# ──────────────────────────────────────────────

def accessible_name_from_labelledby(el, soup):
    """Resolve aria-labelledby references (supports multiple IDs)."""
    ref = el.get('aria-labelledby', '').strip()
    if not ref:
        return ''
    parts = []
    for rid in ref.split():
        target = soup.find(id=rid)
        if target:
            parts.append(target.get_text(strip=True))
    return ' '.join(parts).strip()


def accessible_name_for_link(a_tag, soup):
    """Compute the accessible name of an <a> element."""
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
    """Compute the accessible name for a form element."""
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
    ancestor = el.parent
    while ancestor:
        if hasattr(ancestor, 'name') and ancestor.name == 'label':
            lt = ancestor.get_text(strip=True)
            if lt:
                return lt
            break
        ancestor = getattr(ancestor, 'parent', None)
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


# ──────────────────────────────────────────────
# Baseline Tests
# ──────────────────────────────────────────────

def test_13a_language(soup):
    """Baseline 13.A - Language of Page."""
    findings = []
    html_tag = soup.find('html')
    if not html_tag:
        findings.append({
            'test_id': '13.A-LanguageOfPage', 'result': 'FAIL',
            'wcag_sc': '3.1.1', 'element': 'html',
            'message': 'No html element found'
        })
        return findings
    lang = (html_tag.get('lang') or '').strip()
    if lang:
        findings.append({
            'test_id': '13.A-LanguageOfPage', 'result': 'PASS',
            'wcag_sc': '3.1.1', 'element': 'html',
            'message': f'Page language set to "{lang}"'
        })
    else:
        findings.append({
            'test_id': '13.A-LanguageOfPage', 'result': 'FAIL',
            'wcag_sc': '3.1.1', 'element': 'html',
            'message': 'html element is missing lang attribute'
        })
    return findings


def test_11a_page_title(soup):
    """Baseline 11.A - Page Title."""
    findings = []
    title_tag = soup.find('title')
    if title_tag and title_tag.get_text(strip=True):
        findings.append({
            'test_id': '11.A-PageTitle', 'result': 'PASS',
            'wcag_sc': '2.4.2', 'element': 'title',
            'message': f'Page title: "{title_tag.get_text(strip=True)}"'
        })
    else:
        findings.append({
            'test_id': '11.A-PageTitle', 'result': 'FAIL',
            'wcag_sc': '2.4.2', 'element': 'head',
            'message': 'Page is missing a title element or title is empty'
        })
    return findings


def test_6_images(soup):
    """Baseline 6.A/6.B - Images."""
    findings = []
    for img in soup.find_all('img'):
        eid = element_id(img)
        alt = img.get('alt')
        role = (img.get('role') or '').strip().lower()
        if alt is None:
            findings.append({
                'test_id': '6.A-MeaningfulImage', 'result': 'FAIL',
                'wcag_sc': '1.1.1', 'element': eid,
                'message': 'Image is missing alt attribute entirely'
            })
        elif alt.strip() == '':
            if role in ('presentation', 'none'):
                findings.append({
                    'test_id': '6.B-DecorativeImage', 'result': 'PASS',
                    'wcag_sc': '1.1.1', 'element': eid,
                    'message': 'Decorative image correctly hidden with empty alt and role'
                })
            elif img.get('aria-hidden', '').lower() == 'true':
                findings.append({
                    'test_id': '6.B-DecorativeImage', 'result': 'PASS',
                    'wcag_sc': '1.1.1', 'element': eid,
                    'message': 'Decorative image hidden with aria-hidden="true"'
                })
            else:
                findings.append({
                    'test_id': '6.B-DecorativeImage', 'result': 'PASS',
                    'wcag_sc': '1.1.1', 'element': eid,
                    'message': 'Image marked as decorative with empty alt'
                })
        else:
            if role in ('presentation', 'none'):
                findings.append({
                    'test_id': '6.A-MeaningfulImage', 'result': 'FAIL',
                    'wcag_sc': '1.1.1', 'element': eid,
                    'message': f'Conflict: image has role="{role}" but non-empty alt text'
                })
            else:
                findings.append({
                    'test_id': '6.A-MeaningfulImage', 'result': 'PASS',
                    'wcag_sc': '1.1.1', 'element': eid,
                    'message': 'Image has descriptive text alternative'
                })
    return findings


TEXT_TAGS = {'p', 'span', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
             'li', 'td', 'th', 'dt', 'dd', 'label', 'strong', 'em',
             'b', 'i', 'blockquote', 'figcaption', 'cite', 'abbr'}


def test_8a_contrast(soup, css_rules=None):
    """Baseline 8.A - Contrast Minimum."""
    if css_rules is None:
        css_rules = []
    findings = []
    for elem in soup.find_all(TEXT_TAGS):
        text = elem.get_text(strip=True)
        if not text:
            continue
        styles = get_effective_styles(elem, css_rules)
        fg_str = styles.get('color')
        if not fg_str:
            continue
        fg = parse_color(fg_str)
        if not fg:
            continue
        bg = get_effective_bg_color(elem, css_rules)
        fg_lum = relative_luminance(*fg)
        bg_lum = relative_luminance(*bg)
        ratio = contrast_ratio(fg_lum, bg_lum)
        fsz = get_font_size_px(styles)
        bld = is_bold(styles)
        large = is_large_text(fsz, bld)
        req = 3.0 if large else 4.5
        eid = element_id(elem)
        if ratio >= req:
            findings.append({
                'test_id': '8.A-ContrastMinimum', 'result': 'PASS',
                'wcag_sc': '1.4.3', 'element': eid,
                'message': (f'Contrast {ratio:.2f}:1 meets '
                            f'{"3:1 (large text)" if large else "4.5:1"} requirement')
            })
        else:
            findings.append({
                'test_id': '8.A-ContrastMinimum', 'result': 'FAIL',
                'wcag_sc': '1.4.3', 'element': eid,
                'message': (f'Contrast {ratio:.2f}:1 below '
                            f'{"3:1 (large text)" if large else "4.5:1"} requirement')
            })
    return findings


def test_10a_form_names(soup):
    """Baseline 10.A - Form Names."""
    findings = []
    for elem in soup.find_all(['input', 'select', 'textarea', 'button']):
        if elem.name == 'input' and (elem.get('type') or '').lower() == 'hidden':
            continue
        eid = element_id(elem)
        name = accessible_name_for_form(elem, soup)
        if name:
            findings.append({
                'test_id': '10.A-FormName', 'result': 'PASS',
                'wcag_sc': '4.1.2', 'element': eid,
                'message': f'Form component has accessible name: "{name}"'
            })
        else:
            findings.append({
                'test_id': '10.A-FormName', 'result': 'FAIL',
                'wcag_sc': '4.1.2', 'element': eid,
                'message': 'Form component has no accessible name'
            })
    return findings


def test_14a_links(soup):
    """Baseline 14.A - Link Purpose."""
    findings = []
    for a in soup.find_all('a', href=True):
        eid = element_id(a)
        name = accessible_name_for_link(a, soup)
        if name:
            findings.append({
                'test_id': '14.A-LinkPurpose', 'result': 'PASS',
                'wcag_sc': '2.4.4', 'element': eid,
                'message': f'Link has accessible name: "{name}"'
            })
        else:
            findings.append({
                'test_id': '14.A-LinkPurpose', 'result': 'FAIL',
                'wcag_sc': '2.4.4', 'element': eid,
                'message': 'Link has no accessible name'
            })
    return findings


def test_15a_iframes(soup):
    """Baseline 15.A - iFrame Name."""
    findings = []
    for iframe in soup.find_all('iframe'):
        eid = element_id(iframe)
        title = (iframe.get('title') or '').strip()
        if title:
            findings.append({
                'test_id': '15.A-IframeName', 'result': 'PASS',
                'wcag_sc': '4.1.2', 'element': eid,
                'message': f'Iframe has title: "{title}"'
            })
        else:
            findings.append({
                'test_id': '15.A-IframeName', 'result': 'FAIL',
                'wcag_sc': '4.1.2', 'element': eid,
                'message': 'Iframe is missing title attribute'
            })
    return findings


# ──────────────────────────────────────────────
# Main Audit Engine
# ──────────────────────────────────────────────

def audit_page(filepath):
    """Run all baseline tests on a single HTML file."""
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        html = f.read()
    soup = BeautifulSoup(html, 'html.parser')
    css_rules = parse_css_rules(soup)
    findings = []
    findings.extend(test_13a_language(soup))
    findings.extend(test_11a_page_title(soup))
    findings.extend(test_6_images(soup))
    findings.extend(test_8a_contrast(soup, css_rules))
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
