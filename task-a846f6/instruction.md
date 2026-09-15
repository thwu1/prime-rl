Build a Python command-line tool at `/app/audit.py` that performs automated Section 508 conformance auditing of HTML pages against a subset of the ICT Testing Baseline (v3.1).

The tool reads HTML files from a directory and produces a JSON conformance report. Invoke it as:

```
python3 /app/audit.py /app/pages/ /app/report.json
```

The tool must implement:

- **Accessible name computation** for images, form controls, and links following the W3C priority order: `aria-labelledby` (resolve ID references and concatenate text) → `aria-label` → native semantics (`alt` for images, `<label>` for form controls via `for`/`id` or wrapping, text content for links including child `<img>` alt text) → `title` attribute fallback.

- **WCAG color contrast ratio calculation** using sRGB linearization and relative luminance. Must parse hex (`#rrggbb`, `#rgb`), `rgb(r,g,b)`, and CSS named colors (at minimum: white, black, red, green, blue, gray/grey, silver, orange, yellow, cyan, magenta, maroon, olive, navy, teal, purple). Large text threshold: >=18pt, or >=14pt bold. Headings (h1-h6) without explicit font-size are large text.

- **Ten baseline tests** as configured in `/app/baseline_config.json`:
  - `15.A-LanguagePage`: `<html>` must have a non-empty `lang` attribute
  - `11.A-PageTitled`: page must have a non-empty `<title>` element
  - `6.A-MeaningfulImage`: images (not marked decorative via `alt=""`, `role=presentation/none`, or `aria-hidden=true`) must have an accessible name that is not a filename pattern (e.g. `*.png`, `*.jpg`)
  - `6.B-DecorativeImage`: images with `role=presentation` or `role=none` must not have conflicting non-empty `alt` or `aria-label`
  - `8.A-Contrast`: text with inline `color` and `background-color` styles must meet contrast thresholds
  - `10.A-FormName`: visible form controls (`input`, `select`, `textarea` — excluding `hidden`/`submit`/`button`/`reset`/`image` types) must have accessible names
  - `14.A-LinkPurpose`: links must have non-empty accessible names
  - `12.B-DataTableHeaderAssociation`: data tables (non-layout, >=2 rows) must have `<th>` or ARIA header roles
  - `21.D-AudioControl`: `<audio autoplay>` must have `controls` attribute
  - `3.A-NonInterference`: composite test that fails if any sub-test (`21.D-AudioControl`) fails

- **Test result classification**: each test per page is `"fail"` (violations found), `"pass"` (applicable content checked, no violations), or `"not_applicable"` (no relevant content on page).

The report JSON must conform to the schema at `/app/report_schema.json`. HTML test pages are in `/app/pages/`.