#!/usr/bin/env python3
"""Run the CSS cascade engine and output computed styles as JSON.

"""

import json

from engine.compute import compute_styles, load_dom, load_rules, load_properties


def main():
    dom = load_dom("/app/dom.json")
    rules = load_rules("/app/rules.json")
    props = load_properties("/app/properties.json")

    styles = compute_styles(dom, rules, props)

    output = {}
    for k in sorted(styles.keys()):
        output[str(k)] = dict(sorted(styles[k].items()))
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
