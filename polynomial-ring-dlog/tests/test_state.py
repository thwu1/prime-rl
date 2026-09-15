
import os

EXPECTED_FLAG = "FLAG{p0lyn0m1al_r1ng_f4ct0r1ng_m33ts_p0hl1g_h3llm4n_CRT_d15cr3te_l0g}"


def test_flag_file_exists():
    """The agent must write the recovered flag to /app/flag.txt."""
    assert os.path.isfile("/app/flag.txt"), "/app/flag.txt does not exist"


def test_flag_content():
    """The recovered flag must match the expected value exactly."""
    with open("/app/flag.txt", "r") as f:
        content = f.read().strip()
    assert content == EXPECTED_FLAG, f"Flag mismatch: got {content!r}"


def test_flag_not_empty():
    """flag.txt must not be empty."""
    with open("/app/flag.txt", "r") as f:
        content = f.read().strip()
    assert len(content) > 0, "flag.txt is empty"


def test_flag_format():
    """Flag must follow the FLAG{...} format."""
    with open("/app/flag.txt", "r") as f:
        content = f.read().strip()
    assert content.startswith("FLAG{"), "Flag does not start with FLAG{"
    assert content.endswith("}"), "Flag does not end with }"
