Three HTML pages in `/app/site/` contain accessibility violations against the DHS Trusted Tester v5.1.3 conformance test process. Build a tool that audits these pages and writes a structured violation report to `/app/audit_report.json`.

The audit must cover these Trusted Tester test conditions: 5.C (form label associations), 6.A (link purpose), 7.A (meaningful image accessible names), 7.B (decorative image treatment), 10.B (visual heading markup), 11.A (page language), 11.B (language of parts), 12.A (page titles), 12.D (iframe accessible names), 13.A (color-only information conveyance), 13.B (sensory-dependent instructions), 13.C (text contrast ratios), 14.B (data table header associations), 14.C (layout table misuse of data markup), and 15.A (CSS-generated meaningful content).

Output `/app/audit_report.json` in this format:

```json
{
  "violations": [
    {
      "file": "<filename>",
      "test_id": "<Trusted Tester test condition ID>",
      "wcag_sc": "<WCAG 2.0 Success Criterion number>",
      "element": "<CSS selector or element description>",
      "description": "<violation description>"
    }
  ]
}
```

Each violation must reference the correct WCAG 2.0 Success Criterion. Contrast ratio checks (13.C) must use the WCAG 2.0 relative luminance algorithm with proper sRGB linearization. Normal text requires 4.5:1; large text (>=18pt or >=14pt bold) requires 3:1. The tool must not produce false positives for correctly-implemented accessibility patterns present in the pages.