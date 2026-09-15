#!/usr/bin/env python3
"""
CAVP CTR_DRBG Validation Runner

Parses NIST CAVS 14.3 raw test vector files and validates the CTR_DRBG
implementation at /app/ctr_drbg.py against them.

Usage:
    python3 /app/validate.py                    # Run all configurations
    python3 /app/validate.py --config df_basic  # Run specific config
    python3 /app/validate.py --verbose          # Show first failure details
"""

import argparse
import re
import sys

sys.path.insert(0, "/app")


def parse_cavp_txt(filepath):
    """Parse a CAVS 14.3 CTR_DRBG .txt file with intermediate states.

    Returns a list of configuration groups, each containing:
    - header: dict of configuration parameters
    - vectors: list of test vector dicts with intermediate Key/V values
    """
    with open(filepath) as f:
        content = f.read()

    groups = []
    # Split by section headers [AES-256 ...]
    section_pattern = re.compile(
        r'(\[AES-256 (?:use|no) df\].*?)(?=\[AES-256 |\Z)',
        re.DOTALL
    )

    for match in section_pattern.finditer(content):
        section = match.group(1)
        lines = section.strip().split('\n')

        # Parse header
        header = {}
        i = 0
        while i < len(lines) and not lines[i].startswith('COUNT'):
            line = lines[i].strip()
            m = re.match(r'\[(.+?)\]', line)
            if m:
                kv = m.group(1)
                if '=' in kv:
                    k, v = kv.split('=', 1)
                    header[k.strip()] = v.strip()
                else:
                    header['algorithm'] = kv
            i += 1

        # Parse test vectors
        vectors = []
        current = {}
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('COUNT'):
                if current:
                    vectors.append(current)
                current = {'count': int(line.split('=')[1].strip())}
            elif '=' in line and not line.startswith('**') and not line.startswith('#'):
                k, v = line.split('=', 1)
                k = k.strip()
                v = v.strip()
                # Handle Key and V lines (indented, part of state output)
                current[k] = v
            elif line.startswith('Key') or line.startswith('V'):
                # Intermediate state from ** blocks
                k, v = line.split('=', 1)
                current[f'_state_{k.strip()}'] = v.strip()
            i += 1
        if current:
            vectors.append(current)

        groups.append({'header': header, 'vectors': vectors})

    return groups


def run_validation(config_filter=None, verbose=False):
    """Run CAVP validation and report results."""
    try:
        from ctr_drbg import CTR_DRBG
    except ImportError:
        print("ERROR: Cannot import CTR_DRBG from /app/ctr_drbg.py")
        return False

    raw_file = "/app/cavp_vectors/cavp_aes256_intermediate.txt"
    try:
        groups = parse_cavp_txt(raw_file)
    except FileNotFoundError:
        print(f"ERROR: CAVP vector file not found: {raw_file}")
        return False

    configs = {
        'df_basic': {'use_df': True, 'pers': False, 'ai': False, 'reseed': False},
        'df_addl': {'use_df': True, 'pers': False, 'ai': True, 'reseed': False},
        'df_pers': {'use_df': True, 'pers': True, 'ai': False, 'reseed': False},
        'nodf_basic': {'use_df': False, 'pers': False, 'ai': False, 'reseed': False},
        'df_reseed': {'use_df': True, 'pers': False, 'ai': False, 'reseed': True},
    }

    total_pass = 0
    total_fail = 0
    results = {}

    for gidx, group in enumerate(groups):
        h = group['header']
        use_df = 'use df' in h.get('algorithm', '')
        has_reseed = any('EntropyInputReseed' in v for v in group['vectors'])
        pers_len = int(h.get('PersonalizationStringLen', 0))
        ai_len = int(h.get('AdditionalInputLen', 0))

        # Determine config name
        if use_df and pers_len == 0 and ai_len == 0 and not has_reseed:
            cfg_name = 'df_basic'
        elif use_df and pers_len == 0 and ai_len > 0 and not has_reseed:
            cfg_name = 'df_addl'
        elif use_df and pers_len > 0 and ai_len == 0 and not has_reseed:
            cfg_name = 'df_pers'
        elif not use_df and pers_len == 0 and ai_len == 0:
            cfg_name = 'nodf_basic'
        elif use_df and has_reseed:
            cfg_name = 'df_reseed'
        else:
            continue

        if config_filter and cfg_name != config_filter:
            continue

        g_pass = 0
        g_fail = 0

        for tv in group['vectors']:
            try:
                drbg = CTR_DRBG(use_df=use_df)
                entropy = bytes.fromhex(tv.get('EntropyInput', ''))
                nonce = bytes.fromhex(tv.get('Nonce', '')) if tv.get('Nonce') else b''
                pers = bytes.fromhex(tv.get('PersonalizationString', '')) if tv.get('PersonalizationString') else b''

                drbg.instantiate(entropy, nonce, pers)

                if has_reseed and 'EntropyInputReseed' in tv:
                    re_ent = bytes.fromhex(tv['EntropyInputReseed'])
                    re_ai = bytes.fromhex(tv.get('AdditionalInputReseed', '')) if tv.get('AdditionalInputReseed') else b''
                    drbg.reseed(re_ent, re_ai)

                # Get additional inputs
                ai_keys = [k for k in tv if k.startswith('AdditionalInput') and k not in ('AdditionalInputReseed',)]
                ai_vals = []
                for k in sorted(ai_keys):
                    if k == 'AdditionalInput':
                        ai_vals.append(tv[k])

                rbits_len = int(h.get('ReturnedBitsLen', 512))

                # First generate
                ai1 = bytes.fromhex(ai_vals[0]) if len(ai_vals) > 0 and ai_vals[0] else b''
                drbg.generate(rbits_len, ai1)

                # Second generate
                ai2 = bytes.fromhex(ai_vals[1]) if len(ai_vals) > 1 and ai_vals[1] else b''
                result = drbg.generate(rbits_len, ai2)

                expected = tv.get('ReturnedBits', '')
                if result.hex() == expected:
                    g_pass += 1
                else:
                    g_fail += 1
                    if verbose and g_fail == 1:
                        print(f"  FAIL detail (COUNT={tv['count']}):")
                        print(f"    Expected: {expected[:32]}...")
                        print(f"    Got:      {result.hex()[:32]}...")
            except Exception as e:
                g_fail += 1
                if verbose and g_fail == 1:
                    print(f"  EXCEPTION (COUNT={tv.get('count', '?')}): {e}")

        total_pass += g_pass
        total_fail += g_fail
        status = "PASS" if g_fail == 0 else "FAIL"
        results[cfg_name] = status
        print(f"[{status}] {cfg_name}: {g_pass}/{g_pass + g_fail} vectors passed")

    print(f"\nTotal: {total_pass}/{total_pass + total_fail} vectors passed")
    return total_fail == 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='CAVP CTR_DRBG Validator')
    parser.add_argument('--config', help='Run specific configuration only')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show failure details')
    args = parser.parse_args()

    success = run_validation(config_filter=args.config, verbose=args.verbose)
    sys.exit(0 if success else 1)
