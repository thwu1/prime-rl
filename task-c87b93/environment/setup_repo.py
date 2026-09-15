#!/usr/bin/env python3
"""Set up git repository with commit history for the CSS cascade resolver."""

import subprocess
import os

os.chdir('/app')

subprocess.run(['git', 'init'], check=True, capture_output=True)
subprocess.run(['git', 'config', 'user.email', 'dev@example.com'], check=True, capture_output=True)
subprocess.run(['git', 'config', 'user.name', 'CSS Developer'], check=True, capture_output=True)

# Read current (buggy) file contents
with open('specificity.py', 'r') as f:
    spec_buggy = f.read()
with open('matcher.py', 'r') as f:
    match_buggy = f.read()
with open('resolver.py', 'r') as f:
    res_buggy = f.read()

# Create corrected versions for initial commit
spec_correct = spec_buggy.replace(
    '        return max_specificity_of_selector_list(simple.selectors)  # same as :is()',
    '        # :where() always contributes zero specificity\n        return (0, 0, 0)'
)

match_correct = match_buggy.replace(
    '''        elif combinator == "+":
            # Adjacent sibling: find matching preceding sibling
            found = False
            for sib in current_node.preceding_siblings():
                if matches_compound(sib, compound):
                    current_node = sib
                    found = True
                    break
            if not found:
                return False''',
    '''        elif combinator == "+":
            # Adjacent sibling: immediately preceding sibling must match
            sib = current_node.immediately_preceding_sibling()
            if sib is None or not matches_compound(sib, compound):
                return False
            current_node = sib'''
)

res_correct = res_buggy.replace(
    'entries.sort(key=lambda e: (-e[0], e[1], e[2], e[3]))',
    'entries.sort(key=lambda e: (e[0], e[1], e[2], e[3]))'
)

# Write correct versions and commit
with open('specificity.py', 'w') as f:
    f.write(spec_correct)
with open('matcher.py', 'w') as f:
    f.write(match_correct)
with open('resolver.py', 'w') as f:
    f.write(res_correct)

subprocess.run(['git', 'add', '.'], check=True, capture_output=True)
subprocess.run([
    'git', 'commit', '-m',
    'Initial modular CSS cascade resolver implementation\n\n'
    'Complete CSS Selectors Level 4 cascade resolution with:\n'
    '- Type, class, ID, attribute selectors\n'
    '- :is(), :not(), :where(), :has() pseudo-classes\n'
    '- Descendant, child, adjacent sibling, general sibling combinators\n'
    '- !important support and full cascade ordering'
], check=True, capture_output=True)

# Restore buggy versions and commit
with open('specificity.py', 'w') as f:
    f.write(spec_buggy)
with open('matcher.py', 'w') as f:
    f.write(match_buggy)
with open('resolver.py', 'w') as f:
    f.write(res_buggy)

subprocess.run(['git', 'add', '.'], check=True, capture_output=True)
subprocess.run([
    'git', 'commit', '-m',
    'Optimize and simplify cascade internals\n\n'
    '- Unified pseudo-class specificity computation for consistency\n'
    '- Simplified combinator matching to reduce code duplication\n'
    '- Streamlined cascade sort for more intuitive priority ordering'
], check=True, capture_output=True)
