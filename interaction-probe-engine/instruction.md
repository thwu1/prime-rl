Three interactive HTML web applications are located in `/app/pages/`. Build an automated probe engine that analyzes each application and produces a structured interactivity report.

The probe must discover every interactive DOM element in each page and determine whether that element is genuinely responsive — meaning that interacting with it causes observable state changes in the page's DOM. Elements that merely appear interactive (e.g., styled with `cursor:pointer`) but produce no state changes must be identified as non-responsive.

The pages contain diverse interaction challenges: standard form elements, elements that live inside Shadow DOM web components, elements whose events are handled by parent containers rather than the elements themselves, input handlers that delay their effects, conditionally disabled controls, and dynamically created elements.

Write the report to `/app/output/report.json` with this structure:

```json
{
  "pages": {
    "<filename>": {
      "total_interactive": <int>,
      "responsive": <int>,
      "interaction_rate": <float>,
      "elements": [
        {
          "selector": "<string>",
          "tag": "<string>",
          "action_type": "<string>",
          "mutations_count": <int>,
          "responsive": <bool>
        }
      ]
    }
  },
  "aggregate": {
    "total_interactive": <int>,
    "total_responsive": <int>,
    "interaction_rate": <float>
  }
}
```

- `interaction_rate` is `responsive / total_interactive` for each page, and `total_responsive / total_interactive` for the aggregate.
- Valid action types: `click`, `input`, `select`, `check`, `radio`, `range`.
- `mutations_count` is the number of DOM mutations observed as a result of the interaction.

Entry point: `python3 /app/probe.py`

Playwright and Chromium are pre-installed in the environment.