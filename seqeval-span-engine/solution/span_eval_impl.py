#!/usr/bin/env python3

"""Sequence labeling evaluation engine supporting 6 NER tagging schemes."""

import enum
import json
import sys
from collections import defaultdict


# ---------------------------------------------------------------------------
# Prefix & Tag-condition enums (mirrors seqeval's scheme.py design)
# ---------------------------------------------------------------------------

class Prefix(enum.Flag):
    I = enum.auto()
    O = enum.auto()
    B = enum.auto()
    E = enum.auto()
    S = enum.auto()
    U = enum.auto()
    L = enum.auto()
    ANY = I | O | B | E | S | U | L


class TagCond(enum.Flag):
    SAME = enum.auto()
    DIFF = enum.auto()
    ANY = SAME | DIFF


_PREFIX_MAP = {}
for _m in Prefix:
    if _m.name != 'ANY':
        _PREFIX_MAP[_m.name] = _m


# ---------------------------------------------------------------------------
# Scheme definitions: start / inside / end transition patterns
# ---------------------------------------------------------------------------

SCHEMES = {
    'IOB1': {
        'allowed': Prefix.I | Prefix.O | Prefix.B,
        'start': frozenset({
            (Prefix.O, Prefix.I, TagCond.ANY),
            (Prefix.I, Prefix.I, TagCond.DIFF),
            (Prefix.B, Prefix.I, TagCond.ANY),
            (Prefix.I, Prefix.B, TagCond.SAME),
            (Prefix.B, Prefix.B, TagCond.SAME),
        }),
        'inside': frozenset({
            (Prefix.B, Prefix.I, TagCond.SAME),
            (Prefix.I, Prefix.I, TagCond.SAME),
        }),
        'end': frozenset({
            (Prefix.I, Prefix.I, TagCond.DIFF),
            (Prefix.I, Prefix.O, TagCond.ANY),
            (Prefix.I, Prefix.B, TagCond.ANY),
            (Prefix.B, Prefix.O, TagCond.ANY),
            (Prefix.B, Prefix.I, TagCond.DIFF),
            (Prefix.B, Prefix.B, TagCond.SAME),
        }),
    },
    'IOB2': {
        'allowed': Prefix.I | Prefix.O | Prefix.B,
        'start': frozenset({(Prefix.ANY, Prefix.B, TagCond.ANY)}),
        'inside': frozenset({
            (Prefix.B, Prefix.I, TagCond.SAME),
            (Prefix.I, Prefix.I, TagCond.SAME),
        }),
        'end': frozenset({
            (Prefix.I, Prefix.O, TagCond.ANY),
            (Prefix.I, Prefix.I, TagCond.DIFF),
            (Prefix.I, Prefix.B, TagCond.ANY),
            (Prefix.B, Prefix.O, TagCond.ANY),
            (Prefix.B, Prefix.I, TagCond.DIFF),
            (Prefix.B, Prefix.B, TagCond.ANY),
        }),
    },
    'IOE1': {
        'allowed': Prefix.I | Prefix.O | Prefix.E,
        'start': frozenset({
            (Prefix.O, Prefix.I, TagCond.ANY),
            (Prefix.I, Prefix.I, TagCond.DIFF),
            (Prefix.E, Prefix.I, TagCond.ANY),
            (Prefix.E, Prefix.E, TagCond.SAME),
        }),
        'inside': frozenset({
            (Prefix.I, Prefix.I, TagCond.SAME),
            (Prefix.I, Prefix.E, TagCond.SAME),
        }),
        'end': frozenset({
            (Prefix.I, Prefix.I, TagCond.DIFF),
            (Prefix.I, Prefix.O, TagCond.ANY),
            (Prefix.I, Prefix.E, TagCond.DIFF),
            (Prefix.E, Prefix.I, TagCond.SAME),
            (Prefix.E, Prefix.E, TagCond.SAME),
        }),
    },
    'IOE2': {
        'allowed': Prefix.I | Prefix.O | Prefix.E,
        'start': frozenset({
            (Prefix.O, Prefix.I, TagCond.ANY),
            (Prefix.O, Prefix.E, TagCond.ANY),
            (Prefix.E, Prefix.I, TagCond.ANY),
            (Prefix.E, Prefix.E, TagCond.ANY),
            (Prefix.I, Prefix.I, TagCond.DIFF),
            (Prefix.I, Prefix.E, TagCond.DIFF),
        }),
        'inside': frozenset({
            (Prefix.I, Prefix.E, TagCond.SAME),
            (Prefix.I, Prefix.I, TagCond.SAME),
        }),
        'end': frozenset({(Prefix.E, Prefix.ANY, TagCond.ANY)}),
    },
    'IOBES': {
        'allowed': Prefix.I | Prefix.O | Prefix.B | Prefix.E | Prefix.S,
        'start': frozenset({
            (Prefix.ANY, Prefix.B, TagCond.ANY),
            (Prefix.ANY, Prefix.S, TagCond.ANY),
        }),
        'inside': frozenset({
            (Prefix.B, Prefix.I, TagCond.SAME),
            (Prefix.B, Prefix.E, TagCond.SAME),
            (Prefix.I, Prefix.I, TagCond.SAME),
            (Prefix.I, Prefix.E, TagCond.SAME),
        }),
        'end': frozenset({
            (Prefix.S, Prefix.ANY, TagCond.ANY),
            (Prefix.E, Prefix.ANY, TagCond.ANY),
        }),
    },
    'BILOU': {
        'allowed': Prefix.B | Prefix.I | Prefix.L | Prefix.O | Prefix.U,
        'start': frozenset({
            (Prefix.ANY, Prefix.B, TagCond.ANY),
            (Prefix.ANY, Prefix.U, TagCond.ANY),
        }),
        'inside': frozenset({
            (Prefix.B, Prefix.I, TagCond.SAME),
            (Prefix.B, Prefix.L, TagCond.SAME),
            (Prefix.I, Prefix.I, TagCond.SAME),
            (Prefix.I, Prefix.L, TagCond.SAME),
        }),
        'end': frozenset({
            (Prefix.U, Prefix.ANY, TagCond.ANY),
            (Prefix.L, Prefix.ANY, TagCond.ANY),
        }),
    },
}


# ---------------------------------------------------------------------------
# Tag parsing
# ---------------------------------------------------------------------------

def parse_tag(token_str, suffix=False, delimiter='-'):
    """Parse token string -> (Prefix, entity_type).

    Matches seqeval's Token.__init__ exactly:
      prefix = first char (or last if suffix)
      tag = remaining chars, stripped of delimiter, or '_' if empty
    """
    prefix_char = token_str[-1] if suffix else token_str[0]
    try:
        prefix = _PREFIX_MAP[prefix_char]
    except KeyError:
        raise ValueError(f'Invalid token is found: {token_str}')
    tag_raw = token_str[:-1] if suffix else token_str[1:]
    tag = tag_raw.strip(delimiter) or '_'
    return prefix, tag


# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------

def _match_tag_cond(prev_tag, cur_tag, cond):
    if TagCond.SAME in cond and TagCond.DIFF in cond:
        return True  # ANY
    if TagCond.SAME in cond and prev_tag == cur_tag:
        return True
    if TagCond.DIFF in cond and prev_tag != cur_tag:
        return True
    return False


def _match_patterns(prev_p, prev_tag, cur_p, cur_tag, patterns):
    for pp, cp, tc in patterns:
        if prev_p in pp and cur_p in cp and _match_tag_cond(prev_tag, cur_tag, tc):
            return True
    return False


# ---------------------------------------------------------------------------
# Strict-mode entity extraction (scheme-specific FSM)
# ---------------------------------------------------------------------------

def extract_entities_strict(tags, scheme_name, suffix=False, delimiter='-',
                            sent_id=0):
    """Extract entities using scheme-specific FSM.

    Returns list of (entity_type, sent_id, start, end_exclusive).
    """
    scheme = SCHEMES[scheme_name]
    allowed = scheme['allowed']
    start_pats = scheme['start']
    inside_pats = scheme['inside']
    end_pats = scheme['end']

    # Parse and validate all tokens
    parsed = []
    for t in tags:
        p, tag = parse_tag(t, suffix, delimiter)
        if p not in allowed:
            raise ValueError(
                f'Invalid token is found: {t}. '
                f'Allowed prefixes are: {allowed}.'
            )
        parsed.append((p, tag))

    # Append outside sentinel
    outside = (Prefix.O, '_')
    extended = parsed + [outside]

    entities = []
    i = 0
    prev_p, prev_tag = outside

    while i < len(extended):
        cur_p, cur_tag = extended[i]

        if _match_patterns(prev_p, prev_tag, cur_p, cur_tag, start_pats):
            # Forward-scan for inside tokens
            end = i + 1
            fp, ft = cur_p, cur_tag
            exhausted = True
            while end < len(extended):
                np_, nt = extended[end]
                if _match_patterns(fp, ft, np_, nt, inside_pats):
                    fp, ft = np_, nt
                    end += 1
                else:
                    exhausted = False
                    break

            if exhausted:
                # Fallback (shouldn't happen with O sentinel)
                end = max(len(parsed) - 1, i + 1)

            # Check end-of-entity condition
            if end < len(extended):
                ep, et = extended[end]
                pp, pt = extended[end - 1]
                if _match_patterns(pp, pt, ep, et, end_pats):
                    entities.append((cur_tag, sent_id, i, end))

            i = end
        else:
            i += 1

        prev_p, prev_tag = extended[i - 1]

    return entities


# ---------------------------------------------------------------------------
# Default-mode entity extraction (conlleval.pl-compatible)
# ---------------------------------------------------------------------------

def _end_of_chunk(prev_tag, tag, prev_type, type_):
    chunk_end = False
    if prev_tag == 'E':
        chunk_end = True
    if prev_tag == 'S':
        chunk_end = True
    if prev_tag == 'B' and tag == 'B':
        chunk_end = True
    if prev_tag == 'B' and tag == 'S':
        chunk_end = True
    if prev_tag == 'B' and tag == 'O':
        chunk_end = True
    if prev_tag == 'I' and tag == 'B':
        chunk_end = True
    if prev_tag == 'I' and tag == 'S':
        chunk_end = True
    if prev_tag == 'I' and tag == 'O':
        chunk_end = True
    if prev_tag != 'O' and prev_tag != '.' and prev_type != type_:
        chunk_end = True
    return chunk_end


def _start_of_chunk(prev_tag, tag, prev_type, type_):
    chunk_start = False
    if tag == 'B':
        chunk_start = True
    if tag == 'S':
        chunk_start = True
    if prev_tag == 'E' and tag == 'E':
        chunk_start = True
    if prev_tag == 'E' and tag == 'I':
        chunk_start = True
    if prev_tag == 'S' and tag == 'E':
        chunk_start = True
    if prev_tag == 'S' and tag == 'I':
        chunk_start = True
    if prev_tag == 'O' and tag == 'E':
        chunk_start = True
    if prev_tag == 'O' and tag == 'I':
        chunk_start = True
    if tag != 'O' and tag != '.' and prev_type != type_:
        chunk_start = True
    return chunk_start


def extract_entities_default(tags, suffix=False, delimiter='-', sent_id=0):
    """Extract entities using conlleval.pl-compatible logic.

    Returns list of (entity_type, sent_id, start, end_exclusive).
    """
    prev_tag = 'O'
    prev_type = ''
    begin_offset = 0
    entities = []

    for i, chunk in enumerate(list(tags) + ['O']):
        if suffix:
            tag = chunk[-1]
            type_ = chunk[:-1].rsplit(delimiter, maxsplit=1)[0] or '_'
        else:
            tag = chunk[0]
            type_ = chunk[1:].split(delimiter, maxsplit=1)[-1] or '_'

        if _end_of_chunk(prev_tag, tag, prev_type, type_):
            entities.append((prev_type, sent_id, begin_offset, i))
        if _start_of_chunk(prev_tag, tag, prev_type, type_):
            begin_offset = i

        prev_tag = tag
        prev_type = type_

    return entities


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------

def auto_detect_scheme(sequences, suffix=False, delimiter='-'):
    """Detect tagging scheme from observed prefix set."""
    prefixes = set()
    for tags in sequences:
        for t in tags:
            try:
                p, _ = parse_tag(t, suffix, delimiter)
                prefixes.add(p)
            except (KeyError, ValueError):
                raise ValueError(f'This scheme is not supported: {t}')

    iob2_sets = [
        {Prefix.I, Prefix.O, Prefix.B},
        {Prefix.I, Prefix.B},
        {Prefix.B, Prefix.O},
        {Prefix.B},
    ]
    ioe2_sets = [
        {Prefix.I, Prefix.O, Prefix.E},
        {Prefix.I, Prefix.E},
        {Prefix.E, Prefix.O},
        {Prefix.E},
    ]
    iobes_sets = [
        {Prefix.I, Prefix.O, Prefix.B, Prefix.E, Prefix.S},
        {Prefix.I, Prefix.B, Prefix.E, Prefix.S},
        {Prefix.I, Prefix.O, Prefix.B, Prefix.E},
        {Prefix.O, Prefix.B, Prefix.E, Prefix.S},
        {Prefix.I, Prefix.B, Prefix.E},
        {Prefix.B, Prefix.E, Prefix.S},
        {Prefix.O, Prefix.B, Prefix.E},
        {Prefix.B, Prefix.E},
        {Prefix.S},
    ]
    bilou_sets = [
        {Prefix.I, Prefix.O, Prefix.B, Prefix.L, Prefix.U},
        {Prefix.I, Prefix.B, Prefix.L, Prefix.U},
        {Prefix.I, Prefix.O, Prefix.B, Prefix.L},
        {Prefix.O, Prefix.B, Prefix.L, Prefix.U},
        {Prefix.I, Prefix.B, Prefix.L},
        {Prefix.B, Prefix.L, Prefix.U},
        {Prefix.O, Prefix.B, Prefix.L},
        {Prefix.B, Prefix.L},
        {Prefix.U},
    ]

    if prefixes in iob2_sets:
        return 'IOB2'
    elif prefixes in ioe2_sets:
        return 'IOE2'
    elif prefixes in iobes_sets:
        return 'IOBES'
    elif prefixes in bilou_sets:
        return 'BILOU'
    else:
        raise ValueError(f'This scheme is not supported: {prefixes}')


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def compute_metrics(entities_true, entities_pred):
    """Compute precision, recall, F1 from entity lists.

    Each entity is (type, sent_id, start, end_exclusive).
    """
    true_by_type = defaultdict(set)
    pred_by_type = defaultdict(set)

    for tag, sid, start, end in entities_true:
        true_by_type[tag].add((sid, start, end))
    for tag, sid, start, end in entities_pred:
        pred_by_type[tag].add((sid, start, end))

    all_types = sorted(set(true_by_type.keys()) | set(pred_by_type.keys()))

    per_type = {}
    precisions = []
    recalls = []
    f1s = []
    supports = []

    for t in all_types:
        ts = true_by_type.get(t, set())
        ps = pred_by_type.get(t, set())
        tp = len(ts & ps)

        p = tp / len(ps) if ps else 0.0
        r = tp / len(ts) if ts else 0.0
        f = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        s = len(ts)

        per_type[t] = {'precision': p, 'recall': r, 'f1': f, 'support': s}
        precisions.append(p)
        recalls.append(r)
        f1s.append(f)
        supports.append(s)

    total_support = sum(supports)

    # Micro average
    total_tp = sum(
        len(true_by_type.get(t, set()) & pred_by_type.get(t, set()))
        for t in all_types
    )
    total_pred = sum(len(pred_by_type.get(t, set())) for t in all_types)
    total_true = sum(len(true_by_type.get(t, set())) for t in all_types)

    micro_p = total_tp / total_pred if total_pred else 0.0
    micro_r = total_tp / total_true if total_true else 0.0
    micro_f = (2 * micro_p * micro_r / (micro_p + micro_r)
               if (micro_p + micro_r) > 0 else 0.0)

    # Macro average
    n = len(all_types) or 1
    macro_p = sum(precisions) / n
    macro_r = sum(recalls) / n
    macro_f = sum(f1s) / n

    # Weighted average
    if total_support > 0:
        w_p = sum(p * s for p, s in zip(precisions, supports)) / total_support
        w_r = sum(r * s for r, s in zip(recalls, supports)) / total_support
        w_f = sum(f * s for f, s in zip(f1s, supports)) / total_support
    else:
        w_p = w_r = w_f = 0.0

    return {
        'per_type': per_type,
        'micro_avg': {
            'precision': micro_p, 'recall': micro_r,
            'f1': micro_f, 'support': total_support,
        },
        'macro_avg': {
            'precision': macro_p, 'recall': macro_r,
            'f1': macro_f, 'support': total_support,
        },
        'weighted_avg': {
            'precision': w_p, 'recall': w_r,
            'f1': w_f, 'support': total_support,
        },
    }


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def entities_to_dict(entity_list):
    """Convert [(type, sid, start, end), ...] -> {type: [[sid, start, end], ...]}."""
    result = defaultdict(list)
    for tag, sid, start, end in entity_list:
        result[tag].append([sid, start, end])
    for k in result:
        result[k].sort()
    return dict(result)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    input_path = sys.argv[1]
    with open(input_path) as f:
        config = json.load(f)

    y_true = config['y_true']
    y_pred = config['y_pred']
    scheme = config.get('scheme', 'auto')
    mode = config.get('mode', 'default')
    suffix = config.get('suffix', False)
    delimiter = config.get('delimiter', '-')

    # Validate sequence lengths
    if len(y_true) != len(y_pred):
        raise ValueError(
            f'Found input variables with inconsistent numbers of samples: '
            f'{[len(s) for s in y_true]} vs {[len(s) for s in y_pred]}'
        )
    for i, (t, p) in enumerate(zip(y_true, y_pred)):
        if len(t) != len(p):
            raise ValueError(
                f'Found input variables with inconsistent numbers of samples: '
                f'{[len(s) for s in y_true]} vs {[len(s) for s in y_pred]}'
            )

    result = {}

    # Auto-detect scheme if requested
    if scheme == 'auto':
        detected = auto_detect_scheme(y_true, suffix, delimiter)
        result['detected_scheme'] = detected
        scheme = detected

    # Extract entities
    if mode == 'strict':
        et = []
        ep = []
        for sid, tags in enumerate(y_true):
            et.extend(
                extract_entities_strict(tags, scheme, suffix, delimiter, sid)
            )
        for sid, tags in enumerate(y_pred):
            ep.extend(
                extract_entities_strict(tags, scheme, suffix, delimiter, sid)
            )
    else:
        et = []
        ep = []
        for sid, tags in enumerate(y_true):
            et.extend(
                extract_entities_default(tags, suffix, delimiter, sid)
            )
        for sid, tags in enumerate(y_pred):
            ep.extend(
                extract_entities_default(tags, suffix, delimiter, sid)
            )

    result['entities_true'] = entities_to_dict(et)
    result['entities_pred'] = entities_to_dict(ep)
    result.update(compute_metrics(et, ep))

    json.dump(result, sys.stdout)


if __name__ == '__main__':
    main()
