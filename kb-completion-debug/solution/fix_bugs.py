"""
Fix two bugs in the Knuth-Bendix completion framework.

Bug 1 (ordering.py): Precedence values for inv and mul are swapped.
Bug 2 (rewriting.py): normalize() applies only one rewrite step instead
       of iterating to a fixed point.

(Bug 3 in completion.py is handled by replacing the whole file.)

"""


def fix_ordering():
    with open('/app/ordering.py', 'r') as f:
        content = f.read()
    content = content.replace("'mul': 2,", "'mul': 1,")
    content = content.replace("'inv': 1,", "'inv': 2,")
    with open('/app/ordering.py', 'w') as f:
        f.write(content)
    print("  Fixed ordering.py: inv precedence (2) now higher than mul (1)")


def fix_rewriting():
    with open('/app/rewriting.py', 'r') as f:
        content = f.read()

    old = """    result = rewrite_step(t, rules)
    if result is not None:
        return result
    return t"""

    new = """    while True:
        result = rewrite_step(t, rules)
        if result is None:
            return t
        t = result"""

    content = content.replace(old, new)
    with open('/app/rewriting.py', 'w') as f:
        f.write(content)
    print("  Fixed rewriting.py: normalize now iterates to fixed point")


if __name__ == '__main__':
    print("Applying bug fixes:")
    fix_ordering()
    fix_rewriting()
    print("  Bug fixes applied.")
