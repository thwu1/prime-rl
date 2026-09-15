#!/usr/bin/env python3
"""Attack script for text watermarking evaluation.

Applies various text perturbations to test watermark robustness.
"""
import json
import sys
import unicodedata
import random
import argparse
import os


def normalize_attack(text):
    """Apply unicode and whitespace normalization."""
    text = unicodedata.normalize('NFC', text)
    text = ' '.join(text.split())
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    text = text.replace('\u2013', '-').replace('\u2014', '-')
    return text


def perturb_attack(text, seed=42, rate=0.08):
    """Randomly swap adjacent characters in some words."""
    rng = random.Random(seed)
    words = text.split()
    result = []
    for word in words:
        if rng.random() < rate and len(word) > 4:
            prefix = ""
            suffix = ""
            core = word
            while core and not core[0].isalpha():
                prefix += core[0]
                core = core[1:]
            while core and not core[-1].isalpha():
                suffix = core[-1] + suffix
                core = core[:-1]
            if len(core) > 4:
                pos = rng.randint(1, len(core) - 3)
                core = core[:pos] + core[pos+1] + core[pos] + core[pos+2:]
            result.append(prefix + core + suffix)
        else:
            result.append(word)
    return ' '.join(result)


def mixed_attack(text, seed=42):
    """Apply normalization followed by perturbation."""
    text = normalize_attack(text)
    text = perturb_attack(text, seed=seed, rate=0.08)
    return text


def apply_attack(input_file, output_dir, attack_type, seed=42):
    """Apply attack to JSONL input and write to output directory."""
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "texts.jsonl")

    with open(input_file) as fin, open(output_file, 'w') as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            text = entry["text"]

            if attack_type == "normalize":
                text = normalize_attack(text)
            elif attack_type == "perturb":
                text = perturb_attack(text, seed=seed)
            elif attack_type == "mixed":
                text = mixed_attack(text, seed=seed)
            else:
                raise ValueError(f"Unknown attack type: {attack_type}")

            entry["text"] = text
            fout.write(json.dumps(entry) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Text watermark attack tool")
    parser.add_argument("attack_type", choices=["normalize", "perturb", "mixed"],
                        help="Type of attack to apply")
    parser.add_argument("input_file", help="Input JSONL file")
    parser.add_argument("output_dir", help="Output directory")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()
    apply_attack(args.input_file, args.output_dir, args.attack_type, args.seed)
