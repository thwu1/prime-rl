Implement a WAI-ARIA compliant virtual screen reader module in Python at `/app/screen_reader.py`.

The module must provide a `VirtualScreenReader` class (interface defined in the existing skeleton file) that parses HTML and builds an accessibility tree following WAI-ARIA 1.2 and HTML-AAM 1.0 specifications, then supports linear and command-based navigation producing correct spoken phrases.

Required behaviors:

- **HTML-to-ARIA role mapping** per HTML-AAM 1.0: `<nav>` → navigation, `<footer>` → contentinfo (when scoping root), `<header>` → banner (when scoping root), `<section>` → region (only with accessible name), `<article>` → article, `<h1>`–`<h6>` → heading with level, `<a href>` → link, `<button>` → button, `<ul>`/`<ol>` → list, `<li>` → listitem, `<p>` → paragraph, `<form>` → form (only with accessible name), explicit `role` attributes override implicit roles
- **Accessible name computation** (simplified ACCNAME 1.2): `aria-labelledby` (ID reference resolution), `aria-label`, text content for name-from-content roles
- **Tree linearization**: depth-first traversal, container roles produce start and end announcements (e.g. `"navigation"` / `"end of navigation"`), leaf nodes produce a single announcement
- **Spoken phrase format**: `"role, name, attributes"` — e.g. `"heading, Title, level 1"`, `"dialog, Name, modal"`
- **Hidden element exclusion**: `aria-hidden="true"`, `hidden` attribute
- **Inert handling**: `inert` attribute hides elements from tree, but modal dialogs (`role="dialog" aria-modal="true"`) escape inherited inert; explicitly inert elements are always hidden
- **`aria-owns` reparenting**: owned elements removed from original DOM position and appended to owner's children
- **Presentational roles**: `role="presentation"` and `role="none"` remove the element from tree, promoting its children
- **`childrenPresentational`**: roles like heading and button consume text children as accessible name (children not individually traversed), but focusable children (links, buttons, inputs) escape this and appear in the tree; the presentational context passes through escaped elements to their descendants
- **`aria-roledescription`**: custom role description replaces standard role name in spoken output
- **Navigation commands**: `moveToNextHeading`, `moveToPreviousHeading`, `moveToNextHeadingLevelN` (N=1..6), `moveToPreviousHeadingLevelN`, `moveToNextLandmark`, `moveToPreviousLandmark`

HTML fixtures are at `/app/html_fixtures/` and expected traversal outputs at `/app/expected_outputs.json`. The interface skeleton is at `/app/screen_reader.py`.