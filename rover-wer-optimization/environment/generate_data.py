#!/usr/bin/env python3

"""Generate ASR evaluation data for the ROVER optimization task.

Creates a reference STM file and four hypothesis CTM files with
controlled error patterns and deliberately varied confidence calibration
profiles. One system is anti-calibrated (high confidence on errors,
low on correct words), creating a non-trivial ROVER optimization
landscape where method selection and alpha tuning interact with
calibration quality.
"""
import os

DATA_DIR = "/app/data"
os.makedirs(DATA_DIR, exist_ok=True)

# Reference segments: (file, channel, speaker, start, end, words)
REF_SEGMENTS = [
    ("broadcast01", "A", "spk1", 0.00, 6.00,
     "the quarterly report shows moderate growth in all economic sectors".split()),
    ("broadcast01", "A", "spk1", 7.00, 12.50,
     "senior analysts predict continued expansion across emerging market regions".split()),
    ("broadcast01", "A", "spk2", 13.00, 18.50,
     "inflation remains a significant concern for central bank policy makers".split()),
    ("broadcast01", "A", "spk2", 19.00, 24.50,
     "trade negotiations between major economic powers entered a critical phase".split()),
    ("broadcast01", "A", "spk1", 25.00, 30.50,
     "agricultural exports exceeded initial projections for the current fiscal period".split()),
    ("broadcast01", "A", "spk2", 31.00, 36.50,
     "technology investments continue to outpace traditional sector growth rates substantially".split()),
    ("broadcast01", "A", "spk1", 37.00, 42.50,
     "consumer confidence indicators suggest renewed optimism about future purchasing decisions".split()),
    ("broadcast01", "A", "spk2", 43.00, 48.50,
     "regulatory frameworks must adapt quickly to address challenges in digital commerce".split()),
]

# Write STM reference file
with open(os.path.join(DATA_DIR, "reference.stm"), "w") as f:
    f.write(";; Reference transcription for broadcast01\n")
    f.write(";;\n")
    for fid, ch, spk, start, end, words in REF_SEGMENTS:
        f.write("{} {} {} {:.2f} {:.2f} {}\n".format(
            fid, ch, spk, start, end, " ".join(words)))


def write_ctm(filename, segments, sys_errors, base_conf, conf_variation):
    """Write a CTM file with specified errors and confidence scores.

    sys_errors: list of dicts per segment, mapping word-position -> (replacement, confidence)
    base_conf: base confidence for correct words
    conf_variation: per-position variation multiplier for correct word confidence
    """
    with open(os.path.join(DATA_DIR, filename), "w") as f:
        for seg_idx, (fid, ch, spk, seg_start, seg_end, ref_words) in enumerate(segments):
            n = len(ref_words)
            errors = sys_errors[seg_idx]
            dur_per_word = (seg_end - seg_start) / n
            word_dur = round(dur_per_word * 0.75, 2)

            for i, ref_word in enumerate(ref_words):
                w_start = round(seg_start + i * dur_per_word, 2)
                if i in errors:
                    word_text, word_conf = errors[i]
                else:
                    word_text = ref_word
                    word_conf = round(base_conf + (i % 7) * conf_variation, 3)
                f.write("{} {} {:.2f} {:.2f} {} {:.3f}\n".format(
                    fid, ch, w_start, word_dur, word_text, word_conf))


# ======================================================================
# System definitions with calibration-aware confidence patterns
#
# sys1: 10 errors (~12.8% WER), GOOD calibration
#       High conf on correct (0.91+), low conf on errors (0.28-0.42)
#       Expected NCE: strongly positive
#
# sys2: 20 errors (~25.6% WER), MEDIOCRE calibration
#       Medium conf on correct (0.78+), similar conf on errors (0.55-0.72)
#       Expected NCE: near zero or slightly positive
#
# sys3: 12 errors (~15.4% WER), ANTI-CALIBRATED
#       Low conf on correct (0.72+), HIGH conf on errors (0.88-0.97!)
#       Expected NCE: negative -- this system poisons confidence-based ROVER
#
# sys4: 24 errors (~30.8% WER), DECENT calibration
#       Medium conf on correct (0.80+), low conf on errors (0.22-0.38)
#       Expected NCE: moderate positive
#
# Strategic error overlaps (shared errors reduce ROVER correction ability):
# - S2:2 "predict->predicted": sys1, sys2, sys4 (3 systems wrong!)
# - S3:3 "significant->significance": sys2, sys4
# - S3:8 "policy->policing": sys1, sys4
# - S5:2 "exceeded->exceed": sys3, sys4
# - S6:2 "continue->continued": sys2, sys4
#
# Total ref words: 10+9+10+10+10+10+9+10 = 78
# ======================================================================

# System 1: 10 errors, GOOD calibration (errors have LOW confidence)
sys1_errors = [
    {5: ("grows", 0.38)},                                              # S1: 1
    {2: ("predicted", 0.38), 4: ("expense", 0.30)},                    # S2: 2
    {8: ("policing", 0.35), 9: ("markers", 0.28)},                    # S3: 2
    {5: ("power", 0.42)},                                              # S4: 1
    {0: ("agriculture", 0.40)},                                        # S5: 1
    {9: ("substantial", 0.32)},                                        # S6: 1
    {3: ("renew", 0.36)},                                              # S7: 1
    {7: ("digitally", 0.34)},                                          # S8: 1
]

# System 2: 20 errors, MEDIOCRE calibration (errors have MEDIUM confidence)
sys2_errors = [
    {1: ("quoterly", 0.62), 7: ("hall", 0.58), 9: ("section", 0.65)}, # S1: 3
    {1: ("analysis", 0.60), 2: ("predicted", 0.65), 7: ("marketed", 0.55)},  # S2: 3
    {3: ("significance", 0.62), 7: ("banks", 0.68)},                  # S3: 2
    {6: ("entering", 0.55), 8: ("critically", 0.58), 9: ("face", 0.60)},  # S4: 3
    {1: ("export", 0.65), 8: ("physical", 0.55)},                     # S5: 2
    {2: ("continued", 0.68), 4: ("pace", 0.60), 8: ("rate", 0.62)},   # S6: 3
    {0: ("consuming", 0.58), 5: ("renewed", 0.62)},                   # S7: 2
    {4: ("address", 0.65), 8: ("digitized", 0.55)},                   # S8: 2
]

# System 3: 12 errors, ANTI-CALIBRATED (errors have VERY HIGH confidence!)
sys3_errors = [
    {2: ("reports", 0.93), 8: ("economics", 0.89)},                   # S1: 2
    {0: ("seem", 0.91), 5: ("america", 0.88)},                        # S2: 2
    {},                                                                 # S3: 0 (clean!)
    {7: ("the", 0.97)},                                                # S4: 1
    {2: ("exceed", 0.93), 4: ("projection", 0.90), 9: ("periods", 0.88)},  # S5: 3
    {6: ("sectors", 0.91), 8: ("rating", 0.89)},                      # S6: 2
    {1: ("confident", 0.92)},                                          # S7: 1
    {2: ("adapts", 0.94)},                                             # S8: 1
]

# System 4: 24 errors, DECENT calibration (errors have LOW confidence)
sys4_errors = [
    {0: ("those", 0.28), 2: ("reported", 0.30), 9: ("sector", 0.25)}, # S1: 3
    {1: ("analyst", 0.32), 2: ("predicted", 0.32), 8: ("region", 0.28)},  # S2: 3
    {0: ("inflations", 0.25), 3: ("significance", 0.28), 8: ("policing", 0.22)},  # S3: 3
    {1: ("negotiation", 0.30), 3: ("majority", 0.28), 9: ("phases", 0.25)},  # S4: 3
    {2: ("exceed", 0.28), 3: ("initially", 0.30), 7: ("currency", 0.25)},  # S5: 3
    {1: ("investment", 0.30), 2: ("continued", 0.30), 3: ("through", 0.25)},  # S6: 3
    {0: ("consumed", 0.25), 3: ("renewing", 0.28), 7: ("futures", 0.22)},  # S7: 3
    {1: ("regulations", 0.28), 5: ("addressed", 0.25), 8: ("digitized", 0.30)},  # S8: 3
]

# Write all CTM files with system-specific calibration patterns
write_ctm("sys1.ctm", REF_SEGMENTS, sys1_errors, 0.91, 0.006)   # Good cal
write_ctm("sys2.ctm", REF_SEGMENTS, sys2_errors, 0.78, 0.008)   # Mediocre cal
write_ctm("sys3.ctm", REF_SEGMENTS, sys3_errors, 0.72, 0.005)   # Anti-cal
write_ctm("sys4.ctm", REF_SEGMENTS, sys4_errors, 0.80, 0.007)   # Decent cal

print("Generated data files in {}:".format(DATA_DIR))
print("  reference.stm")
for s in ["sys1", "sys2", "sys3", "sys4"]:
    print("  {}.ctm".format(s))
total_ref = sum(len(seg[5]) for seg in REF_SEGMENTS)
print("Total reference words: {}".format(total_ref))
