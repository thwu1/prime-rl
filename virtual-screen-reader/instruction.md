Implement a virtual screen reader at `/app/screen_reader.py` that builds an accessibility tree from HTML and supports navigation. The `VirtualScreenReader` class stub and its required API are already defined there (backup at `/data/screen_reader_stub.py`). Example HTML fixtures are in `/data/fixtures/`.

The implementation must conform to:
- **WAI-ARIA 1.2** — role semantics, `aria-owns`, `aria-flowto`, `aria-hidden`, `aria-modal`, `aria-valuenow`, `aria-valuetext`, presentational role inheritance
- **HTML-AAM 1.0** — implicit role mappings for 30+ HTML elements, including context-dependent roles
- **ACCNAME 1.2** — full accessible name and description computation, including interactions between `aria-labelledby` and embedded form controls

All of these features must work together coherently: `aria-owns` restructuring, presentational children, accessible value for widget roles, embedded control values in name computation, `aria-flowto` navigation, hidden/inert/modal scoping, sequential/role-based/landmark navigation with wrapping, and spoken phrase logging.

Spoken phrase format: `role, name, value, description, level N` — empty parts omitted, comma-separated. Containers with accessible children produce enter/exit markers (`"role[, name]"` / `"end of role[, name]"`). Roles that are generic, presentation, or none are transparent — their children are promoted to the parent level. Roles that support name-from-content absorb text descendants as the accessible name.