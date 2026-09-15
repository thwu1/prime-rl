Build an automated accessibility conformance auditor aligned to the **ICT Testing Baseline for Web v3.1**. The tool must parse the HTML files in `/app/pages/`, execute automated checks for the Baseline Tests listed below, and produce a JSON report at `/app/report.json`.

## Scope

Implement automated checks for these ICT Baseline Tests:

- **Baseline 6** — Images (6.A MeaningfulImage, 6.B DecorativeImage)
- **Baseline 10** — Forms (10.A FormName)
- **Baseline 11** — Page Titles (11.A PageTitled)
- **Baseline 12** — Tables (12.A DataTableRole, 12.B DataTableHeaderAssociation)
- **Baseline 13** — Content Structure (13.A HeadingDescriptive)
- **Baseline 15** — Language (15.A LanguageOfPage)

## Key Implementation Requirements

The auditor must correctly implement **accessible name computation** following the W3C Accessible Name and Description Computation specification. The computation precedence is: `aria-labelledby` (resolve ID references, concatenate text) > `aria-label` > native labeling mechanism (`alt` for images, `<label for>` for form controls) > `title` attribute > text content (for buttons/links).

For images, the auditor must detect **ARIA presentational role conflicts** per WAI-ARIA Presentational Roles Conflict Resolution — an image with `role="none"` or `role="presentation"` that also carries a non-empty text alternative has a conflict that must be flagged. Decorative images (empty text alternative) that are keyboard-focusable (via `tabindex`) must also be flagged. Images missing any text alternative technique entirely (no `alt`, no `aria-label`, no `aria-labelledby`, no `role="presentation"/"none"`, no `aria-hidden="true"`) must be flagged.

For tables, validate that `headers` attribute ID references resolve to existing elements within the same `<table>`. For ARIA tables (`role="table"`), verify that data cells have `role="cell"`; for ARIA grids, verify `role="gridcell"`.

The report format is defined in `/app/audit_spec.json`. Report **FAIL findings only** — elements passing all checks are omitted. Each finding must include `element_id`, `baseline_test_id`, `result`, `wcag_sc`, and `description`.

Write the auditor as `/app/audit.py` and execute it.