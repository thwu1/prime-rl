#!/usr/bin/env python3
"""
proofquery - Proof-state query engine with marker-placement mini-language,
JSON structural minification, jq filter generation, and proof obligation DAG.
"""

import sys
import json
import fnmatch as fnmatch_module
import argparse


# ============================================================
# Path segment types
# ============================================================

class SentenceMatch:
    def __init__(self, pattern, mode):
        self.pattern = pattern
        self.mode = mode  # 'literal' or 'fnmatch'

class GoalMatch:
    def __init__(self, value, mode):
        self.value = value
        self.mode = mode  # 'position', 'name', 'literal', 'fnmatch'

class HypothesisMatch:
    def __init__(self, value, mode):
        self.value = value
        self.mode = mode  # 'name', 'literal', 'fnmatch'

class MessageMatch:
    def __init__(self, pattern=None, mode=None):
        self.pattern = pattern
        self.mode = mode  # None, 'literal', 'fnmatch'

class LeafSelector:
    def __init__(self, kind):
        self.kind = kind  # 'in', 'ccl', 'name', 'type', 'body'


# ============================================================
# Path parser
# ============================================================

def _read_until(s, start, delimiter):
    end = s.index(delimiter, start)
    return s[start:end], end + 1

def _read_until_dot_or_end(s, start):
    end = start
    while end < len(s) and s[end] != '.':
        end += 1
    return s[start:end], end

def parse_path(path_str):
    segments = []
    pos = 0
    s = path_str

    while pos < len(s):
        if s[pos] != '.':
            raise ValueError(f"Expected '.' at position {pos}, got '{s[pos]}'")
        pos += 1

        if s[pos:].startswith('s('):
            pos += 2
            pattern, pos = _read_until(s, pos, ')')
            segments.append(SentenceMatch(pattern, 'literal'))
        elif s[pos:].startswith('s{'):
            pos += 2
            pattern, pos = _read_until(s, pos, '}')
            segments.append(SentenceMatch(pattern, 'fnmatch'))
        elif s[pos:].startswith('g#'):
            pos += 2
            value, pos = _read_until_dot_or_end(s, pos)
            try:
                segments.append(GoalMatch(int(value), 'position'))
            except ValueError:
                segments.append(GoalMatch(value, 'name'))
        elif s[pos:].startswith('g('):
            pos += 2
            pattern, pos = _read_until(s, pos, ')')
            segments.append(GoalMatch(pattern, 'literal'))
        elif s[pos:].startswith('g{'):
            pos += 2
            pattern, pos = _read_until(s, pos, '}')
            segments.append(GoalMatch(pattern, 'fnmatch'))
        elif s[pos:].startswith('h#'):
            pos += 2
            value, pos = _read_until_dot_or_end(s, pos)
            segments.append(HypothesisMatch(value, 'name'))
        elif s[pos:].startswith('h('):
            pos += 2
            pattern, pos = _read_until(s, pos, ')')
            segments.append(HypothesisMatch(pattern, 'literal'))
        elif s[pos:].startswith('h{'):
            pos += 2
            pattern, pos = _read_until(s, pos, '}')
            segments.append(HypothesisMatch(pattern, 'fnmatch'))
        elif s[pos:].startswith('msg('):
            pos += 4
            pattern, pos = _read_until(s, pos, ')')
            segments.append(MessageMatch(pattern, 'literal'))
        elif s[pos:].startswith('msg{'):
            pos += 4
            pattern, pos = _read_until(s, pos, '}')
            segments.append(MessageMatch(pattern, 'fnmatch'))
        elif _match_keyword(s, pos, 'msg'):
            pos += 3
            segments.append(MessageMatch())
        elif _match_keyword(s, pos, 'ccl'):
            pos += 3
            segments.append(LeafSelector('ccl'))
        elif _match_keyword(s, pos, 'name'):
            pos += 4
            segments.append(LeafSelector('name'))
        elif _match_keyword(s, pos, 'type'):
            pos += 4
            segments.append(LeafSelector('type'))
        elif _match_keyword(s, pos, 'body'):
            pos += 4
            segments.append(LeafSelector('body'))
        elif _match_keyword(s, pos, 'in'):
            pos += 2
            segments.append(LeafSelector('in'))
        else:
            raise ValueError(f"Unknown segment at position {pos}: '{s[pos:]}'")

    return segments

def _match_keyword(s, pos, keyword):
    end = pos + len(keyword)
    return s[pos:end] == keyword and (end >= len(s) or s[end] == '.')


# ============================================================
# Query evaluator
# ============================================================

def _get_all_sentences(document):
    sentences = []
    for fragment in document:
        for item in fragment:
            if isinstance(item, dict) and item.get("_type") == "sentence":
                sentences.append(item)
    return sentences

def _match_text(text, pattern, mode):
    if mode == 'literal':
        return pattern in text
    elif mode == 'fnmatch':
        return fnmatch_module.fnmatch(text, pattern)
    return False

def evaluate(document, path_segments):
    ctx = "document"
    data = document

    for seg in path_segments:
        if isinstance(seg, SentenceMatch):
            if ctx == "document":
                sentences = _get_all_sentences(data)
            elif ctx == "sentences":
                sentences = data
            else:
                return []
            data = [s for s in sentences
                    if _match_text(s["sentence"], seg.pattern, seg.mode)]
            ctx = "sentences"

        elif isinstance(seg, GoalMatch):
            if ctx == "sentences":
                goals = []
                for s in data:
                    s_goals = s.get("goals", [])
                    if seg.mode == 'position':
                        idx = seg.value - 1
                        if 0 <= idx < len(s_goals):
                            goals.append(s_goals[idx])
                    elif seg.mode == 'name':
                        for g in s_goals:
                            if g.get("name") is not None and \
                               fnmatch_module.fnmatch(g["name"], seg.value):
                                goals.append(g)
                    elif seg.mode == 'literal':
                        for g in s_goals:
                            if seg.value in g.get("conclusion", ""):
                                goals.append(g)
                    elif seg.mode == 'fnmatch':
                        for g in s_goals:
                            if fnmatch_module.fnmatch(
                                    g.get("conclusion", ""), seg.value):
                                goals.append(g)
                data = goals
                ctx = "goals"
            elif ctx == "goals":
                filtered = []
                for g in data:
                    if seg.mode == 'literal':
                        if seg.value in g.get("conclusion", ""):
                            filtered.append(g)
                    elif seg.mode == 'fnmatch':
                        if fnmatch_module.fnmatch(
                                g.get("conclusion", ""), seg.value):
                            filtered.append(g)
                data = filtered
            else:
                return []

        elif isinstance(seg, HypothesisMatch):
            if ctx == "sentences":
                goals = []
                for s in data:
                    s_goals = s.get("goals", [])
                    if s_goals:
                        goals.append(s_goals[0])
                data = goals
                ctx = "goals"

            if ctx == "goals":
                hyps = []
                for g in data:
                    for h in g.get("hypotheses", []):
                        if seg.mode == 'name':
                            if fnmatch_module.fnmatch(h["name"], seg.value):
                                hyps.append(h)
                        elif seg.mode == 'literal':
                            t = h.get("type") or ""
                            b = h.get("body") or ""
                            if seg.value in t or seg.value in b:
                                hyps.append(h)
                        elif seg.mode == 'fnmatch':
                            t = h.get("type") or ""
                            b = h.get("body") or ""
                            if fnmatch_module.fnmatch(t, seg.value) or \
                               fnmatch_module.fnmatch(b, seg.value):
                                hyps.append(h)
                data = hyps
                ctx = "hypotheses"
            else:
                return []

        elif isinstance(seg, MessageMatch):
            if ctx == "sentences":
                msgs = []
                for s in data:
                    for r in s.get("responses", []):
                        if seg.pattern is None:
                            msgs.append(r)
                        elif _match_text(r, seg.pattern, seg.mode):
                            msgs.append(r)
                data = msgs
                ctx = "messages"
            else:
                return []

        elif isinstance(seg, LeafSelector):
            if seg.kind == 'in':
                if ctx == "sentences":
                    data = [s["sentence"] for s in data]
                    ctx = "strings"
                else:
                    return []
            elif seg.kind == 'ccl':
                if ctx == "sentences":
                    data = [s["goals"][0]["conclusion"]
                            for s in data if s.get("goals")]
                    ctx = "strings"
                elif ctx == "goals":
                    data = [g["conclusion"] for g in data]
                    ctx = "strings"
                else:
                    return []
            elif seg.kind == 'name':
                if ctx == "goals":
                    data = [g["name"] for g in data
                            if g.get("name") is not None]
                    ctx = "strings"
                elif ctx == "hypotheses":
                    data = [h["name"] for h in data]
                    ctx = "strings"
                else:
                    return []
            elif seg.kind == 'type':
                if ctx == "hypotheses":
                    data = [h["type"] for h in data]
                    ctx = "strings"
                else:
                    return []
            elif seg.kind == 'body':
                if ctx == "hypotheses":
                    data = [h["body"] for h in data
                            if h.get("body") is not None]
                    ctx = "strings"
                else:
                    return []

    return data


# ============================================================
# Minification
# ============================================================

def minify(document):
    refs = {}
    ref_counter = [0]

    def _next_id():
        rid = str(ref_counter[0])
        ref_counter[0] += 1
        return rid

    # Phase 1: Deduplicate hypotheses
    hyp_counts = {}
    for fragment in document:
        for item in fragment:
            if isinstance(item, dict) and item.get("_type") == "sentence":
                for goal in item.get("goals", []):
                    for hyp in goal.get("hypotheses", []):
                        canon = json.dumps(hyp, sort_keys=True)
                        hyp_counts[canon] = hyp_counts.get(canon, 0) + 1

    hyp_to_ref = {}
    for canon, count in hyp_counts.items():
        if count >= 2:
            rid = _next_id()
            hyp_to_ref[canon] = rid
            refs[rid] = json.loads(canon)

    def _replace_hyps_in_goal(goal):
        new_hyps = []
        for hyp in goal.get("hypotheses", []):
            canon = json.dumps(hyp, sort_keys=True)
            if canon in hyp_to_ref:
                new_hyps.append({"$ref": hyp_to_ref[canon]})
            else:
                new_hyps.append(hyp)
        new_goal = dict(goal)
        new_goal["hypotheses"] = new_hyps
        return new_goal

    doc_phase1 = []
    goal_counts = {}
    for fragment in document:
        new_frag = []
        for item in fragment:
            if isinstance(item, dict) and item.get("_type") == "sentence":
                new_item = dict(item)
                new_goals = [_replace_hyps_in_goal(g)
                             for g in item.get("goals", [])]
                new_item["goals"] = new_goals
                for g in new_goals:
                    canon = json.dumps(g, sort_keys=True)
                    goal_counts[canon] = goal_counts.get(canon, 0) + 1
                new_frag.append(new_item)
            else:
                new_frag.append(item)
        doc_phase1.append(new_frag)

    # Phase 2: Deduplicate goals
    goal_to_ref = {}
    for canon, count in goal_counts.items():
        if count >= 2:
            rid = _next_id()
            goal_to_ref[canon] = rid
            refs[rid] = json.loads(canon)

    doc_final = []
    for fragment in doc_phase1:
        new_frag = []
        for item in fragment:
            if isinstance(item, dict) and item.get("_type") == "sentence":
                new_item = dict(item)
                new_goals = []
                for g in item.get("goals", []):
                    canon = json.dumps(g, sort_keys=True)
                    if canon in goal_to_ref:
                        new_goals.append({"$ref": goal_to_ref[canon]})
                    else:
                        new_goals.append(g)
                new_item["goals"] = new_goals
                new_frag.append(new_item)
            else:
                new_frag.append(item)
        doc_final.append(new_frag)

    return {"_refs": refs, "data": doc_final}


def expand(minified):
    refs = minified["_refs"]
    data = minified["data"]

    def resolve(obj):
        if isinstance(obj, dict):
            if "$ref" in obj and len(obj) == 1:
                ref_id = obj["$ref"]
                if ref_id in refs:
                    return resolve(refs[ref_id])
                return obj
            return {k: resolve(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [resolve(item) for item in obj]
        return obj

    return resolve(data)


def load_document(file_path):
    with open(file_path) as f:
        data = json.load(f)
    if isinstance(data, dict) and "_refs" in data and "data" in data:
        return expand(data)
    return data


# ============================================================
# jq filter generation
# ============================================================

def _fnmatch_to_regex(pattern):
    """Convert an fnmatch pattern to a PCRE regex for jq's test()."""
    result = ['^']
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == '*':
            result.append('.*')
            i += 1
        elif c == '?':
            result.append('.')
            i += 1
        elif c == '[':
            j = i + 1
            chars = '['
            if j < n and pattern[j] == '!':
                chars += '^'
                j += 1
            while j < n and pattern[j] != ']':
                chars += pattern[j]
                j += 1
            if j < n:
                chars += ']'
                result.append(chars)
                i = j + 1
            else:
                result.append('\\[')
                i += 1
        elif c in '.+^${}|()\\':
            result.append('\\' + c)
            i += 1
        else:
            result.append(c)
            i += 1
    result.append('$')
    return ''.join(result)


def _jq_escape(s):
    """Escape a string for embedding inside a jq double-quoted string literal."""
    return (s
            .replace('\\', '\\\\')
            .replace('"', '\\"')
            .replace('\n', '\\n')
            .replace('\t', '\\t'))


def generate_jq(segments):
    """Generate a jq filter expression from parsed path segments."""
    parts = ['.[][]']
    ctx = 'document'

    for seg in segments:
        if isinstance(seg, SentenceMatch):
            if seg.mode == 'literal':
                cond = '(.sentence | contains("{0}"))'.format(
                    _jq_escape(seg.pattern))
            else:
                regex = _fnmatch_to_regex(seg.pattern)
                cond = '(.sentence | test("{0}"))'.format(
                    _jq_escape(regex))
            parts.append(
                'select(._type == "sentence" and {0})'.format(cond))
            ctx = 'sentences'

        elif isinstance(seg, GoalMatch):
            if ctx == 'sentences':
                if seg.mode == 'position':
                    n = seg.value
                    parts.append(
                        'select(.goals | length >= {0})'.format(n))
                    parts.append('.goals[{0}]'.format(n - 1))
                elif seg.mode == 'name':
                    regex = _fnmatch_to_regex(seg.value)
                    parts.append('.goals[]')
                    parts.append(
                        'select(.name != null and '
                        '(.name | test("{0}")))'.format(
                            _jq_escape(regex)))
                elif seg.mode == 'literal':
                    parts.append('.goals[]')
                    parts.append(
                        'select(.conclusion | contains("{0}"))'.format(
                            _jq_escape(seg.value)))
                elif seg.mode == 'fnmatch':
                    regex = _fnmatch_to_regex(seg.value)
                    parts.append('.goals[]')
                    parts.append(
                        'select(.conclusion | test("{0}"))'.format(
                            _jq_escape(regex)))
                ctx = 'goals'
            elif ctx == 'goals':
                if seg.mode == 'literal':
                    parts.append(
                        'select(.conclusion | contains("{0}"))'.format(
                            _jq_escape(seg.value)))
                elif seg.mode == 'fnmatch':
                    regex = _fnmatch_to_regex(seg.value)
                    parts.append(
                        'select(.conclusion | test("{0}"))'.format(
                            _jq_escape(regex)))

        elif isinstance(seg, HypothesisMatch):
            if ctx == 'sentences':
                parts.append('select(.goals | length > 0)')
                parts.append('.goals[0]')
                ctx = 'goals'
            if ctx == 'goals':
                if seg.mode == 'name':
                    regex = _fnmatch_to_regex(seg.value)
                    parts.append('.hypotheses[]')
                    parts.append(
                        'select(.name | test("{0}"))'.format(
                            _jq_escape(regex)))
                elif seg.mode == 'literal':
                    esc = _jq_escape(seg.value)
                    parts.append('.hypotheses[]')
                    parts.append(
                        'select((.type | contains("{0}")) or '
                        '((.body // "") | contains("{0}")))'.format(esc))
                elif seg.mode == 'fnmatch':
                    regex = _fnmatch_to_regex(seg.value)
                    esc = _jq_escape(regex)
                    parts.append('.hypotheses[]')
                    parts.append(
                        'select((.type | test("{0}")) or '
                        '((.body // "") | test("{0}")))'.format(esc))
                ctx = 'hypotheses'

        elif isinstance(seg, MessageMatch):
            if ctx == 'sentences':
                if seg.pattern is None:
                    parts.append('.responses[]')
                elif seg.mode == 'literal':
                    parts.append('.responses[]')
                    parts.append(
                        'select(contains("{0}"))'.format(
                            _jq_escape(seg.pattern)))
                elif seg.mode == 'fnmatch':
                    regex = _fnmatch_to_regex(seg.pattern)
                    parts.append('.responses[]')
                    parts.append(
                        'select(test("{0}"))'.format(
                            _jq_escape(regex)))
                ctx = 'messages'

        elif isinstance(seg, LeafSelector):
            if seg.kind == 'in':
                if ctx == 'sentences':
                    parts.append('.sentence')
                    ctx = 'strings'
            elif seg.kind == 'ccl':
                if ctx == 'sentences':
                    parts.append('select(.goals | length > 0)')
                    parts.append('.goals[0].conclusion')
                    ctx = 'strings'
                elif ctx == 'goals':
                    parts.append('.conclusion')
                    ctx = 'strings'
            elif seg.kind == 'name':
                if ctx == 'goals':
                    parts.append('select(.name != null)')
                    parts.append('.name')
                    ctx = 'strings'
                elif ctx == 'hypotheses':
                    parts.append('.name')
                    ctx = 'strings'
            elif seg.kind == 'type':
                if ctx == 'hypotheses':
                    parts.append('.type')
                    ctx = 'strings'
            elif seg.kind == 'body':
                if ctx == 'hypotheses':
                    parts.append('select(.body != null)')
                    parts.append('.body')
                    ctx = 'strings'

    return '[' + ' | '.join(parts) + ']'


# ============================================================
# Proof Obligation DAG
# ============================================================

def _extract_proof_name(sentence_text):
    """Extract proof name from declaration sentence."""
    tokens = sentence_text.split()
    if len(tokens) >= 2:
        return tokens[1].rstrip(':.')
    return "unknown"


def _goals_structurally_equal(g1, g2):
    """Check if two goal lists are structurally equal."""
    if g1 is None or g2 is None:
        return g1 is g2
    return json.dumps(g1, sort_keys=True) == json.dumps(g2, sort_keys=True)


def analyze_dag(document):
    """Build proof obligation DAG from proof-state document."""
    proofs = []
    commands = []

    for fragment in document:
        sentences = [item for item in fragment
                     if isinstance(item, dict) and item.get("_type") == "sentence"]
        if not sentences:
            continue

        has_terminal = any(s["sentence"] in ("Qed.", "Defined.")
                          for s in sentences)
        if not has_terminal:
            for s in sentences:
                commands.append({"sentence": s["sentence"], "effect": "info"})
            continue

        proof = _analyze_proof(sentences)
        proofs.append(proof)

    return {"proofs": proofs, "commands": commands}


def _analyze_proof(sentences):
    """Analyze a proof fragment and build the obligation DAG."""
    name = _extract_proof_name(sentences[0]["sentence"])

    gctr = [0]
    gmap = {}       # gid -> goal data dict (mutable)
    pending = []    # ordered list of pending goal IDs; first = focused
    steps = []
    prev_goals = None
    last_hyp_count = 0

    def _new_goal(conclusion, hyp_count, parent, step_idx):
        gid = "g{}".format(gctr[0])
        gctr[0] += 1
        gmap[gid] = {
            "id": gid,
            "conclusion": conclusion,
            "parent": parent,
            "children": [],
            "spawned_by": step_idx,
            "resolved_by": None,
            "resolution": None,
            "_ihc": hyp_count,   # internal: initial hypothesis count
        }
        return gid

    for idx, sent in enumerate(sentences):
        stxt = sent["sentence"]
        cg = sent.get("goals", [])
        effect = None

        if stxt in ("Qed.", "Defined."):
            effect = "close"

        elif idx == 0:
            # Declaration sentence
            effect = "declare"
            if cg:
                gid = _new_goal(
                    cg[0]["conclusion"],
                    len(cg[0].get("hypotheses", [])),
                    None, idx)
                pending.append(gid)
                last_hyp_count = len(cg[0].get("hypotheses", []))

        elif _goals_structurally_equal(prev_goals, cg) and (len(cg) > 0 or not pending):
            effect = "noop"

        elif len(cg) > 1:
            # Branch: focused goal splits into multiple sub-goals
            effect = "branch"
            focused = pending.pop(0) if pending else None
            children = []
            for g in cg:
                gid = _new_goal(
                    g["conclusion"],
                    len(g.get("hypotheses", [])),
                    focused, idx)
                children.append(gid)
            if focused and focused in gmap:
                gmap[focused]["children"] = children
                gmap[focused]["resolved_by"] = idx
                gmap[focused]["resolution"] = "branch"
            # Push children to front, preserving order, then rest of pending
            pending = children + pending
            last_hyp_count = len(cg[0].get("hypotheses", []))

        elif len(cg) == 0:
            # Discharge: focused goal is proven
            effect = "discharge"
            focused = pending.pop(0) if pending else None
            if focused and focused in gmap:
                gmap[focused]["resolved_by"] = idx
                gmap[focused]["resolution"] = "discharge"
            # Update hyp count baseline for next focused goal
            if pending:
                last_hyp_count = gmap[pending[0]]["_ihc"]
            else:
                last_hyp_count = 0

        else:
            # Single goal: intro or transform
            curr_hyps = len(cg[0].get("hypotheses", []))
            if curr_hyps > last_hyp_count:
                effect = "intro"
            else:
                effect = "transform"
            last_hyp_count = curr_hyps

        steps.append({
            "index": idx,
            "sentence": stxt,
            "effect": effect
        })
        prev_goals = cg

    # Build output goals list, ordered by ID, without internal fields
    goals_out = []
    for gid in sorted(gmap, key=lambda x: int(x[1:])):
        g = dict(gmap[gid])
        del g["_ihc"]
        goals_out.append(g)

    return {"name": name, "goals": goals_out, "steps": steps}


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Proof-state query engine with marker-placement paths")
    subparsers = parser.add_subparsers(dest="command", required=True)

    q = subparsers.add_parser("query")
    q.add_argument("path", help="Marker-placement path")
    q.add_argument("file", help="JSON proof state file")

    m = subparsers.add_parser("minify")
    m.add_argument("file", help="JSON proof state file")
    m.add_argument("-o", "--output", required=True)

    e = subparsers.add_parser("expand")
    e.add_argument("file", help="Minified JSON file")
    e.add_argument("-o", "--output", required=True)

    j = subparsers.add_parser("jqgen")
    j.add_argument("path", help="Marker-placement path")
    j.add_argument("file", help="JSON proof state file")

    d = subparsers.add_parser("dag")
    d.add_argument("file", help="JSON proof state file")

    args = parser.parse_args()

    if args.command == "query":
        document = load_document(args.file)
        segments = parse_path(args.path)
        results = evaluate(document, segments)
        print(json.dumps(results, indent=2))

    elif args.command == "minify":
        with open(args.file) as f:
            document = json.load(f)
        result = minify(document)
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)

    elif args.command == "expand":
        with open(args.file) as f:
            minified = json.load(f)
        result = expand(minified)
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)

    elif args.command == "jqgen":
        segments = parse_path(args.path)
        jq_filter = generate_jq(segments)
        print(jq_filter)

    elif args.command == "dag":
        document = load_document(args.file)
        result = analyze_dag(document)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
