#!/bin/bash
set -e
mkdir -p /app/output
python3 -c "
import sys
sys.path.insert(0, '/app')
from pcky import Grammar, parse_sentence, tree_to_dot
g = Grammar.from_file(sys.argv[1])
result = parse_sentence(g, sys.argv[2])
if result['best_parse']:
    dot = tree_to_dot(result['best_parse'])
    with open('/app/output/tree.dot', 'w') as f:
        f.write(dot)
else:
    print('Sentence not accepted by grammar', file=sys.stderr)
    sys.exit(1)
" "$1" "$2"
dot -Tsvg /app/output/tree.dot -o /app/output/tree.svg
