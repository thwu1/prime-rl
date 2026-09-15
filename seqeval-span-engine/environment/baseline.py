#!/usr/bin/env python3
"""Baseline span evaluation tool. Partial implementation with known issues.

Handles basic IOB-style entity extraction but has bugs in boundary logic
and is missing support for several schemes, modes, and output fields.
"""

import json
import sys
from collections import defaultdict


def parse_tag(token_str, suffix=False, delimiter='-'):
    """Parse a tag string into (prefix_char, entity_type)."""
    if token_str == 'O':
        return 'O', '_'
    if suffix:
        parts = token_str.rsplit(delimiter, maxsplit=1)
        return (parts[-1], parts[0]) if len(parts) > 1 else (parts[0], '_')
    else:
        parts = token_str.split(delimiter, maxsplit=1)
        return (parts[0], parts[1]) if len(parts) > 1 else (parts[0], '_')


def extract_entities(tags, suffix=False, delimiter='-', sent_id=0):
    """Extract entity spans from a tag sequence.

    Returns list of (entity_type, sent_id, start, end_exclusive).
    """
    entities = []
    current_type = None
    start = None

    for i, tag_str in enumerate(tags):
        prefix, etype = parse_tag(tag_str, suffix, delimiter)

        if prefix == 'B':
            # B always starts a new entity
            if current_type is not None:
                entities.append((current_type, sent_id, start, i))
            current_type = etype
            start = i
        elif prefix == 'I':
            if current_type is not None and etype == current_type:
                pass  # continuation of same entity
            elif current_type is not None:
                # different type: close current, start new
                entities.append((current_type, sent_id, start, i))
                current_type = etype
                start = i
            else:
                # I without preceding B — start new entity
                current_type = etype
                start = i
        elif prefix == 'O':
            if current_type is not None:
                entities.append((current_type, sent_id, start, i))
                current_type = None
                start = None
        else:
            raise ValueError(f'Unknown prefix: {prefix} in token {tag_str}')

    # close trailing entity
    if current_type is not None:
        entities.append((current_type, sent_id, start, len(tags)))

    return entities


def entities_to_dict(entity_list):
    """Convert entity list to {type: [[sid, start, end], ...]}."""
    result = {}
    for tag, sid, start, end in entity_list:
        result.setdefault(tag, []).append([sid, start, end])
    for k in result:
        result[k].sort()
    return result


def compute_metrics(entities_true, entities_pred):
    """Compute per-type and micro-average metrics."""
    true_by_type = defaultdict(set)
    pred_by_type = defaultdict(set)

    for tag, sid, start, end in entities_true:
        true_by_type[tag].add((sid, start, end))
    for tag, sid, start, end in entities_pred:
        pred_by_type[tag].add((sid, start, end))

    all_types = sorted(set(true_by_type) | set(pred_by_type))
    per_type = {}

    for t in all_types:
        ts = true_by_type.get(t, set())
        ps = pred_by_type.get(t, set())
        tp = len(ts & ps)
        p = tp / len(ps) if ps else 0.0
        r = tp / len(ts) if ts else 0.0
        f = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        per_type[t] = {
            'precision': p, 'recall': r, 'f1': f, 'support': len(ts)
        }

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

    return {
        'per_type': per_type,
        'micro_avg': {
            'precision': micro_p, 'recall': micro_r,
            'f1': micro_f, 'support': total_true,
        },
    }


def main():
    with open(sys.argv[1]) as f:
        config = json.load(f)

    y_true = config['y_true']
    y_pred = config['y_pred']
    suffix = config.get('suffix', False)
    delimiter = config.get('delimiter', '-')

    et, ep = [], []
    for sid, tags in enumerate(y_true):
        et.extend(extract_entities(tags, suffix, delimiter, sid))
    for sid, tags in enumerate(y_pred):
        ep.extend(extract_entities(tags, suffix, delimiter, sid))

    result = {
        'entities_true': entities_to_dict(et),
        'entities_pred': entities_to_dict(ep),
    }
    result.update(compute_metrics(et, ep))
    json.dump(result, sys.stdout)


if __name__ == '__main__':
    main()
