Build `/app/interaction_probe.py` — a headless browser automation tool that evaluates the interactivity of HTML-based web applications.

Given a path to an HTML file as its sole command-line argument, the tool must programmatically interact with every discoverable interactive element and produce a JSON interaction report to stdout, conforming to `/app/schema.json`.

## Goal

Determine which elements in a web application are truly interactive — that is, which produce meaningful application state changes versus merely cosmetic effects. A state change is **meaningful** if it alters text content, DOM structure, element visibility, or ARIA state. Focus/hover styling and transient class toggles for appearance-only effects are **cosmetic** and must not count as state changes.

The tool must handle standard form controls, buttons, Shadow DOM (open mode), custom web components, tabbed navigation with ARIA roles, range inputs, and conditionally-visible fields. Each element's semantic action — `click`, `type`, `select`, `check`, or `slide` — must be inferred from the element's type and attributes.

## Output

The JSON report contains two top-level keys (see `/app/schema.json` for the full specification):

- **`elements`** — array of discovered interactive elements. Each entry must include `action_type` (string), `state_changed` (boolean), `mutations_observed` (integer ≥ 0), and `meaningful_mutations` (integer ≥ 0, ≤ `mutations_observed`). Additional descriptive fields (`selector`, `tag`, `role`, `label`, `in_shadow_dom`) are recommended.

- **`summary`** — includes `total_elements` (count of all discovered elements) and `interaction_rate` (float in [0, 1]: fraction of elements where `state_changed` is true).

## Sample Applications (`/app/samples/`)

- **`calculator.html`** — 17 calculator buttons that update a text display, expression history, and active-key indicator on click.
- **`dynamic_form.html`** — Registration form: text inputs for name/email, an account-type `<select>` dropdown (choosing "Business" reveals additional hidden fields), a terms `<input type="checkbox">`, and a submit button.
- **`tabbed_dashboard.html`** — Three tabs (`role="tab"`, `aria-selected`) switching panel visibility. Contains a status-refresh button, a `<input type="range">` slider, a notifications checkbox, and a `<theme-toggle>` custom element whose interactive button lives inside an open Shadow DOM.

## Environment

Playwright (Python) and Chromium are pre-installed. Set `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers` before launching the browser.