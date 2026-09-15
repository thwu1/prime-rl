#!/usr/bin/env python3
"""Inject per-instance challenge parameters into the NDP dissector source.

Randomizes buffer sizes and generates a unique challenge token to ensure
each task instance requires fresh source code analysis.
"""

import random
import json
import re


def main():
    seed = random.randint(0, 2**32 - 1)
    rng = random.Random(seed)

    # Randomize the IDENT interface name buffer size
    ident_name_buf = rng.choice([80, 96, 112, 144, 160, 176, 208])

    # Generate unique per-instance challenge token (24 hex chars)
    challenge_token = ''.join(rng.choices('0123456789abcdef', k=24))

    # Read and modify ndp.h
    with open('src/ndp.h', 'r') as f:
        content = f.read()

    # Replace IDENT_NAME_BUF with randomized value
    content = re.sub(
        r'#define IDENT_NAME_BUF\s+\d+',
        '#define IDENT_NAME_BUF    %d' % ident_name_buf,
        content
    )

    # Insert CHALLENGE_TOKEN define before the closing #endif
    content = content.replace(
        '#endif /* NDP_H */',
        '/* Per-instance challenge identifier */\n'
        '#define CHALLENGE_TOKEN   "%s"\n\n'
        '#endif /* NDP_H */' % challenge_token
    )

    with open('src/ndp.h', 'w') as f:
        f.write(content)

    # Save challenge configuration for verification and solution use
    config = {
        'seed': seed,
        'ident_name_buf': ident_name_buf,
        'challenge_token': challenge_token,
    }
    with open('.challenge.json', 'w') as f:
        json.dump(config, f, indent=2)

    print('Challenge configured: IDENT_NAME_BUF=%d, token=%s' % (
        ident_name_buf, challenge_token))


if __name__ == '__main__':
    main()
