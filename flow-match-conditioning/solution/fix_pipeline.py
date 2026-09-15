#!/usr/bin/env python3

"""Fix all bugs in the video world-model conditioning pipeline.

Bugs addressed:
1. scheduler.py   - sigma formula missing shift multiplier in numerator
2. geometry.py    - temporal latent dim uses floor instead of ceiling division
3. conditioning.py - mask convention inverted (ref=1 instead of ref=0)
4. normalization.py - multiplies by std instead of dividing
5. inference.py    - CFG formula has wrong base term
6. inference.py    - two-stage split boundary off by one
"""


FIXES = {
    "/app/pipeline/scheduler.py": (
        "sigmas = t / (1.0 + (shift - 1.0) * t)",
        "sigmas = shift * t / (1.0 + (shift - 1.0) * t)",
    ),
    "/app/pipeline/geometry.py": (
        "t = num_frames // temporal_factor",
        "t = (num_frames - 1) // temporal_factor + 1",
    ),
    "/app/pipeline/conditioning.py": (
        "    mask = np.zeros(num_latent_frames, dtype=np.float64)\n"
        "    for idx in ref_indices:\n"
        "        mask[idx] = 1.0",
        "    mask = np.ones(num_latent_frames, dtype=np.float64)\n"
        "    for idx in ref_indices:\n"
        "        mask[idx] = 0.0",
    ),
    "/app/pipeline/normalization.py": [
        (
            "return (x - mean) * std",
            "return (x - mean) / std",
        ),
        (
            "return x / std + mean",
            "return x * std + mean",
        ),
    ],
    "/app/pipeline/inference.py": [
        (
            "return cond + scale * (cond - uncond)",
            "return uncond + scale * (cond - uncond)",
        ),
        (
            "boundary = int(len(sigmas) * ratio) + 1",
            "boundary = int(len(sigmas) * ratio)",
        ),
    ],
}


def apply_fix(path, old, new):
    with open(path, "r") as f:
        content = f.read()
    if old not in content:
        print(f"  WARNING: pattern not found in {path}: {old!r}")
        return False
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    return True


def main():
    for path, fixes in FIXES.items():
        if isinstance(fixes, tuple):
            fixes = [fixes]
        for old, new in fixes:
            ok = apply_fix(path, old, new)
            status = "OK" if ok else "MISS"
            print(f"[{status}] {path}")


if __name__ == "__main__":
    main()
