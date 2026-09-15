#!/usr/bin/env python3
"""Text watermarking system using hash-based synonym substitution.


Embeds watermarks by deterministically replacing eligible words with their
synonyms based on a cryptographic hash of (secret_key, document_id, word).
Detection checks whether observed word choices correlate with the hash pattern
at a rate significantly above chance.
"""
import hashlib
import json
import argparse
import os
import re
import unicodedata


def load_synonyms(path="/app/data/synonyms.json"):
    with open(path) as f:
        return json.load(f)


def build_reverse_map(synonyms):
    """Map every word (original or synonym) to its canonical (original) form."""
    reverse = {}
    for original, syns in synonyms.items():
        reverse[original] = original
        for s in syns:
            reverse[s] = original
    return reverse


def compute_decision(key, doc_id, canonical_word):
    """Hash-based binary decision: 0 = keep original, 1 = use synonym."""
    payload = f"{key}:{doc_id}:{canonical_word}"
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return int(h, 16) % 2


def normalize_word(word):
    """Extract the alphabetic core of a word for dictionary lookup."""
    core = word.lower()
    core = re.sub(r"^[^a-z]+", "", core)
    core = re.sub(r"[^a-z]+$", "", core)
    return core


def extract_affixes(word):
    """Split word into (leading_punct, alpha_core, trailing_punct)."""
    match = re.match(r"^([^a-zA-Z]*)([a-zA-Z]*)([^a-zA-Z]*)$", word)
    if match:
        return match.group(1), match.group(2), match.group(3)
    return "", word, ""


def preserve_case(original_core, replacement):
    """Transfer case pattern from original to replacement."""
    if not original_core or not replacement:
        return replacement
    if original_core.isupper():
        return replacement.upper()
    if original_core[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement.lower()


def embed_watermark(key, input_file, output_file, synonyms_path="/app/data/synonyms.json"):
    synonyms = load_synonyms(synonyms_path)
    reverse_map = build_reverse_map(synonyms)

    with open(input_file) as fin, open(output_file, "w") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            doc_id = entry["id"]
            text = entry["text"]

            words = text.split()
            result_words = []

            for word in words:
                prefix, core, suffix = extract_affixes(word)
                normalized = core.lower()

                canonical = reverse_map.get(normalized)
                if canonical and canonical in synonyms and len(synonyms[canonical]) > 0:
                    decision = compute_decision(key, doc_id, canonical)
                    if decision == 1:
                        replacement = synonyms[canonical][0]
                    else:
                        replacement = canonical
                    replacement = preserve_case(core, replacement)
                    result_words.append(prefix + replacement + suffix)
                else:
                    result_words.append(word)

            entry["text"] = " ".join(result_words)
            fout.write(json.dumps(entry) + "\n")


def levenshtein(s1, s2):
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
        prev = curr
    return prev[-1]


def fuzzy_lookup(word, mapping, max_dist=2):
    """Find closest match in mapping within edit distance threshold."""
    if word in mapping:
        return mapping[word]
    best_val = None
    best_dist = max_dist + 1
    for key, val in mapping.items():
        if abs(len(key) - len(word)) > max_dist:
            continue
        d = levenshtein(word, key)
        if d < best_dist:
            best_dist = d
            best_val = val
    return best_val if best_dist <= max_dist else None


def fuzzy_match(word1, word2, max_dist=2):
    """Check if two words are within edit distance threshold."""
    if word1 == word2:
        return True
    return levenshtein(word1, word2) <= max_dist


def detect_watermark(key, input_file, output_file, synonyms_path="/app/data/synonyms.json"):
    synonyms = load_synonyms(synonyms_path)
    reverse_map = build_reverse_map(synonyms)

    with open(input_file) as fin, open(output_file, "w") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            doc_id = entry["id"]
            text = entry["text"]

            # Normalize text to handle unicode/whitespace attacks
            text = unicodedata.normalize("NFC", text)
            text = " ".join(text.split())

            words = text.split()
            matches = 0
            eligible = 0

            for word in words:
                _, core, _ = extract_affixes(word)
                normalized = core.lower()
                if not normalized:
                    continue

                # Look up canonical form (exact then fuzzy)
                canonical = reverse_map.get(normalized)
                if canonical is None:
                    canonical = fuzzy_lookup(normalized, reverse_map, max_dist=2)
                if canonical is None or canonical not in synonyms:
                    continue
                if len(synonyms[canonical]) == 0:
                    continue

                synonym = synonyms[canonical][0]
                decision = compute_decision(key, doc_id, canonical)

                if decision == 1:
                    # Expect synonym
                    if normalized == synonym or fuzzy_match(normalized, synonym, max_dist=2):
                        matches += 1
                else:
                    # Expect original
                    if normalized == canonical or fuzzy_match(normalized, canonical, max_dist=2):
                        matches += 1
                eligible += 1

            # Statistical detection threshold
            if eligible >= 3:
                match_rate = matches / eligible
                label = 1.0 if match_rate > 0.70 else 0.0
            else:
                label = 0.0

            fout.write(json.dumps({"id": doc_id, "label": label}) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Text watermarking tool")
    parser.add_argument("command", choices=["embed", "detect"])
    parser.add_argument("--key", required=True, help="Secret watermark key")
    parser.add_argument("--input", required=True, help="Input JSONL file")
    parser.add_argument("--output", required=True, help="Output JSONL file")
    parser.add_argument("--synonyms", default="/app/data/synonyms.json",
                        help="Path to synonym dictionary")
    args = parser.parse_args()

    if args.command == "embed":
        embed_watermark(args.key, args.input, args.output, args.synonyms)
    elif args.command == "detect":
        detect_watermark(args.key, args.input, args.output, args.synonyms)
