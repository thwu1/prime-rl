#!/usr/bin/env python3
"""
Kaltiru morphological generator.

Implements the complete morphophonological rule system discovered from training data:
1. Two-way vowel harmony (back: a,o,u  vs  front: e,i)
2. Agglutinative suffix ordering: ROOT + PLURAL + POSSESSIVE + CASE
3. Stem-final consonant alternation: k->g, p->b, t->d before vowel-initial suffixes
   (only at root boundary, not after other suffixes)
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
        vf = stem[-1] in VOWELS  # vowel-final

        # Alternation check: only at root boundary, C-final, and V-initial suffix
        do_alt = (at_root and not vf and root[-1] in ALT_MAP
                  and poss != '3PL')  # 3PL starts with C (l)
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
        voiceless = (not vf) and (stem[-1] in VOICELESS)

        # Alternation: only at root boundary for ACC/GEN/DAT (vowel-initial after C)
        do_alt = (at_root and not vf and root[-1] in ALT_MAP
                  and case in ('ACC', 'GEN', 'DAT'))
        if do_alt:
            stem = stem[:-1] + ALT_MAP[stem[-1]]
            voiceless = False

        h, a = H(harm), A(harm)
        if case == 'ACC':
            suf = ('n' + h) if vf else h
        elif case == 'GEN':
            suf = ('n' + h + 'n') if vf else (h + 'n')
        elif case == 'DAT':
            suf = ('y' + a) if vf else a
        elif case == 'LOC':
            suf = ('t' + a) if voiceless else ('d' + a)
        elif case == 'ABL':
            suf = ('t' + a + 'n') if voiceless else ('d' + a + 'n')
        else:
            suf = ''
        stem += suf

    return stem


def parse_gloss(gloss, meaning_to_root):
    parts = gloss.split('.')
    meaning = parts[0]
    root = meaning_to_root[meaning]

    number = None
    poss = None
    case = None

    for p in parts[1:]:
        if p == 'PL':
            number = 'PL'
        elif p in ('1SG', '2SG', '3SG', '1PL', '2PL', '3PL'):
            poss = p
        elif p in ('ACC', 'GEN', 'DAT', 'LOC', 'ABL'):
            case = p

    return root, number, poss, case


def main():
    # Load roots
    meaning_to_root = {}
    with open('/app/data/roots.tsv') as f:
        for line in f:
            line = line.strip()
            if line:
                root, meaning = line.split('\t')
                meaning_to_root[meaning] = root

    # Read test glosses
    with open('/app/data/test_glosses.txt') as f:
        glosses = [line.strip() for line in f if line.strip()]

    # Generate forms
    results = []
    for gloss in glosses:
        root, number, poss, case = parse_gloss(gloss, meaning_to_root)
        form = generate(root, number, poss, case)
        results.append(form)

    # Write output
    with open('/app/output.txt', 'w') as f:
        for form in results:
            f.write(form + '\n')

    print(f"Generated {len(results)} forms -> /app/output.txt")


if __name__ == '__main__':
    main()
