#!/usr/bin/env python3
"""
Interaction Probe Engine
Analyzes interactive HTML web applications by discovering interactive DOM
elements, exercising them in a headless browser, tracking DOM mutations via
MutationObserver, and computing Interaction Rate metrics.

"""

import asyncio
import json
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

PAGES_DIR = '/app/pages'
OUTPUT_DIR = '/app/output'
DEBOUNCE_WAIT_S = 0.65

# ── Scripts injected into the page ───────────────────────────────────

INIT_SCRIPT = """
(() => {
    const lm = new WeakMap();
    const orig = EventTarget.prototype.addEventListener;
    EventTarget.prototype.addEventListener = function(type, fn, opts) {
        if (!lm.has(this)) lm.set(this, []);
        lm.get(this).push(type);
        return orig.call(this, type, fn, opts);
    };
    window.__lm = lm;
    window.__hasL = el => { const t = lm.get(el); return t && t.length > 0; };
    window.__getL = el => lm.get(el) || [];
})();
"""

MUTATION_OBSERVER_SCRIPT = """
(() => {
    window.__mu = [];
    function obs(root) {
        new MutationObserver(ms => {
            ms.forEach(m => window.__mu.push({
                type: m.type,
                tTag: (m.target.tagName || 'TEXT'),
                tId: m.target.id || '',
                attr: m.attributeName || null,
                added: m.addedNodes.length,
                removed: m.removedNodes.length
            }));
        }).observe(root, {
            childList: true, attributes: true, characterData: true,
            subtree: true, attributeOldValue: true, characterDataOldValue: true
        });
    }
    obs(document.body);
    document.querySelectorAll('*').forEach(el => {
        if (el.shadowRoot) obs(el.shadowRoot);
    });
})();
"""

DISCOVER_SCRIPT = """
(() => {
    const results = [];
    const seen = new Set();
    const INTERACTIVE_EVENTS = new Set([
        'click','mousedown','mouseup','pointerdown','pointerup',
        'input','change','keydown','keyup','keypress','touchstart'
    ]);

    function sel(el, pfx) {
        var tag = el.tagName.toLowerCase();
        if (el.id) return (pfx||'') + '#' + el.id;
        if (tag === 'input' && el.name && el.type === 'radio')
            return (pfx||'') + 'input[name="'+el.name+'"][value="'+el.value+'"]';
        if (el.getAttribute && el.getAttribute('data-id'))
            return (pfx||'') + tag + '[data-id="'+el.getAttribute('data-id')+'"]';
        if (el.name)
            return (pfx||'') + tag + '[name="'+el.name+'"]';
        var p = el.parentElement;
        if (p) {
            var sibs = Array.from(p.children).filter(c => c.tagName === el.tagName);
            if (sibs.length > 1) {
                var idx = sibs.indexOf(el) + 1;
                var ps = p.id ? '#'+p.id : p.tagName.toLowerCase();
                return (pfx||'') + ps + ' > ' + tag + ':nth-of-type(' + idx + ')';
            }
        }
        if (el.className && typeof el.className === 'string' && el.className.trim())
            return (pfx||'') + tag + '.' + el.className.trim().split(/\\s+/)[0];
        return (pfx||'') + tag;
    }

    function classify(el) {
        var tag = el.tagName.toLowerCase();
        var tp = (el.getAttribute('type')||'').toLowerCase();
        if (tag==='button'||(tag==='input'&&(tp==='submit'||tp==='button'))) return 'click';
        if (tag==='a') return 'click';
        if (tag==='select') return 'select';
        if (tag==='textarea') return 'input';
        if (tag==='input') {
            if (tp==='checkbox') return 'check';
            if (tp==='radio') return 'radio';
            if (tp==='range') return 'range';
            return 'input';
        }
        return 'click';
    }

    function add(el, pfx, deleg) {
        var s = sel(el, pfx);
        var key = s + '|' + el.tagName;
        if (seen.has(key)) return;
        seen.add(key);
        results.push({
            selector: s,
            tag: el.tagName.toLowerCase(),
            action_type: classify(el),
            disabled: !!(el.disabled || el.getAttribute('disabled') !== null),
            in_shadow: !!(pfx),
            delegated: !!deleg
        });
    }

    function walk(root, pfx) {
        var all = root.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var tag = el.tagName.toLowerCase();
            // Standard interactive
            if (['button','select','textarea'].indexOf(tag) !== -1 ||
                tag === 'input' ||
                (tag === 'a' && el.href)) {
                add(el, pfx, false);
            }
            // Programmatic listeners
            else if (window.__hasL(el)) {
                var types = window.__getL(el);
                var hasInteractive = false;
                for (var t = 0; t < types.length; t++) {
                    if (INTERACTIVE_EVENTS.has(types[t])) { hasInteractive = true; break; }
                }
                if (hasInteractive) {
                    add(el, pfx, false);
                    // Delegation: if click listener, find likely child targets
                    if (types.indexOf('click') !== -1) {
                        var kids = el.querySelectorAll(
                            'li, tr, td, div[data-id], div[data-value], ' +
                            '[role="button"], [role="option"], [role="tab"], [role="menuitem"]'
                        );
                        for (var k = 0; k < kids.length; k++) {
                            var kt = kids[k].tagName.toLowerCase();
                            if (['button','input','select','textarea','a'].indexOf(kt)===-1) {
                                add(kids[k], pfx, true);
                            }
                        }
                    }
                }
            }
            // on* attributes
            else if (el.attributes) {
                for (var a = 0; a < el.attributes.length; a++) {
                    if (el.attributes[a].name.indexOf('on') === 0) {
                        add(el, pfx, false);
                        break;
                    }
                }
            }
            // ARIA roles
            var role = el.getAttribute && el.getAttribute('role');
            if (role && ['button','link','checkbox','radio','slider','tab',
                         'menuitem','switch','combobox','option'].indexOf(role) !== -1) {
                add(el, pfx, false);
            }
            // Shadow DOM
            if (el.shadowRoot) {
                walk(el.shadowRoot, sel(el, pfx) + ' >>> ');
            }
        }
    }

    walk(document, '');
    return results;
})();
"""


async def perform_action(page, elem):
    action = elem['action_type']
    selector = elem['selector']
    in_shadow = elem.get('in_shadow', False)
    disabled = elem.get('disabled', False)
    delegated = elem.get('delegated', False)

    if disabled:
        return False

    try:
        # Shadow DOM elements
        if in_shadow and '>>>' in selector:
            parts = selector.split(' >>> ')
            host_sel, inner_sel = parts[0], parts[1]
            return await page.evaluate('''(hs, is, act) => {
                try {
                    var host = document.querySelector(hs);
                    if (!host || !host.shadowRoot) return false;
                    var el = host.shadowRoot.querySelector(is);
                    if (!el) return false;
                    var tp = (el.getAttribute('type')||'').toLowerCase();
                    if (tp === 'range') {
                        var nv = String((parseFloat(el.max)+parseFloat(el.min))/2 + parseFloat(el.step||1));
                        Object.getOwnPropertyDescriptor(
                            HTMLInputElement.prototype, 'value'
                        ).set.call(el, nv);
                        el.dispatchEvent(new Event('input', {bubbles:true}));
                        el.dispatchEvent(new Event('change', {bubbles:true}));
                    } else if (el.tagName.toLowerCase() === 'input') {
                        el.value = 'probe_test';
                        el.dispatchEvent(new Event('input', {bubbles:true}));
                    } else {
                        el.click();
                    }
                    return true;
                } catch(e) { return false; }
            }''', host_sel, inner_sel, action)

        # Delegated click targets
        if delegated:
            return await page.evaluate('''(s) => {
                try {
                    var el = document.querySelector(s);
                    if (!el) return false;
                    el.click();
                    return true;
                } catch(e) { return false; }
            }''', selector)

        # Standard elements
        loc = page.locator(selector).first

        if action == 'click':
            await loc.click(timeout=3000)
        elif action == 'input':
            await loc.fill('42', timeout=3000)
        elif action == 'select':
            opts = await loc.locator('option').all()
            if len(opts) > 1:
                val = await opts[1].get_attribute('value')
                await loc.select_option(val, timeout=3000)
            else:
                return False
        elif action == 'check':
            if await loc.is_checked():
                await loc.uncheck(timeout=3000)
            else:
                await loc.check(timeout=3000)
        elif action == 'radio':
            await loc.check(timeout=3000)
        elif action == 'range':
            await page.evaluate('''(s) => {
                var el = document.querySelector(s);
                if (!el) return;
                var nv = String((parseFloat(el.max)+parseFloat(el.min))/2 + parseFloat(el.step||1));
                Object.getOwnPropertyDescriptor(
                    HTMLInputElement.prototype, 'value'
                ).set.call(el, nv);
                el.dispatchEvent(new Event('input', {bubbles:true}));
                el.dispatchEvent(new Event('change', {bubbles:true}));
            }''', selector)
        else:
            await loc.click(timeout=3000)
        return True

    except Exception as e:
        print(f'  action failed {selector}: {e}', file=sys.stderr)
        return False


async def probe_page(browser, filepath):
    url = f'file://{filepath}'
    name = Path(filepath).name
    print(f'Probing {name} ...')

    # Discovery pass
    pg = await browser.new_page()
    await pg.add_init_script(INIT_SCRIPT)
    await pg.goto(url)
    await pg.wait_for_load_state('networkidle')
    elements = await pg.evaluate(DISCOVER_SCRIPT)
    await pg.close()
    print(f'  discovered {len(elements)} interactive elements')

    # Test each element in isolation
    results = []
    for i, elem in enumerate(elements):
        pg = await browser.new_page()
        await pg.add_init_script(INIT_SCRIPT)
        await pg.goto(url)
        await pg.wait_for_load_state('networkidle')
        await pg.evaluate(MUTATION_OBSERVER_SCRIPT)
        await pg.evaluate('() => { window.__mu = []; }')

        ok = await perform_action(pg, elem)
        await asyncio.sleep(DEBOUNCE_WAIT_S)
        muts = await pg.evaluate('() => window.__mu || []')

        responsive = ok and len(muts) > 0
        results.append({
            'selector': elem['selector'],
            'tag': elem['tag'],
            'action_type': elem['action_type'],
            'mutations_count': len(muts),
            'responsive': responsive,
        })
        mark = '+' if responsive else '-'
        print(f'  [{i+1}/{len(elements)}] {mark} {elem["selector"]} '
              f'({elem["action_type"]}): {len(muts)} mutations')
        await pg.close()

    total = len(results)
    resp = sum(1 for r in results if r['responsive'])
    ir = round(resp / total, 4) if total > 0 else 0.0

    return {
        'total_interactive': total,
        'responsive': resp,
        'interaction_rate': ir,
        'elements': results,
    }


async def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox',
                  '--disable-gpu', '--disable-dev-shm-usage'],
        )

        report = {'pages': {}}
        for html in sorted(Path(PAGES_DIR).glob('*.html')):
            report['pages'][html.name] = await probe_page(
                browser, str(html.resolve()))

        total = sum(pg['total_interactive'] for pg in report['pages'].values())
        resp = sum(pg['responsive'] for pg in report['pages'].values())
        report['aggregate'] = {
            'total_interactive': total,
            'total_responsive': resp,
            'interaction_rate': round(resp / total, 4) if total > 0 else 0.0,
        }

        out = os.path.join(OUTPUT_DIR, 'report.json')
        with open(out, 'w') as f:
            json.dump(report, f, indent=2)

        print(f'\nReport: {out}')
        print(f'Aggregate: {total} interactive, {resp} responsive, '
              f'IR={report["aggregate"]["interaction_rate"]}')
        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
