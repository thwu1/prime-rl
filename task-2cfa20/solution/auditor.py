#!/usr/bin/env python3
"""
WCAG 2.0 / Section 508 Conformance Audit Tool
Based on DHS Trusted Tester v5.1.3 Test Conditions
"""

import json
import os
import re
from bs4 import BeautifulSoup

# ISO 639-1 primary language subtags
VALID_LANG_SUBTAGS = {
    'aa', 'ab', 'ae', 'af', 'ak', 'am', 'an', 'ar', 'as', 'av', 'ay', 'az',
    'ba', 'be', 'bg', 'bh', 'bi', 'bm', 'bn', 'bo', 'br', 'bs',
    'ca', 'ce', 'ch', 'co', 'cr', 'cs', 'cu', 'cv', 'cy',
    'da', 'de', 'dv', 'dz',
    'ee', 'el', 'en', 'eo', 'es', 'et', 'eu',
    'fa', 'ff', 'fi', 'fj', 'fo', 'fr', 'fy',
    'ga', 'gd', 'gl', 'gn', 'gu', 'gv',
    'ha', 'he', 'hi', 'ho', 'hr', 'ht', 'hu', 'hy', 'hz',
    'ia', 'id', 'ie', 'ig', 'ii', 'ik', 'in', 'io', 'is', 'it', 'iu',
    'ja', 'jv', 'jw',
    'ka', 'kg', 'ki', 'kj', 'kk', 'kl', 'km', 'kn', 'ko', 'kr', 'ks',
    'ku', 'kv', 'kw', 'ky',
    'la', 'lb', 'lg', 'li', 'ln', 'lo', 'lt', 'lu', 'lv',
    'mg', 'mh', 'mi', 'mk', 'ml', 'mn', 'mo', 'mr', 'ms', 'mt', 'my',
    'na', 'nb', 'nd', 'ne', 'ng', 'nl', 'nn', 'no', 'nr', 'nv', 'ny',
    'oc', 'oj', 'om', 'or', 'os',
    'pa', 'pi', 'pl', 'ps', 'pt',
    'qu',
    'rm', 'rn', 'ro', 'ru', 'rw',
    'sa', 'sc', 'sd', 'se', 'sg', 'sh', 'si', 'sk', 'sl', 'sm', 'sn',
    'so', 'sq', 'sr', 'ss', 'st', 'su', 'sv', 'sw',
    'ta', 'te', 'tg', 'th', 'ti', 'tk', 'tl', 'tn', 'to', 'tr', 'ts',
    'tt', 'tw', 'ty',
    'ug', 'uk', 'ur', 'uz',
    've', 'vi', 'vo',
    'wa', 'wo',
    'xh',
    'yi', 'yo',
    'za', 'zh', 'zu',
}

NON_DESCRIPTIVE_LINK_TEXT = {
    'click here', 'here', 'more', 'read more', 'learn more',
    'link', 'this', 'go', 'details', 'info',
}

SENSORY_PATTERNS = [
    r'\bround\b',
    r'\bsquare\b',
    r'\bcircular\b',
    r'\btriangular\b',
    r'\b(?:top|bottom|left|right)\s+(?:of|side|corner)\b',
    r'\b(?:above|below)\b.*\b(?:button|link|field|section)\b',
    r'\bshaped?\b',
]

MEANINGFUL_IMG_KEYWORDS = [
    'logo', 'chart', 'graph', 'icon', 'banner', 'hero',
    'photo', 'portrait', 'diagram', 'map', 'screenshot',
]

DECORATIVE_IMG_KEYWORDS = [
    'decorative', 'border', 'spacer', 'divider', 'separator',
    'ornament', 'background', 'flourish',
]


# ---- Color / Contrast Utilities ----

def srgb_to_linear(c):
    """Convert sRGB channel (0-255) to linear value."""
    c = c / 255.0
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(r, g, b):
    """Compute relative luminance per WCAG 2.0."""
    return 0.2126 * srgb_to_linear(r) + 0.7152 * srgb_to_linear(g) + 0.0722 * srgb_to_linear(b)


def contrast_ratio(l1, l2):
    """Compute contrast ratio between two luminance values."""
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def hex_to_rgb(hex_color):
    """Convert hex color string to RGB tuple."""
    h = hex_color.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# ---- DOM Utilities ----

def describe_element(el):
    """Create a CSS-selector-like description of an element."""
    tag = el.name
    if el.get('id'):
        return f"{tag}#{el['id']}"
    classes = el.get('class', [])
    if classes:
        return f"{tag}.{'.'.join(classes)}"
    return tag


def get_inline_color(el, prop):
    """Extract color from inline style attribute."""
    style = el.get('style', '')
    if not style:
        return None
    if prop == 'background-color':
        m = re.search(r'background-color\s*:\s*(#[0-9a-fA-F]{3,8})', style, re.I)
    else:
        m = re.search(r'(?<!-)color\s*:\s*(#[0-9a-fA-F]{3,8})', style, re.I)
    return m.group(1) if m else None


def get_body_bg_from_style(html_str):
    """Extract body background-color from <style> blocks."""
    m = re.search(
        r'body\s*\{[^}]*background-color\s*:\s*(#[0-9a-fA-F]{3,8})',
        html_str, re.I
    )
    return m.group(1) if m else '#ffffff'


def find_effective_bg(el, html_str):
    """Walk up ancestors to find effective background color."""
    bg = get_inline_color(el, 'background-color')
    if bg:
        return bg
    parent = el.parent
    while parent and parent.name:
        bg = get_inline_color(parent, 'background-color')
        if bg:
            return bg
        parent = parent.parent
    return get_body_bg_from_style(html_str)


def is_data_table(table):
    """Heuristic: is this table a data table (not layout)?"""
    if table.get('role') in ('presentation', 'none'):
        return False
    classes = ' '.join(table.get('class', [])).lower()
    if 'layout' in classes:
        return False
    first_row = table.find('tr')
    if first_row:
        cells = first_row.find_all(['td', 'th'])
        if cells and all(len(c.get_text(strip=True)) < 60 for c in cells):
            rows = table.find_all('tr')
            if len(rows) > 1:
                return True
    return False


# ---- Test Condition Checks ----

def check_11a(filename, soup):
    """Test 11.A (WCAG 3.1.1): Page language programmatically determined."""
    html_el = soup.find('html')
    if not html_el:
        return [{"file": filename, "test_id": "11.A", "wcag_sc": "3.1.1",
                 "element": "html",
                 "description": "No <html> element found"}]

    lang = html_el.get('lang', '').strip()
    if not lang:
        return [{"file": filename, "test_id": "11.A", "wcag_sc": "3.1.1",
                 "element": "html",
                 "description": "Page language not programmatically determined "
                                "- lang attribute missing or empty"}]

    primary = lang.split('-')[0].lower()
    if primary not in VALID_LANG_SUBTAGS:
        return [{"file": filename, "test_id": "11.A", "wcag_sc": "3.1.1",
                 "element": "html",
                 "description": f"Invalid primary language subtag: '{primary}'"}]
    return []


def check_12a(filename, soup):
    """Test 12.A (WCAG 2.4.2): <title> defined for page."""
    title_el = soup.find('title')
    if not title_el or not title_el.get_text(strip=True):
        return [{"file": filename, "test_id": "12.A", "wcag_sc": "2.4.2",
                 "element": "title",
                 "description": "Page title element missing or empty"}]
    return []


def check_7a(filename, soup):
    """Test 7.A (WCAG 1.1.1): Meaningful images have accessible name."""
    violations = []
    for img in soup.find_all('img'):
        alt = img.get('alt')
        src = img.get('src', '')
        src_lower = src.lower()
        is_meaningful = any(kw in src_lower for kw in MEANINGFUL_IMG_KEYWORDS)

        if is_meaningful and (alt is None or alt.strip() == ''):
            violations.append({
                "file": filename, "test_id": "7.A", "wcag_sc": "1.1.1",
                "element": f"img[src='{src}']",
                "description": f"Meaningful image '{src}' lacks accessible name "
                               f"(alt is {'missing' if alt is None else 'empty'})"
            })
    return violations


def check_7b(filename, soup):
    """Test 7.B (WCAG 1.1.1): Decorative images have no accessible name."""
    violations = []
    for img in soup.find_all('img'):
        alt = img.get('alt', '')
        src = img.get('src', '')
        src_lower = src.lower()
        is_decorative = any(kw in src_lower for kw in DECORATIVE_IMG_KEYWORDS)

        if is_decorative and alt.strip():
            violations.append({
                "file": filename, "test_id": "7.B", "wcag_sc": "1.1.1",
                "element": f"img[src='{src}']",
                "description": f"Decorative image '{src}' should have empty alt "
                               f"but has: '{alt[:60]}'"
            })
    return violations


def check_14b(filename, soup):
    """Test 14.B (WCAG 1.3.1): Data cells associated with headers."""
    violations = []
    for table in soup.find_all('table'):
        if not is_data_table(table):
            continue
        th_elements = table.find_all('th')
        has_headers_attr = any(td.get('headers') for td in table.find_all('td'))

        if not th_elements and not has_headers_attr:
            violations.append({
                "file": filename, "test_id": "14.B", "wcag_sc": "1.3.1",
                "element": describe_element(table),
                "description": "Data table lacks header cells (<th>) - data cells "
                               "not programmatically associated with headers"
            })
    return violations


def check_14c(filename, soup):
    """Test 14.C (WCAG 1.3.1): Layout table does not use data table markup."""
    violations = []
    for table in soup.find_all('table'):
        classes = ' '.join(table.get('class', [])).lower()
        if 'layout' not in classes:
            continue

        has_role_table = table.get('role') == 'table'
        has_th = bool(table.find_all('th'))
        has_scope = any(
            el.get('scope') for el in table.find_all(['td', 'th'])
        )

        if has_role_table or has_th or has_scope:
            reasons = []
            if has_role_table:
                reasons.append('role="table"')
            if has_th:
                reasons.append('<th> elements')
            if has_scope:
                reasons.append('scope attributes')
            violations.append({
                "file": filename, "test_id": "14.C", "wcag_sc": "1.3.1",
                "element": describe_element(table),
                "description": f"Layout table uses data table markup: "
                               f"{', '.join(reasons)}"
            })
    return violations


def check_13a(filename, soup):
    """Test 13.A (WCAG 1.4.1): Color not only means of conveying info."""
    violations = []
    color_groups = {}

    for el in soup.find_all(style=True):
        text = el.get_text(strip=True)
        color = get_inline_color(el, 'color')
        if text and color:
            if text not in color_groups:
                color_groups[text] = set()
            color_groups[text].add(color.lower())

    for text, colors in color_groups.items():
        if len(colors) > 1:
            violations.append({
                "file": filename, "test_id": "13.A", "wcag_sc": "1.4.1",
                "element": f"elements with text '{text[:30]}'",
                "description": f"Color is the only visual means distinguishing "
                               f"elements with identical text '{text[:30]}' "
                               f"- colors: {', '.join(sorted(colors))}"
            })

    return violations


def check_13b(filename, soup):
    """Test 13.B (WCAG 1.3.3): Instructions don't rely on sensory characteristics."""
    violations = []

    for el in soup.find_all(['p', 'li', 'span', 'div', 'label']):
        text = el.get_text()
        if not text or len(text.strip()) < 10:
            continue

        for pattern in SENSORY_PATTERNS:
            if re.search(pattern, text, re.I):
                if re.search(
                    r'\b(press|click|select|find|look|use|tap|push|hit|submit)\b',
                    text, re.I
                ):
                    violations.append({
                        "file": filename, "test_id": "13.B", "wcag_sc": "1.3.3",
                        "element": describe_element(el),
                        "description": f"Instruction relies on sensory "
                                       f"characteristics: "
                                       f"'{text.strip()[:100]}'"
                    })
                    break

    return violations


def check_13c(filename, soup, html_str):
    """Test 13.C (WCAG 1.4.3): Text has sufficient contrast ratio."""
    violations = []

    for el in soup.find_all(style=True):
        fg_hex = get_inline_color(el, 'color')
        if not fg_hex:
            continue

        text = el.get_text(strip=True)
        if not text:
            continue

        bg_hex = find_effective_bg(el, html_str)

        try:
            fg_rgb = hex_to_rgb(fg_hex)
            bg_rgb = hex_to_rgb(bg_hex)
        except (ValueError, TypeError):
            continue

        fg_lum = relative_luminance(*fg_rgb)
        bg_lum = relative_luminance(*bg_rgb)
        ratio = contrast_ratio(fg_lum, bg_lum)

        style = el.get('style', '')
        is_large = False
        size_match = re.search(
            r'font-size\s*:\s*(\d+(?:\.\d+)?)\s*(px|pt|em|rem)?', style
        )
        if size_match:
            size = float(size_match.group(1))
            unit = size_match.group(2) or 'px'
            is_bold = bool(
                re.search(r'font-weight\s*:\s*(bold|[6-9]00)', style)
            )
            if unit == 'pt':
                is_large = size >= 18 or (size >= 14 and is_bold)
            elif unit == 'px':
                is_large = size >= 24 or (size >= 18.66 and is_bold)

        threshold = 3.0 if is_large else 4.5

        if ratio < threshold:
            violations.append({
                "file": filename, "test_id": "13.C", "wcag_sc": "1.4.3",
                "element": describe_element(el),
                "description": f"Contrast ratio {ratio:.2f}:1 below "
                               f"{threshold}:1 threshold "
                               f"(fg: {fg_hex}, bg: {bg_hex})"
            })

    return violations


def check_5c(filename, soup):
    """Test 5.C (WCAG 1.3.1): Form inputs have programmatic label."""
    violations = []
    form_inputs = soup.find_all(['input', 'select', 'textarea'])

    for inp in form_inputs:
        input_type = inp.get('type', 'text').lower()
        if input_type in ('hidden', 'submit', 'button', 'reset', 'image'):
            continue

        input_id = inp.get('id', '')
        has_association = False

        # label[for] matching id
        if input_id:
            label = soup.find('label', attrs={'for': input_id})
            if label:
                has_association = True

        # aria-label
        if inp.get('aria-label', '').strip():
            has_association = True

        # aria-labelledby
        if inp.get('aria-labelledby', '').strip():
            has_association = True

        # title attribute
        if inp.get('title', '').strip():
            has_association = True

        # wrapped in <label>
        parent = inp.parent
        while parent:
            if parent.name == 'label':
                has_association = True
                break
            parent = parent.parent

        if not has_association:
            name_hint = inp.get('name', inp.get('id', 'unknown'))
            violations.append({
                "file": filename, "test_id": "5.C", "wcag_sc": "1.3.1",
                "element": describe_element(inp),
                "description": f"Form input '{name_hint}' has no programmatic "
                               f"label association (no matching label[for], "
                               f"aria-label, aria-labelledby, title, or "
                               f"wrapping <label>)"
            })

    return violations


def check_11b(filename, soup):
    """Test 11.B (WCAG 3.1.2): Language of parts programmatically determined."""
    violations = []
    html_el = soup.find('html')
    if not html_el:
        return []

    page_lang = html_el.get('lang', '').split('-')[0].lower()
    if not page_lang:
        return []

    try:
        from langdetect import detect
    except ImportError:
        return []

    for el in soup.find_all(['p', 'div', 'span', 'blockquote', 'li']):
        text = el.get_text(strip=True)
        if len(text) < 30:
            continue

        # Check if element or non-html ancestor has lang attribute
        has_lang = False
        check_el = el
        while check_el and check_el.name and check_el.name != 'html':
            if check_el.get('lang'):
                has_lang = True
                break
            check_el = check_el.parent

        if has_lang:
            continue

        try:
            detected = detect(text)
            if detected != page_lang:
                violations.append({
                    "file": filename, "test_id": "11.B", "wcag_sc": "3.1.2",
                    "element": describe_element(el),
                    "description": f"Content detected as '{detected}' differs "
                                   f"from page language '{page_lang}' but no "
                                   f"lang attribute is set on the element"
                })
        except Exception:
            continue

    return violations


def check_6a(filename, soup):
    """Test 6.A (WCAG 2.4.4): Link purpose determinable."""
    violations = []

    for a in soup.find_all('a', href=True):
        link_text = a.get_text(strip=True).lower()

        if link_text in NON_DESCRIPTIVE_LINK_TEXT:
            # Check programmatic context
            parent = a.parent
            context_text = ''
            if parent and parent.name in ('p', 'li', 'td', 'th'):
                context_text = parent.get_text(strip=True)

            # If context equals link text, there's no additional context
            if not context_text or context_text.strip().lower() == link_text:
                violations.append({
                    "file": filename, "test_id": "6.A", "wcag_sc": "2.4.4",
                    "element": f"a[href='{a['href']}']",
                    "description": f"Link text '{a.get_text(strip=True)}' is "
                                   f"non-descriptive and surrounding context "
                                   f"provides no additional purpose"
                })

    return violations


def check_10b(filename, soup):
    """Test 10.B (WCAG 1.3.1): Visual headings programmatically marked."""
    violations = []
    heading_tags = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}

    for el in soup.find_all(style=True):
        if el.name in heading_tags:
            continue
        if el.get('role') == 'heading':
            continue

        style = el.get('style', '')
        text = el.get_text(strip=True)

        if not text or len(text) > 200:
            continue

        has_large_font = False
        has_bold = bool(re.search(r'font-weight\s*:\s*(bold|[6-9]00)', style))

        size_match = re.search(
            r'font-size\s*:\s*(\d+(?:\.\d+)?)\s*(px|pt|em|rem)?', style
        )
        if size_match:
            size = float(size_match.group(1))
            unit = size_match.group(2) or 'px'
            if (unit == 'px' and size >= 18) or (unit == 'pt' and size >= 14):
                has_large_font = True

        if has_large_font and has_bold:
            violations.append({
                "file": filename, "test_id": "10.B", "wcag_sc": "1.3.1",
                "element": describe_element(el),
                "description": f"Visual heading '{text[:60]}' not "
                               f"programmatically marked as heading element"
            })

    return violations


def check_12d(filename, soup):
    """Test 12.D (WCAG 4.1.2): iframes have accessible name."""
    violations = []

    for iframe in soup.find_all('iframe'):
        tabindex = iframe.get('tabindex', '0')
        try:
            if int(tabindex) < 0:
                continue
        except (ValueError, TypeError):
            pass

        title = iframe.get('title', '').strip()
        aria_label = iframe.get('aria-label', '').strip()
        aria_labelledby = iframe.get('aria-labelledby', '').strip()

        if not title and not aria_label and not aria_labelledby:
            violations.append({
                "file": filename, "test_id": "12.D", "wcag_sc": "4.1.2",
                "element": f"iframe[src='{iframe.get('src', '')}']",
                "description": "iframe has no accessible name (missing title, "
                               "aria-label, or aria-labelledby)"
            })

    return violations


def check_15a(filename, soup, html_str):
    """Test 15.A (WCAG 1.3.1): CSS ::before/::after meaningful content."""
    violations = []

    for style_block in soup.find_all('style'):
        css_text = style_block.get_text()

        pattern = r'([^{}\s][^{}]*?)::(?:before|after)\s*\{([^}]*)\}'
        for m in re.finditer(pattern, css_text):
            selector_raw = m.group(1).strip()
            props = m.group(2)

            content_match = re.search(
                r'content\s*:\s*["\']([^"\']+)["\']', props
            )
            if not content_match:
                continue

            content = content_match.group(1).strip()
            if not content:
                continue

            # Skip purely decorative characters
            decorative_chars = set('•·–—―‒|/\\→←↑↓★☆○●◆▪▫ ')
            if all(c in decorative_chars for c in content):
                continue

            # Find matching elements by class
            class_match = re.search(r'\.([a-zA-Z0-9_-]+)', selector_raw)
            if not class_match:
                continue

            class_name = class_match.group(1)
            elements = soup.find_all(class_=class_name)

            for el in elements:
                el_text = el.get_text(strip=True)
                # Strip common wrapping from content for comparison
                content_clean = re.sub(r'[\[\](){}<>]', '', content).strip()
                if content_clean.lower() not in el_text.lower():
                    violations.append({
                        "file": filename, "test_id": "15.A",
                        "wcag_sc": "1.3.1",
                        "element": f".{class_name}::before/after",
                        "description": f"CSS pseudo-element content "
                                       f"'{content}' has no text equivalent "
                                       f"in the element"
                    })
                    break

    return violations


# ---- Main ----

def main():
    site_dir = "/app/site"
    all_violations = []

    for filename in sorted(os.listdir(site_dir)):
        if not filename.endswith(".html"):
            continue

        filepath = os.path.join(site_dir, filename)
        with open(filepath, encoding='utf-8') as f:
            html_str = f.read()

        soup = BeautifulSoup(html_str, "html.parser")

        all_violations.extend(check_11a(filename, soup))
        all_violations.extend(check_12a(filename, soup))
        all_violations.extend(check_7a(filename, soup))
        all_violations.extend(check_7b(filename, soup))
        all_violations.extend(check_14b(filename, soup))
        all_violations.extend(check_14c(filename, soup))
        all_violations.extend(check_13a(filename, soup))
        all_violations.extend(check_13b(filename, soup))
        all_violations.extend(check_13c(filename, soup, html_str))
        all_violations.extend(check_5c(filename, soup))
        all_violations.extend(check_11b(filename, soup))
        all_violations.extend(check_6a(filename, soup))
        all_violations.extend(check_10b(filename, soup))
        all_violations.extend(check_12d(filename, soup))
        all_violations.extend(check_15a(filename, soup, html_str))

    report = {"violations": all_violations}
    with open("/app/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Audit complete. Found {len(all_violations)} violations.")
    for v in all_violations:
        print(f"  [{v['file']}] {v['test_id']} ({v['wcag_sc']}): "
              f"{v['description'][:80]}")


if __name__ == "__main__":
    main()
