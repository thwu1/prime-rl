"""CSS cascade resolver — main entry point."""

import json
import sys

from dom import build_dom
from parser import parse_css
from resolver import resolve_cascade


def main():
    if len(sys.argv) < 3:
        print("Usage: cascade.py <dom.json> <styles.css>", file=sys.stderr)
        sys.exit(1)

    dom_path = sys.argv[1]
    css_path = sys.argv[2]

    with open(dom_path) as f:
        dom_data = json.load(f)
    with open(css_path) as f:
        css_text = f.read()

    dom_root = build_dom(dom_data)
    rules = parse_css(css_text)
    result = resolve_cascade(dom_root, rules)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
