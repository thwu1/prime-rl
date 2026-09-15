#!/usr/bin/env python3

"""
Interaction probe: discovers all interactive elements in a web application,
including those hidden behind state transitions and inside Shadow DOM.
Outputs a structured JSON report.
"""

import asyncio
import json
import http.server
import threading
import functools
import time
from playwright.async_api import async_playwright


def start_server(directory):
    """Start a local HTTP server on an OS-assigned port. Returns the server."""
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=directory
    )
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# JavaScript: find all visible interactive elements, including inside shadow DOM
FIND_ELEMENTS_JS = """() => {
    var results = [];
    var ITAGS = new Set(['INPUT', 'SELECT', 'BUTTON', 'TEXTAREA']);

    function isInteractive(el) {
        if (ITAGS.has(el.tagName)) return true;
        if (el.tagName === 'A' && el.hasAttribute('href')) return true;
        if (el.hasAttribute('onclick') || el.hasAttribute('onchange')) return true;
        if (el.tagName === 'TH' && el.hasAttribute('data-sort')) return true;
        return false;
    }

    function isVisible(el) {
        if (!el.isConnected) return false;
        var cur = el;
        while (cur) {
            if (cur.nodeType !== 1) break;
            var st = window.getComputedStyle(cur);
            if (st.display === 'none' || st.visibility === 'hidden') return false;
            if (cur.getRootNode() instanceof ShadowRoot) {
                cur = cur.getRootNode().host;
            } else {
                cur = cur.parentElement;
            }
        }
        return true;
    }

    function traverse(root, inShadow) {
        var els = root.querySelectorAll('*');
        for (var i = 0; i < els.length; i++) {
            var el = els[i];
            if (el.id && isInteractive(el) && isVisible(el)) {
                results.push({
                    id: el.id,
                    tag: el.tagName,
                    type: el.getAttribute('type') || '',
                    in_shadow_dom: inShadow
                });
            }
            if (el.shadowRoot) {
                traverse(el.shadowRoot, true);
            }
        }
    }

    traverse(document, false);
    return results;
}"""


# JavaScript: set up MutationObservers on document.body and all shadow roots
SETUP_OBSERVERS_JS = """() => {
    if (window.__observers) {
        for (var i = 0; i < window.__observers.length; i++) {
            window.__observers[i].disconnect();
        }
    }
    window.__observers = [];
    window.__mutations = [];

    var cfg = {
        childList: true, attributes: true, characterData: true,
        subtree: true, attributeOldValue: true, characterDataOldValue: true
    };

    var docObs = new MutationObserver(function(ms) {
        for (var j = 0; j < ms.length; j++) {
            window.__mutations.push({
                type: ms[j].type,
                target: ms[j].target.id || ms[j].target.tagName
            });
        }
    });
    docObs.observe(document.body, cfg);
    window.__observers.push(docObs);

    var allEls = document.querySelectorAll('*');
    for (var k = 0; k < allEls.length; k++) {
        if (allEls[k].shadowRoot) {
            (function(sr) {
                var sObs = new MutationObserver(function(ms) {
                    for (var j = 0; j < ms.length; j++) {
                        window.__mutations.push({
                            type: ms[j].type,
                            target: ms[j].target.id || ms[j].target.tagName,
                            shadow: true
                        });
                    }
                });
                sObs.observe(sr, cfg);
                window.__observers.push(sObs);
            })(allEls[k].shadowRoot);
        }
    }
}"""


# JavaScript: interact with a shadow DOM element by ID
SHADOW_INTERACT_JS = """(eid) => {
    function findInShadow(root) {
        var els = root.querySelectorAll('*');
        for (var i = 0; i < els.length; i++) {
            if (els[i].shadowRoot) {
                var found = els[i].shadowRoot.getElementById(eid);
                if (found) return found;
                var deeper = findInShadow(els[i].shadowRoot);
                if (deeper) return deeper;
            }
        }
        return null;
    }
    var el = findInShadow(document);
    if (!el) return false;

    if (el.tagName === 'SELECT') {
        if (el.options.length > 1) {
            el.selectedIndex = el.selectedIndex === 0 ? 1 : 0;
            el.dispatchEvent(new Event('change', {bubbles: true}));
        }
    } else if (el.tagName === 'INPUT' && el.type === 'checkbox') {
        el.checked = !el.checked;
        el.dispatchEvent(new Event('change', {bubbles: true}));
    } else if (el.tagName === 'INPUT') {
        el.value = '42';
        el.dispatchEvent(new Event('input', {bubbles: true}));
    } else {
        el.click();
    }
    return true;
}"""


def element_priority(el):
    """Lower number = interact first. Inputs before selects before checkboxes before buttons."""
    tag = el["tag"]
    etype = el.get("type", "")
    eid = el["id"]

    if tag == "INPUT" and etype == "number":
        return 0
    if tag == "INPUT" and etype not in ("checkbox", "radio"):
        return 1
    if tag == "SELECT":
        return 2
    if tag == "INPUT" and etype == "checkbox":
        return 3
    if tag == "INPUT" and etype == "radio":
        return 4
    if tag == "TH":
        return 5
    if tag == "BUTTON" and "reset" in eid:
        return 8
    if tag == "BUTTON" and "export" in eid:
        return 7
    if tag == "BUTTON":
        return 6
    return 9


async def interact_with(page, el):
    """Perform the appropriate semantic action on an element. Returns True on success."""
    eid = el["id"]
    tag = el["tag"]
    etype = el.get("type", "")
    in_shadow = el.get("in_shadow_dom", False)

    try:
        if in_shadow:
            await page.evaluate(SHADOW_INTERACT_JS, eid)
        else:
            loc = page.locator(f"#{eid}")
            if tag == "SELECT":
                opts = await loc.locator("option").all()
                for opt in opts[1:]:
                    val = await opt.get_attribute("value")
                    if val:
                        await loc.select_option(val)
                        break
            elif tag == "INPUT" and etype == "checkbox":
                if await loc.is_checked():
                    await loc.uncheck()
                else:
                    await loc.check()
            elif tag == "INPUT" and etype == "number":
                await loc.fill("100")
            elif tag == "INPUT":
                await loc.fill("test")
            elif tag in ("BUTTON", "TH"):
                await loc.click()

        await page.wait_for_timeout(350)
        return True
    except Exception as exc:
        print(f"  [warn] interact {eid}: {exc}")
        return False


async def run_probe():
    """Main probe logic."""
    server = start_server("/app/webapp")
    port = server.server_address[1]
    time.sleep(0.3)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = await browser.new_page()
        await page.goto(
            f"http://127.0.0.1:{port}/index.html", wait_until="domcontentloaded"
        )
        await page.wait_for_timeout(500)

        # Set up mutation observers
        await page.evaluate(SETUP_OBSERVERS_JS)

        # Discover initial elements
        initial = await page.evaluate(FIND_ELEMENTS_JS)
        initial_ids = {e["id"] for e in initial}

        all_els = {}
        for e in initial:
            e["initially_visible"] = True
            all_els[e["id"]] = e

        processed = set()
        chains = []
        mutation_map = {}

        # Iterative discovery: interact with elements, check for newly-revealed ones
        for _ in range(30):  # safety bound
            todo = sorted(
                [eid for eid in all_els if eid not in processed],
                key=lambda eid: (element_priority(all_els[eid]), eid),
            )
            if not todo:
                break

            for eid in todo:
                if eid in processed:
                    continue
                processed.add(eid)

                # Clear mutation log
                await page.evaluate("() => { window.__mutations = []; }")

                ok = await interact_with(page, all_els[eid])

                if ok:
                    muts = await page.evaluate("() => window.__mutations || []")
                    mutation_map[eid] = len(muts) > 0

                    # Scan for new elements (including newly-visible ones and shadow DOM)
                    current = await page.evaluate(FIND_ELEMENTS_JS)
                    revealed = []
                    for e in current:
                        if e["id"] not in all_els:
                            e["initially_visible"] = False
                            all_els[e["id"]] = e
                            revealed.append(e["id"])

                    if revealed:
                        chains.append(
                            {"trigger": eid, "revealed": sorted(revealed)}
                        )
                        # Re-setup observers to cover new shadow roots
                        await page.evaluate(SETUP_OBSERVERS_JS)
                else:
                    mutation_map[eid] = False

        # Assemble report
        elements = []
        for eid in sorted(all_els):
            e = all_els[eid]
            elements.append(
                {
                    "id": eid,
                    "tag": e["tag"],
                    "in_shadow_dom": e.get("in_shadow_dom", False),
                    "initially_visible": e.get("initially_visible", False),
                    "produces_mutation": mutation_map.get(eid, False),
                }
            )

        shadow_els = sorted(e["id"] for e in elements if e["in_shadow_dom"])
        total = len(elements)
        producing = sum(1 for e in elements if e["produces_mutation"])
        ir = producing / total if total else 0.0

        report = {
            "total_elements": total,
            "elements": elements,
            "discovery_chains": chains,
            "shadow_dom_elements": shadow_els,
            "interaction_rate": round(ir, 4),
        }

        with open("/app/report.json", "w") as f:
            json.dump(report, f, indent=2)

        print(f"Report written: {total} elements, IR={ir:.4f}")
        print(f"  Shadow DOM: {shadow_els}")
        print(f"  Chains: {len(chains)}")

        await browser.close()

    server.shutdown()


if __name__ == "__main__":
    asyncio.run(run_probe())
