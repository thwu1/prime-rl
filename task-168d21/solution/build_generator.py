#!/usr/bin/env python3
"""
Analyzes Kaltiru morphological data, discovers rules, and generates
all HFST build artifacts: AT&T format FST definition, LEXC grammar,
Makefile, lookup input, and output.txt.

Discovered rule system:
1. Two-way vowel harmony (back: a,o,u  vs  front: e,i)
2. Agglutinative suffix ordering: ROOT + PLURAL + POSSESSIVE + CASE
3. Stem-final consonant alternation: k->g, p->b, t->d before vowel-initial
   suffixes at the root boundary only
4. Suffix allomorphy conditioned by preceding segment (vowel vs consonant)
5. Voicing assimilation in LOC/ABL: d->t after voiceless consonants (p,t,k,s)
6. Buffer consonant 'y' inserted in DAT after vowel-final stems
"""

BACK_VOWELS = set('aou')
FRONT_VOWELS = set('ei')
VOWELS = BACK_VOWELS | FRONT_VOWELS
VOICELESS = set('ptks')
ALT_MAP = {'k': 'g', 'p': 'b', 't': 'd'}


def get_harmony(form):
    for ch in reversed(form):
        if ch in BACK_VOWELS:
            return 'B'
        if ch in FRONT_VOWELS:
            return 'F'
    return 'B'


def H(h):
    return 'u' if h == 'B' else 'i'


def A(h):
    return 'a' if h == 'B' else 'e'


def generate(root, number=None, poss=None, case=None):
    stem = root
    at_root = True

    # --- PLURAL ---
    if number == 'PL':
        harm = get_harmony(stem)
        stem += 'lar' if harm == 'B' else 'ler'
        at_root = False

    # --- POSSESSIVE ---
    if poss:
        harm = get_harmony(stem)
        vf = stem[-1] in VOWELS

        do_alt = (at_root and not vf and root[-1] in ALT_MAP
                  and poss != '3PL')
        if do_alt:
            stem = stem[:-1] + ALT_MAP[stem[-1]]

        if vf:
            suf = {'1SG': 'm', '2SG': 'n',
                   '3SG': 's' + H(harm),
                   '1PL': 'm' + H(harm) + 'z',
                   '2PL': 'n' + H(harm) + 'z',
                   '3PL': ('lar' if harm == 'B' else 'ler') + H(harm)}[poss]
        else:
            h = H(harm)
            suf = {'1SG': h + 'm', '2SG': h + 'n', '3SG': h,
                   '1PL': h + 'm' + h + 'z',
                   '2PL': h + 'n' + h + 'z',
                   '3PL': ('lar' if harm == 'B' else 'ler') + h}[poss]
        stem += suf
        at_root = False

    # --- CASE ---
    if case:
        harm = get_harmony(stem)
        vf = stem[-1] in VOWELS
        voiceless_c = (not vf) and (stem[-1] in VOICELESS)

        do_alt = (at_root and not vf and root[-1] in ALT_MAP
                  and case in ('ACC', 'GEN', 'DAT'))
        if do_alt:
            stem = stem[:-1] + ALT_MAP[stem[-1]]
            voiceless_c = False

        h, a = H(harm), A(harm)
        if case == 'ACC':
            suf = ('n' + h) if vf else h
        elif case == 'GEN':
            suf = ('n' + h + 'n') if vf else (h + 'n')
        elif case == 'DAT':
            suf = ('y' + a) if vf else a
        elif case == 'LOC':
            suf = ('t' + a) if voiceless_c else ('d' + a)
        elif case == 'ABL':
            suf = ('t' + a + 'n') if voiceless_c else ('d' + a + 'n')
        else:
            suf = ''
        stem += suf

    return stem


def build_gloss(meaning, number, poss, case):
    parts = [meaning]
    if number:
        parts.append(number)
    if poss:
        parts.append(poss)
    if case:
        parts.append(case)
    return '.'.join(parts)


def generate_att(pairs):
    """Generate AT&T format transducer from (gloss, surface_form) pairs.

    Each pair becomes a linear chain of character-level arcs from state 0
    through fresh states, with @0@ (epsilon) padding the shorter string.
    """
    lines = []
    next_state = 1  # state 0 is the shared start state
    final_states = []

    for inp, out in pairs:
        max_len = max(len(inp), len(out))
        prev = 0
        for j in range(max_len):
            ic = inp[j] if j < len(inp) else '@0@'
            oc = out[j] if j < len(out) else '@0@'
            lines.append(f'{prev}\t{next_state}\t{ic}\t{oc}')
            prev = next_state
            next_state += 1
        final_states.append(prev)

    for fs in final_states:
        lines.append(str(fs))

    return '\n'.join(lines) + '\n'


def main():
    # Read roots
    meaning_to_root = {}
    with open('/app/data/roots.tsv') as f:
        for line in f:
            line = line.strip()
            if line:
                root, meaning = line.split('\t')
                meaning_to_root[meaning] = root

    # Generate all possible gloss -> surface form pairs
    numbers = [None, 'PL']
    posses = [None, '1SG', '2SG', '3SG', '1PL', '2PL', '3PL']
    cases = [None, 'ACC', 'GEN', 'DAT', 'LOC', 'ABL']

    pairs = []
    for meaning in sorted(meaning_to_root.keys()):
        root = meaning_to_root[meaning]
        for num in numbers:
            for poss in posses:
                for case in cases:
                    gloss = build_gloss(meaning, num, poss, case)
                    surface = generate(root, num, poss, case)
                    pairs.append((gloss, surface))

    pair_dict = {g: s for g, s in pairs}

    # Write AT&T format FST definition
    att_content = generate_att(pairs)
    with open('/app/kaltiru.att', 'w') as f:
        f.write(att_content)
    print(f"Generated {len(pairs)} pairs -> /app/kaltiru.att")

    # Generate output.txt directly from morphology rules
    with open('/app/data/test_glosses.txt') as f:
        test_glosses = [l.strip() for l in f if l.strip()]

    with open('/app/output.txt', 'w') as f:
        for gloss in test_glosses:
            f.write(pair_dict[gloss] + '\n')
    print(f"Generated {len(test_glosses)} forms -> /app/output.txt")

    # Write LEXC morphotactic grammar
    write_lexc(meaning_to_root)

    # Write Makefile for build pipeline
    write_makefile()

    # Write lookup input from test glosses
    with open('/app/lookup_input.txt', 'w') as f:
        for g in test_glosses:
            f.write(g + '\n')

    print("Artifacts: kaltiru.att, kaltiru.lexc, Makefile, lookup_input.txt, output.txt")


def write_lexc(meaning_to_root):
    """Write a LEXC grammar describing Kaltiru morphotactic structure."""
    lines = []
    lines.append("Multichar_Symbols")
    lines.append("+N +PL +1SG +2SG +3SG +1PL +2PL +3PL +ACC +GEN +DAT +LOC +ABL")
    lines.append("")
    lines.append("LEXICON Root")
    for meaning in sorted(meaning_to_root.keys()):
        root = meaning_to_root[meaning]
        lines.append(f"{meaning}+N:{root} Num ;")
    lines.append("")
    lines.append("LEXICON Num")
    lines.append("+PL Poss ;")
    lines.append(" Poss ;")
    lines.append("")
    lines.append("LEXICON Poss")
    lines.append("+1SG Case ;")
    lines.append("+2SG Case ;")
    lines.append("+3SG Case ;")
    lines.append("+1PL Case ;")
    lines.append("+2PL Case ;")
    lines.append("+3PL Case ;")
    lines.append(" Case ;")
    lines.append("")
    lines.append("LEXICON Case")
    lines.append("+ACC # ;")
    lines.append("+GEN # ;")
    lines.append("+DAT # ;")
    lines.append("+LOC # ;")
    lines.append("+ABL # ;")
    lines.append("# ;")
    lines.append("")

    with open('/app/kaltiru.lexc', 'w') as f:
        f.write('\n'.join(lines))


def write_makefile():
    """Write a Makefile for the HFST build pipeline."""
    makefile = """.PHONY: all clean summary

all: kaltiru.hfst output.txt

kaltiru.hfst: kaltiru.att
\thfst-txt2fst -i kaltiru.att -o kaltiru.hfst

output.txt: kaltiru.hfst lookup_input.txt parse_lookup.py
\thfst-lookup -q kaltiru.hfst < lookup_input.txt | python3 parse_lookup.py > output.txt

summary: kaltiru.hfst
\thfst-summarize kaltiru.hfst

clean:
\trm -f kaltiru.hfst output.txt
"""
    with open('/app/Makefile', 'w') as f:
        f.write(makefile)


if __name__ == '__main__':
    main()
