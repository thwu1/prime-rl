
import subprocess
import os


def test_exploit_file_exists():
    """The exploit script must exist at /app/exploit.py."""
    assert os.path.isfile("/app/exploit.py"), \
        "Expected exploit script at /app/exploit.py"


def test_exploit_references_binary():
    """The exploit must interact with the challenge binary, not hardcode the flag."""
    with open("/app/exploit.py") as f:
        code = f.read()
    has_ref = any(t in code for t in ["challenge", "process", "ELF", "elf", "Process"])
    assert has_ref, "Exploit must reference the challenge binary"
    assert "ROPE{p1v0t_g0t_r3s0lv3_r0p_ch41n_m4st3r}" not in code, \
        "Exploit must not hardcode the complete flag"


def test_exploit_produces_correct_flag():
    """Running the exploit must produce /app/flag.txt with the correct flag."""
    if os.path.exists("/app/flag.txt"):
        os.remove("/app/flag.txt")

    result = subprocess.run(
        ["python3", "/app/exploit.py"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd="/app",
    )

    assert os.path.exists("/app/flag.txt"), (
        f"flag.txt not produced. "
        f"stdout={result.stdout[:500]}, stderr={result.stderr[:500]}"
    )

    with open("/app/flag.txt") as f:
        content = f.read().strip()

    assert content == "ROPE{p1v0t_g0t_r3s0lv3_r0p_ch41n_m4st3r}", \
        f"Incorrect flag: {content}"
