A multi-phase interactive web application is located at `/app/webapp/index.html`. It implements a scientific optimization benchmark tool with sequential workflow phases, conditional UI sections that are initially hidden and only appear after certain user actions, form validation that gates phase transitions, and a custom web component (`<result-chart>`) whose interactive controls live inside Shadow DOM.

Build `/app/probe.py` — a Playwright-based headless browser probe that programmatically discovers **every** interactive element in the application and writes a complete interaction report to `/app/report.json`.

The probe must correctly handle:
- Elements that are not visible on initial page load
- Elements inside Shadow DOM boundaries
- Form validation constraints that must be satisfied before the application advances
- Determining whether interacting with each element produces a meaningful change in the page

Required report schema for `/app/report.json`:

    {
      "total_elements": <int>,
      "elements": [
        {"id": <str>, "tag": <str>, "in_shadow_dom": <bool>,
         "initially_visible": <bool>, "produces_mutation": <bool>}
      ],
      "discovery_chains": [
        {"trigger": <str>, "revealed": [<str>]}
      ],
      "shadow_dom_elements": [<str>],
      "interaction_rate": <float>
    }

`interaction_rate` = (elements producing meaningful DOM mutations) / (total interactive elements).