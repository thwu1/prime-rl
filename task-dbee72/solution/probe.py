#!/usr/bin/env python3
"""
Interaction Probe: analyzes web application interactivity via headless
Chromium, MutationObserver injection, and DOM mutation classification.

Usage: python3 interaction_probe.py <path_to_html_file>
"""

import json
import sys
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright


# ---------------------------------------------------------------------------
# Shared JavaScript: recursive element discovery including Shadow DOM
# ---------------------------------------------------------------------------

_FIND_ALL_JS = """
function findAllInteractive() {
    var results = [];
    function isInteractive(el) {
        if (!el || !el.tagName) return false;
        var tag = el.tagName.toLowerCase();
        var role = (el.getAttribute('role') || '').toLowerCase();
        var interTags = ['button', 'input', 'select', 'textarea'];
        var interRoles = ['button', 'tab', 'slider', 'checkbox', 'switch',
                          'combobox', 'menuitem', 'option', 'radio'];
        if (interTags.indexOf(tag) >= 0) return true;
        if (interRoles.indexOf(role) >= 0) return true;
        if (tag === 'a' && el.hasAttribute('href')) return true;
        if (el.hasAttribute('onclick')) return true;
        return false;
    }
    function actionFor(el) {
        var tag = el.tagName.toLowerCase();
        var type = (el.getAttribute('type') || '').toLowerCase();
        if (tag === 'input') {
            if (type === 'checkbox' || type === 'radio') return 'check';
            if (type === 'range') return 'slide';
            if (['button','submit','reset','image'].indexOf(type) >= 0) return 'click';
            return 'type';
        }
        if (tag === 'select') return 'select';
        if (tag === 'textarea') return 'type';
        return 'click';
    }
    function traverse(root, inShadow) {
        var els = root.querySelectorAll ? Array.from(root.querySelectorAll('*')) : [];
        for (var i = 0; i < els.length; i++) {
            var el = els[i];
            if (isInteractive(el)) {
                results.push({
                    el: el,
                    tag: el.tagName.toLowerCase(),
                    role: (el.getAttribute('role') || el.tagName.toLowerCase()),
                    label: ((el.textContent || '').trim().substring(0, 50) ||
                            el.getAttribute('aria-label') ||
                            el.getAttribute('placeholder') ||
                            el.getAttribute('id') || ''),
                    action: actionFor(el),
                    shadow: !!inShadow,
                    sel: el.id ? '#' + el.id : el.tagName.toLowerCase()
                });
            }
            if (el.shadowRoot) {
                traverse(el.shadowRoot, true);
            }
        }
    }
    traverse(document.body, false);
    return results;
}
"""

# ---------------------------------------------------------------------------
# Phase-specific JavaScript snippets
# ---------------------------------------------------------------------------

DISCOVER_JS = "() => { " + _FIND_ALL_JS + """
    return findAllInteractive().map(function(r, i) {
        return {
            tag: r.tag, role: r.role, label: r.label,
            actionType: r.action, inShadow: r.shadow,
            selector: r.sel, index: i
        };
    });
}"""

INTERACT_JS = "(args) => { " + _FIND_ALL_JS + """
    var found = findAllInteractive();
    var idx = args.idx;
    var act = args.action;
    if (idx >= found.length) return false;
    var el = found[idx].el;
    try {
        if (act === 'click') {
            el.click();
        } else if (act === 'type') {
            el.focus();
            el.value = 'test value';
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
        } else if (act === 'select') {
            if (el.options && el.options.length > 1) {
                el.selectedIndex = 1;
                el.dispatchEvent(new Event('change', {bubbles: true}));
            }
        } else if (act === 'check') {
            el.click();
        } else if (act === 'slide') {
            el.value = 75;
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
        } else {
            el.click();
        }
        return true;
    } catch(e) { return false; }
}"""

OBSERVER_JS = """() => {
    window.__mutations = [];
    var obs = new MutationObserver(function(muts) {
        for (var i = 0; i < muts.length; i++) {
            var m = muts[i];
            window.__mutations.push({
                type: m.type,
                attr: m.attributeName || null,
                oldVal: m.oldValue || null,
                newVal: (m.type === 'attributes' && m.target && m.target.getAttribute)
                        ? m.target.getAttribute(m.attributeName) : null,
                added: m.addedNodes.length,
                removed: m.removedNodes.length
            });
        }
    });
    obs.observe(document.body, {
        attributes: true, childList: true, subtree: true,
        characterData: true, attributeOldValue: true
    });
}"""

COLLECT_JS = "() => window.__mutations || []"


# ---------------------------------------------------------------------------
# Mutation classification heuristics
# ---------------------------------------------------------------------------

MEANINGFUL_ATTRS = frozenset([
    'aria-selected', 'aria-expanded', 'aria-checked', 'aria-hidden',
    'aria-disabled', 'disabled', 'hidden', 'checked', 'selected',
    'value', 'src', 'href', 'data-state', 'data-active',
])

MEANINGFUL_CLASSES = frozenset([
    'active', 'hidden', 'visible', 'selected', 'disabled', 'collapsed',
    'expanded', 'open', 'closed', 'dark', 'light', 'show', 'hide',
])

STYLE_MEANINGFUL = ('display', 'visibility', 'opacity', 'background', 'color')


def is_meaningful(m):
    """Return True if a mutation dict represents a meaningful state change."""
    mtype = m.get('type', '')

    if mtype == 'childList':
        return m.get('added', 0) > 0 or m.get('removed', 0) > 0

    if mtype == 'characterData':
        return True

    if mtype == 'attributes':
        attr = m.get('attr') or ''
        if attr in MEANINGFUL_ATTRS:
            return True
        if attr == 'style':
            combined = (m.get('oldVal') or '') + (m.get('newVal') or '')
            return any(p in combined for p in STYLE_MEANINGFUL)
        if attr == 'class':
            old_set = set((m.get('oldVal') or '').split())
            new_set = set((m.get('newVal') or '').split())
            diff = old_set.symmetric_difference(new_set)
            return bool(diff & MEANINGFUL_CLASSES)

    return False


# ---------------------------------------------------------------------------
# Main probe logic
# ---------------------------------------------------------------------------

async def run_probe(html_path):
    url = 'file://' + str(Path(html_path).resolve())

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage']
        )
        page = await browser.new_page()

        # --- Phase 1: discover interactive elements ---
        await page.goto(url, wait_until='networkidle')
        await page.wait_for_timeout(500)
        elements = await page.evaluate(DISCOVER_JS)

        # --- Phase 2: probe each element in isolation ---
        probed = []
        for info in elements:
            # Reload to reset state
            await page.goto(url, wait_until='networkidle')
            await page.wait_for_timeout(300)

            # Inject MutationObserver
            await page.evaluate(OBSERVER_JS)
            await page.wait_for_timeout(100)

            # Perform interaction
            try:
                await page.evaluate(
                    INTERACT_JS,
                    {'idx': info['index'], 'action': info['actionType']}
                )
            except Exception:
                pass

            # Wait for async mutations to settle
            await page.wait_for_timeout(500)

            # Collect mutations
            mutations = await page.evaluate(COLLECT_JS)

            meaningful_count = sum(1 for m in mutations if is_meaningful(m))

            probed.append({
                'selector': info['selector'],
                'tag': info['tag'],
                'role': info['role'],
                'label': info['label'],
                'action_type': info['actionType'],
                'in_shadow_dom': info['inShadow'],
                'mutations_observed': len(mutations),
                'meaningful_mutations': meaningful_count,
                'state_changed': meaningful_count > 0,
            })

        await browser.close()

    # --- Phase 3: compute summary ---
    total = len(probed)
    state_changing = sum(1 for r in probed if r['state_changed'])

    return {
        'url': url,
        'elements': probed,
        'summary': {
            'total_elements': total,
            'state_changing_elements': state_changing,
            'interaction_rate': round(state_changing / total, 4) if total > 0 else 0.0,
            'total_mutations': sum(r['mutations_observed'] for r in probed),
            'meaningful_mutations': sum(r['meaningful_mutations'] for r in probed),
        },
    }


async def main():
    if len(sys.argv) < 2:
        print('Usage: python3 interaction_probe.py <html_file>', file=sys.stderr)
        sys.exit(1)
    report = await run_probe(sys.argv[1])
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
