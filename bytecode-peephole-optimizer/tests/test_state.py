
import subprocess
import os
import struct
import pytest

PROGRAMS = ["fold_and_shift", "control_flow", "nested"]
MJ_DIR = "/app/MicroJava"
PROG_DIR = "/app/programs"
OPT_DIR = "/tmp/optimized"


def run_vm(obj_path):
    """Run a .obj file on the MicroJava VM and return filtered stdout."""
    r = subprocess.run(
        ["java", "-cp", MJ_DIR, "MJ.Run", obj_path],
        capture_output=True, text=True, timeout=30
    )
    lines = r.stdout.split("\n")
    filtered = [l for l in lines if "Completion took" not in l]
    return "\n".join(filtered).rstrip("\n")


def find_optimizer():
    """Search for the optimizer tool under /app."""
    candidates = [
        "/app/optimizer.py",
        "/app/optimize.py",
        "/app/optimizer",
        "/app/optimize",
        "/app/optimizer.sh",
        "/app/optimize.sh",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    for root, _, files in os.walk("/app"):
        if "MicroJava" in root or "programs" in root:
            continue
        for f in files:
            if "optim" in f.lower() and (f.endswith(".py") or f.endswith(".sh")):
                return os.path.join(root, f)
    return None


def run_optimizer(opt_path, in_obj, out_obj):
    """Invoke the optimizer tool."""
    if opt_path.endswith(".py"):
        cmd = ["python3", opt_path, in_obj, out_obj]
    elif opt_path.endswith(".sh"):
        cmd = ["bash", opt_path, in_obj, out_obj]
    else:
        cmd = [opt_path, in_obj, out_obj]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return r.returncode == 0, r.stderr + r.stdout


@pytest.fixture(scope="session", autouse=True)
def optimize_all():
    """Find the optimizer and run it on all test programs."""
    os.makedirs(OPT_DIR, exist_ok=True)
    opt = find_optimizer()
    assert opt is not None, (
        "No optimizer found. Expected at /app/optimizer.py or similar."
    )
    for prog in PROGRAMS:
        in_obj = os.path.join(PROG_DIR, f"{prog}.obj")
        out_obj = os.path.join(OPT_DIR, f"{prog}.obj")
        assert os.path.exists(in_obj), f"Original .obj not found: {in_obj}"
        ok, output = run_optimizer(opt, in_obj, out_obj)
        assert ok, f"Optimizer failed on {prog}:\n{output}"
        assert os.path.exists(out_obj), f"Optimizer did not produce {out_obj}"


@pytest.mark.parametrize("prog", PROGRAMS)
def test_output_correctness(prog):
    """Optimized program must produce identical output to the original."""
    orig_obj = os.path.join(PROG_DIR, f"{prog}.obj")
    opt_obj = os.path.join(OPT_DIR, f"{prog}.obj")
    expected = run_vm(orig_obj)
    actual = run_vm(opt_obj)
    assert expected == actual, (
        f"Output mismatch for {prog}:\n"
        f"--- expected ---\n{expected}\n--- actual ---\n{actual}"
    )


@pytest.mark.parametrize("prog", PROGRAMS)
def test_size_reduction(prog):
    """Optimized .obj must be strictly smaller than the original."""
    orig = os.path.getsize(os.path.join(PROG_DIR, f"{prog}.obj"))
    opt = os.path.getsize(os.path.join(OPT_DIR, f"{prog}.obj"))
    assert opt < orig, (
        f"{prog}: optimized ({opt}B) not smaller than original ({orig}B)"
    )


@pytest.mark.parametrize("prog", PROGRAMS)
def test_minimum_savings(prog):
    """Each program must achieve a minimum byte savings."""
    orig = os.path.getsize(os.path.join(PROG_DIR, f"{prog}.obj"))
    opt = os.path.getsize(os.path.join(OPT_DIR, f"{prog}.obj"))
    savings = orig - opt
    thresholds = {
        "fold_and_shift": 30,
        "control_flow": 15,
        "nested": 20,
    }
    required = thresholds[prog]
    assert savings >= required, (
        f"{prog}: saved only {savings}B, need at least {required}B"
    )


@pytest.mark.parametrize("prog", PROGRAMS)
def test_valid_obj_format(prog):
    """Optimized file must be a valid MicroJava .obj file."""
    path = os.path.join(OPT_DIR, f"{prog}.obj")
    with open(path, "rb") as f:
        data = f.read()
    assert len(data) >= 14, f"{prog}: file too small ({len(data)}B)"
    assert data[:2] == b"MJ", f"{prog}: invalid MJ signature"
    cs = struct.unpack(">i", data[2:6])[0]
    ds = struct.unpack(">i", data[6:10])[0]
    mp = struct.unpack(">i", data[10:14])[0]
    assert cs > 0, f"{prog}: codeSize must be > 0 (got {cs})"
    assert ds >= 0, f"{prog}: dataSize must be >= 0 (got {ds})"
    assert 0 <= mp < cs, f"{prog}: mainPc={mp} out of range [0, {cs})"
    assert len(data) == 14 + cs, (
        f"{prog}: file size {len(data)} != expected {14 + cs}"
    )
