#!/usr/bin/env python3
"""Generate synthetic ASR evaluation data for SCTK scoring task."""
import random
import os

random.seed(42)

# Reference transcript segments: (file, channel, speaker, start, end, labels, text)
segments = [
    ("conv01", "A", "spkA1", 0.50, 5.80, "<O,M,CL>",
     "the quick brown fox jumped over the lazy dog"),
    ("conv01", "A", "spkA1", 6.20, 11.50, "<O,M,CL>",
     "she had your dark suit in greasy wash water all year"),
    ("conv01", "A", "spkA2", 12.00, 17.80, "<O,F,NS>",
     "as competition in the mutual fund business grows increasingly intense"),
    ("conv01", "A", "spkA2", 18.20, 23.50, "<O,F,NS>",
     "more players in the industry appear willing to sacrifice integrity"),
    ("conv01", "A", "spkA1", 24.00, 28.50, "<O,M,CL>",
     "compound yields assume reinvestment of dividends"),
    ("conv01", "B", "spkB1", 0.50, 7.20, "<O,M,NS>",
     "yields on taxable money market mutual funds rose slightly in the latest week"),
    ("conv01", "B", "spkB1", 7.80, 13.50, "<O,M,NS>",
     "the average seven day compound yield on tax free money funds fell"),
    ("conv01", "B", "spkB1", 14.00, 19.50, "<O,M,CL>",
     "average maturity of the tax exempt portfolios lengthened by two days"),
    ("conv02", "A", "spkA2", 0.50, 5.20, "<O,F,CL>",
     "the report must include full financial statements and auditor assurance"),
    ("conv02", "A", "spkA2", 5.80, 11.00, "<O,F,CL>",
     "the company invited some analysts to its headquarters to talk"),
    ("conv02", "A", "spkA1", 11.50, 16.80, "<O,M,NS>",
     "a memorandum from the research firm questioned the health of cash flow"),
    ("conv02", "A", "spkA1", 17.20, 22.50, "<O,M,NS>",
     "in addition questions have been raised by the failure to issue annual reports"),
    ("conv02", "B", "spkB1", 0.50, 6.00, "<O,M,CL>",
     "the practice is almost as annoying as giving oneself three public names"),
    ("conv02", "B", "spkB1", 6.50, 11.80, "<O,M,NS>",
     "its shares fell four point eight seven five dollars on wednesday"),
    ("conv02", "B", "spkB1", 12.20, 17.50, "<O,M,CL>",
     "early last week the stock was trading above thirty dollars"),
    ("conv02", "B", "spkA2", 18.00, 23.80, "<O,F,NS>",
     "many analysts are saying the company will fall short of projected growth"),
]

LABELS = [
    ';; LABEL "O" "Overall" "All Segments"',
    ';; LABEL "M" "Male" "Male Speakers"',
    ';; LABEL "F" "Female" "Female Speakers"',
    ';; LABEL "CL" "Clean" "Clean Recording Conditions"',
    ';; LABEL "NS" "Noisy" "Noisy Recording Conditions"',
]

CATEGORIES = [
    ';; CATEGORY "0" "" ""',
    ';; CATEGORY "1" "Gender" "Speaker Gender"',
    ';; CATEGORY "2" "Condition" "Recording Condition"',
]


def write_stm(path):
    with open(path, "w") as f:
        for cat in CATEGORIES:
            f.write(cat + "\n")
        for lbl in LABELS:
            f.write(lbl + "\n")
        for seg in segments:
            fn, ch, spk, bt, et, lbl, txt = seg
            f.write(f"{fn} {ch} {spk} {bt:.2f} {et:.2f} {lbl} {txt}\n")


# Error injection for each system
SYSTEM_PROFILES = {
    "sys1": {
        "sub_rate": 0.06, "del_rate": 0.02, "ins_rate": 0.02,
        "subs": {"the": "a", "in": "and", "of": "the", "fund": "find",
                 "its": "it's", "to": "too"},
        "conf_mean": 0.85, "conf_std": 0.12,
    },
    "sys2": {
        "sub_rate": 0.10, "del_rate": 0.03, "ins_rate": 0.03,
        "subs": {"the": "the", "mutual": "actual", "yields": "fields",
                 "compound": "compound", "analysts": "announce",
                 "average": "average", "maturity": "majority",
                 "integrity": "integrity", "questioned": "questions",
                 "practice": "practical"},
        "conf_mean": 0.75, "conf_std": 0.18,
    },
    "sys3": {
        "sub_rate": 0.08, "del_rate": 0.04, "ins_rate": 0.01,
        "subs": {"jumped": "leaped", "greasy": "easy", "sacrifice": "surface",
                 "oneself": "one", "memorandum": "memoranda",
                 "lengthened": "length", "portfolios": "portfolio",
                 "increasingly": "increasing"},
        "conf_mean": 0.80, "conf_std": 0.15,
    },
    "sys4": {
        "sub_rate": 0.12, "del_rate": 0.02, "ins_rate": 0.04,
        "subs": {"fox": "box", "suit": "sweet", "wash": "watch",
                 "taxable": "textbook", "exempt": "example",
                 "financial": "finally", "auditor": "audit",
                 "annoying": "morning", "projected": "protected"},
        "conf_mean": 0.70, "conf_std": 0.20,
    },
    "sys5": {
        "sub_rate": 0.15, "del_rate": 0.05, "ins_rate": 0.03,
        "subs": {"quick": "thick", "brown": "crown", "over": "other",
                 "dark": "dock", "competition": "composition",
                 "business": "witness", "industry": "infantry",
                 "money": "many", "health": "wealth",
                 "dollars": "collars", "growth": "gross"},
        "conf_mean": 0.65, "conf_std": 0.22,
    },
}

INSERT_WORDS = ["um", "uh", "the", "a", "and", "like", "so", "well"]


def generate_hyp_words(ref_words, profile):
    """Generate hypothesis words with controlled errors."""
    rng = random.Random()
    rng.seed(hash(tuple(ref_words)) + hash(profile["conf_mean"]))

    hyp = []
    for w in ref_words:
        # Check for substitution
        if w in profile["subs"] and profile["subs"][w] != w:
            if rng.random() < 0.7:  # Apply known sub 70% of the time
                hyp.append(profile["subs"][w])
                continue
        if rng.random() < profile["sub_rate"]:
            # Random substitution
            sub_word = rng.choice(INSERT_WORDS)
            hyp.append(sub_word)
            continue
        # Check for deletion
        if rng.random() < profile["del_rate"]:
            continue
        # Insert before this word
        if rng.random() < profile["ins_rate"]:
            hyp.append(rng.choice(INSERT_WORDS))
        hyp.append(w)

    return hyp


def assign_timings(words, seg_start, seg_end):
    """Assign realistic word timings within a segment."""
    if not words:
        return []
    total_dur = seg_end - seg_start
    rng = random.Random(hash(tuple(words)))
    raw_durs = [rng.uniform(0.15, 0.45) for _ in words]
    total_raw = sum(raw_durs)
    usable = total_dur * 0.90
    scale = usable / total_raw if total_raw > 0 else 1.0
    durs = [d * scale for d in raw_durs]

    start = seg_start + (total_dur * 0.05)
    result = []
    for w, d in zip(words, durs):
        result.append((start, d, w))
        start += d + 0.01
    return result


def generate_confidence(n_words, mean_conf, std_conf):
    """Generate confidence scores."""
    rng = random.Random(n_words * 1000 + int(mean_conf * 100))
    confs = []
    for _ in range(n_words):
        c = rng.gauss(mean_conf, std_conf)
        c = max(0.01, min(0.99, c))
        confs.append(c)
    return confs


def write_ctm(path, sys_name, profile):
    with open(path, "w") as f:
        f.write(f";; System: {sys_name}\n")
        f.write(";;\n")
        for seg in segments:
            fn, ch, spk, bt, et, lbl, txt = seg
            ref_words = txt.split()
            hyp_words = generate_hyp_words(ref_words, profile)
            timings = assign_timings(hyp_words, bt, et)
            confs = generate_confidence(len(hyp_words), profile["conf_mean"],
                                        profile["conf_std"])
            for (start, dur, word), conf in zip(timings, confs):
                f.write(f"{fn} {ch} {start:.2f} {dur:.2f} {word} {conf:.6f}\n")


def write_wwl(path):
    all_words = set()
    for seg in segments:
        for w in seg[6].split():
            all_words.add(w.lower())
    with open(path, "w") as f:
        f.write(";; 'Headings' 'Word Spelling' 'Character Count'\n")
        f.write(";; Default missing weight '30'\n")
        for w in sorted(all_words):
            f.write(f"{w} {len(w)}\n")


def write_broken_eval(workspace_dir):
    """Write an incomplete, broken evaluation attempt to the workspace."""
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(os.path.join(workspace_dir, "eval_output"), exist_ok=True)

    script = """\
#!/bin/bash
# Preliminary evaluation attempt
# Status: ABANDONED - persistent format errors

DATADIR=/app/data
OUTDIR=/app/workspace/eval_output
mkdir -p $OUTDIR

echo "=== Scoring individual systems ==="

# Only managed first 3 before giving up
for sys in sys1 sys2 sys3; do
    echo "Processing $sys..."
    sclite -r $DATADIR/ref.stm trn -h $DATADIR/${sys}.ctm ctm \\
        -o sum -O $OUTDIR -f 0 -n $sys 2>&1
done

# sys4 and sys5 had the same errors

echo ""
echo "=== ROVER combination ==="
# Could not figure out correct syntax
# rover -h $DATADIR/sys1.ctm -h $DATADIR/sys2.ctm -h $DATADIR/sys3.ctm \\
#     -o $OUTDIR/rover_out.ctm -m avgconf
echo "ROVER: commented out, syntax errors"

echo ""
echo "Evaluation incomplete"
"""

    script_path = os.path.join(workspace_dir, "run_eval.sh")
    with open(script_path, "w") as f:
        f.write(script)
    os.chmod(script_path, 0o755)

    notes = """\
Evaluation Notes
================

Systems: sys1 through sys5
Reference: ref.stm

Issues:
- sclite keeps rejecting the reference file with format errors.
  Tried several format flags but could not resolve it.
- ROVER does not accept the hypothesis files directly.
  The -h flag syntax seems to need something extra.
- Have not attempted NCE extraction or category-level
  analysis yet.

Files in eval_output/ are from incorrect runs.
"""

    notes_path = os.path.join(workspace_dir, "notes.txt")
    with open(notes_path, "w") as f:
        f.write(notes)


def main():
    outdir = "/app/data"
    os.makedirs(outdir, exist_ok=True)

    write_stm(os.path.join(outdir, "ref.stm"))

    for sys_name, profile in SYSTEM_PROFILES.items():
        write_ctm(os.path.join(outdir, f"{sys_name}.ctm"), sys_name, profile)

    write_wwl(os.path.join(outdir, "weights.wwl"))

    write_broken_eval("/app/workspace")

    print("Data generation complete.")
    total = 0
    for seg in segments:
        n = len(seg[6].split())
        total += n
    print(f"Total reference words: {total}")
    print(f"Total segments: {len(segments)}")


if __name__ == "__main__":
    main()
