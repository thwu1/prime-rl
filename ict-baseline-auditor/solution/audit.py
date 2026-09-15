#!/usr/bin/env python3

"""
ICT Testing Baseline v3.1 Conformance Auditor

Implements automated accessibility checks for Baselines 6 (Images),
10 (Forms), 11 (Page Titles), 12 (Tables), 13 (Structure), 15 (Language).
Produces a JSON report mapping findings to Baseline Test IDs and WCAG SC.
"""

import json
import os
import sys
from bs4 import BeautifulSoup

PAGES_DIR = "/app/pages"
OUTPUT_PATH = "/app/report.json"


# =====================================================================
# Accessible Name Computation (simplified W3C ACCNAME)
# =====================================================================


def compute_accessible_name(element, soup):
    """
    Compute the accessible name for an element following W3C ACCNAME precedence:
    aria-labelledby > aria-label > native label mechanism > title > text content.

    This is a simplified implementation covering the test cases in the audit.
    """
    # Step 1: aria-labelledby
    labelledby = element.get("aria-labelledby")
    if labelledby:
        ids = labelledby.split()
        texts = []
        for ref_id in ids:
            ref_el = soup.find(id=ref_id)
            if ref_el:
                texts.append(ref_el.get_text(strip=True))
        result = " ".join(texts).strip()
        if result:
            return result
        # If no valid IDREFs resolved, fall through per spec

    # Step 2: aria-label
    aria_label = element.get("aria-label")
    if aria_label is not None:
        return aria_label.strip()

    # Step 3: Native labeling mechanisms
    tag = element.name

    # For <img>: alt attribute
    if tag == "img":
        alt = element.get("alt")
        if alt is not None:
            return alt

    # For <input type="image">: alt attribute
    if tag == "input" and (element.get("type") or "").lower() == "image":
        alt = element.get("alt")
        if alt is not None:
            return alt

    # For form controls: <label for="id"> association
    el_id = element.get("id")
    if el_id and tag in ("input", "select", "textarea"):
        label = soup.find("label", attrs={"for": el_id})
        if label:
            return label.get_text(strip=True)

    # Step 4: title attribute
    title = element.get("title")
    if title is not None:
        return title.strip()

    # Step 5: Text content (for buttons, links, and elements with widget roles)
    if tag in ("button", "a") or element.get("role") in ("button", "link"):
        text = element.get_text(strip=True)
        if text:
            return text

    return ""


# =====================================================================
# Focusability check
# =====================================================================


def is_focusable(element):
    """Check if an element is keyboard focusable."""
    tabindex = element.get("tabindex")
    if tabindex is not None:
        try:
            return int(tabindex) >= 0
        except (ValueError, TypeError):
            return False
    # Natively focusable elements
    tag = element.name
    if tag in ("a",) and element.has_attr("href"):
        return True
    if tag in ("button", "input", "select", "textarea"):
        return not element.has_attr("disabled")
    return False


# =====================================================================
# Baseline 6: Images
# =====================================================================


def check_images(soup):
    """
    Baseline 6.A (MeaningfulImage) and 6.B (DecorativeImage).

    6.A: Images with non-empty text alternative — verify role is not
         presentation/none (conflict resolution).
    6.B: Images with empty text alternative — verify proper decorative
         technique is used, image is not focusable, no attribute conflicts.
    """
    findings = []

    # Collect all image elements: <img> and elements with role="img"
    images = list(soup.find_all("img"))
    for el in soup.find_all(attrs={"role": "img"}):
        if el not in images:
            images.append(el)

    for img in images:
        el_id = img.get("id")
        if not el_id:
            continue

        role = (img.get("role") or "").lower()
        acc_name = compute_accessible_name(img, soup)
        is_html_img = img.name == "img"

        # --- Case 1: Non-empty accessible name → test under 6.A ---
        if acc_name.strip():
            # Check for presentational role conflict
            if role in ("presentation", "none"):
                findings.append({
                    "element_id": el_id,
                    "baseline_test_id": "6.A",
                    "result": "FAIL",
                    "wcag_sc": "4.1.2",
                    "description": (
                        f"Presentational role conflict: role=\"{role}\" "
                        f"on image with non-empty text alternative"
                    ),
                })

        # --- Case 2: Empty accessible name → test under 6.B ---
        else:
            # 2a: Element with explicit role="img" but no name
            #     (intended to be meaningful but missing accessible name)
            if role == "img" and not is_html_img:
                findings.append({
                    "element_id": el_id,
                    "baseline_test_id": "6.A",
                    "result": "FAIL",
                    "wcag_sc": "1.1.1",
                    "description": (
                        "Element with role=\"img\" has no accessible name "
                        "(missing text alternative for non-text content)"
                    ),
                })

            # 2b: HTML <img> with no alt attribute and no other technique
            elif is_html_img and not img.has_attr("alt"):
                has_pres = role in ("presentation", "none")
                has_hidden = img.get("aria-hidden") == "true"
                if not has_pres and not has_hidden:
                    findings.append({
                        "element_id": el_id,
                        "baseline_test_id": "6.B",
                        "result": "FAIL",
                        "wcag_sc": "1.1.1",
                        "description": (
                            "Image missing alt attribute and no other text "
                            "alternative technique (F65)"
                        ),
                    })

            # 2c: HTML <img> with a decorative technique — check for issues
            elif is_html_img:
                has_empty_alt = img.has_attr("alt") and img["alt"] == ""
                has_pres = role in ("presentation", "none")
                has_hidden = img.get("aria-hidden") == "true"

                if has_empty_alt or has_pres or has_hidden:
                    # Check: decorative image must not be focusable
                    if is_focusable(img):
                        findings.append({
                            "element_id": el_id,
                            "baseline_test_id": "6.B",
                            "result": "FAIL",
                            "wcag_sc": "1.1.1",
                            "description": (
                                "Decorative image is keyboard focusable "
                                "(in tab order via tabindex)"
                            ),
                        })

    return findings


# =====================================================================
# Baseline 10: Forms
# =====================================================================


def check_forms(soup):
    """
    Baseline 10.A (FormName): Verify form controls have non-empty
    accessible names computed per W3C ACCNAME.
    """
    findings = []

    form_controls = soup.find_all(["input", "select", "textarea", "button"])

    for ctrl in form_controls:
        el_id = ctrl.get("id")
        if not el_id:
            continue

        # Skip hidden inputs
        input_type = (ctrl.get("type") or "text").lower()
        if input_type == "hidden":
            continue

        acc_name = compute_accessible_name(ctrl, soup)

        if not acc_name or not acc_name.strip():
            findings.append({
                "element_id": el_id,
                "baseline_test_id": "10.A",
                "result": "FAIL",
                "wcag_sc": "4.1.2",
                "description": (
                    "Form control has no accessible name "
                    "(empty result from accessible name computation)"
                ),
            })

    return findings


# =====================================================================
# Baseline 12: Tables
# =====================================================================


def check_tables(soup):
    """
    Baseline 12.A (DataTableRole): Verify table/row/cell role assignments.
    Baseline 12.B (DataTableHeaderAssociation): Verify headers attribute
    ID references resolve within the same table.
    """
    findings = []

    # --- HTML tables ---
    html_tables = soup.find_all("table")
    for table in html_tables:
        table_id = table.get("id")
        if not table_id:
            continue

        table_role = (table.get("role") or "").lower()

        # Skip layout tables that are properly marked with role="presentation"/"none"
        if table_role in ("presentation", "none"):
            continue

        # 12.B: Validate headers attribute references
        cells_with_headers = table.find_all(attrs={"headers": True})
        for cell in cells_with_headers:
            raw_headers = cell.get("headers", "")
            if isinstance(raw_headers, list):
                headers_val = raw_headers
            else:
                headers_val = raw_headers.split()
            for hid in headers_val:
                ref = table.find(id=hid)
                if ref is None:
                    cell_id = cell.get("id", table_id + "_cell")
                    findings.append({
                        "element_id": cell_id,
                        "baseline_test_id": "12.B",
                        "result": "FAIL",
                        "wcag_sc": "1.3.1",
                        "description": (
                            f"headers attribute references nonexistent "
                            f"id \"{hid}\" within the table"
                        ),
                    })
                    break  # Report once per cell

    # --- ARIA tables ---
    aria_tables = []
    for role_val in ("table", "grid", "treegrid"):
        aria_tables.extend(soup.find_all(attrs={"role": role_val}))

    for atable in aria_tables:
        # Skip HTML <table> elements (already checked above)
        if atable.name == "table":
            continue

        atable_id = atable.get("id")
        if not atable_id:
            continue

        atable_role = (atable.get("role") or "").lower()
        expected_cell_roles = {"cell", "gridcell"}
        header_roles = {"columnheader", "rowheader"}

        # 12.A: Check that data cells have proper role
        has_missing_cell_role = False
        rows = atable.find_all(attrs={"role": "row"})

        for row in rows:
            for child in row.find_all(recursive=False):
                child_role = (child.get("role") or "").lower()
                if child_role in expected_cell_roles | header_roles:
                    continue
                # Child in a row without a table cell/header role
                text = child.get_text(strip=True)
                if text:
                    has_missing_cell_role = True
                    break
            if has_missing_cell_role:
                break

        if has_missing_cell_role:
            findings.append({
                "element_id": atable_id,
                "baseline_test_id": "12.A",
                "result": "FAIL",
                "wcag_sc": "4.1.2",
                "description": (
                    "ARIA table data cells missing required role "
                    "(expected role=\"cell\" or role=\"gridcell\")"
                ),
            })

    return findings


# =====================================================================
# Baseline 13: Content Structure (Headings)
# =====================================================================


def check_headings(soup):
    """
    Baseline 13.A (HeadingDescriptive): Verify programmatic headings
    have non-empty text content describing their topic.
    """
    findings = []

    # Find all programmatic headings
    heading_tags = ["h1", "h2", "h3", "h4", "h5", "h6"]
    headings = list(soup.find_all(heading_tags))
    # Also include elements with role="heading" that are not native headings
    for el in soup.find_all(attrs={"role": "heading"}):
        if el.name not in heading_tags:
            headings.append(el)

    for heading in headings:
        el_id = heading.get("id")
        if not el_id:
            continue

        text = heading.get_text(strip=True)
        if not text:
            findings.append({
                "element_id": el_id,
                "baseline_test_id": "13.A",
                "result": "FAIL",
                "wcag_sc": "2.4.6",
                "description": (
                    "Heading element is empty "
                    "(does not describe topic or purpose)"
                ),
            })

    return findings


# =====================================================================
# Baseline 11: Page Titles & Baseline 15: Language
# =====================================================================


def check_page_level(soup):
    """
    Baseline 11.A (PageTitled): Page must have non-empty <title>.
    Baseline 15.A (LanguageOfPage): <html> must have valid lang attribute.
    """
    findings = []

    # 15.A: Language of Page
    html_el = soup.find("html")
    if html_el:
        lang = (html_el.get("lang") or "").strip()
        if not lang:
            xml_lang = (html_el.get("xml:lang") or "").strip()
            if not xml_lang:
                findings.append({
                    "element_id": "html",
                    "baseline_test_id": "15.A",
                    "result": "FAIL",
                    "wcag_sc": "3.1.1",
                    "description": (
                        "html element missing lang attribute "
                        "(page language not programmatically identified)"
                    ),
                })

    # 11.A: Page Titled
    title_el = soup.find("title")
    if not title_el or not title_el.get_text(strip=True):
        findings.append({
            "element_id": "title",
            "baseline_test_id": "11.A",
            "result": "FAIL",
            "wcag_sc": "2.4.2",
            "description": "Page title is missing or empty",
        })

    return findings


# =====================================================================
# Main Audit Engine
# =====================================================================


def audit_page(filepath):
    """Run all baseline checks on a single HTML page."""
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    soup = BeautifulSoup(content, "html.parser")

    findings = []
    findings.extend(check_images(soup))
    findings.extend(check_forms(soup))
    findings.extend(check_tables(soup))
    findings.extend(check_headings(soup))
    findings.extend(check_page_level(soup))

    return findings


def main():
    report = {
        "baseline_version": "3.1",
        "pages": {},
    }

    if not os.path.isdir(PAGES_DIR):
        print(f"Error: pages directory not found at {PAGES_DIR}", file=sys.stderr)
        sys.exit(1)

    for filename in sorted(os.listdir(PAGES_DIR)):
        if not filename.endswith(".html"):
            continue
        filepath = os.path.join(PAGES_DIR, filename)
        findings = audit_page(filepath)
        report["pages"][filename] = {"findings": findings}
        print(f"  {filename}: {len(findings)} finding(s)")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    total = sum(len(p["findings"]) for p in report["pages"].values())
    print(f"\nAudit complete. {total} finding(s) written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
