"""
Tests for the MVS (Minimal Version Selection) CLI tool.
Scenarios derived from Go's official MVS test suite.
"""

import subprocess
import tempfile
import os
import pytest

BINARY = "/app/mvs"

TEST_DATA = r"""
name: blog
A: B1 C2
B1: D3
C1: D2
C2: D4
C3: D5
C4: G1
D2: E1
D3: E2
D4: E2 F1
D5: E2
G1: C4
A2: B1 C4 D4
build A:       A B1 C2 D4 E2 F1
upgrade* A:    A B1 C4 D5 E2 F1 G1
upgrade A C4:  A B1 C4 D4 E2 F1 G1
build A2:     A2 B1 C4 D4 E2 F1 G1
downgrade A2 D2: A2 C4 D2 E2 F1 G1

name: trim
A: B1 C2
B1: D3
C2: B2
B2:
build A: A B2 C2 D3

name: cross1
A: B C
B: D1
C: D2
D1: E2
D2: E1
build A: A B C D2 E2

name: cross1V
A: B2 C D2 E1
B1:
B2: D1
C: D2
D1: E2
D2: E1
build A: A B2 C D2 E2

name: cross1U
A: B1 C
B1:
B2: D1
C: D2
D1: E2
D2: E1
build A:      A B1 C D2 E1
upgrade A B2: A B2 C D2 E2

name: cross1R
A: B C
B: D2
C: D1
D1: E2
D2: E1
build A: A B C D2 E2

name: cross1X
A: B C
B: D1 E2
C: D2
D1: E2
D2: E1
build A: A B C D2 E2

name: cross2
A: B D2
B: D1
D1: E2
D2: E1
build A: A B D2 E2

name: cross2X
A: B D2
B: D1 E2
C: D2
D1: E2
D2: E1
build A: A B D2 E2

name: cross3
A: B D2 E1
B: D1
D1: E2
D2: E1
build A: A B D2 E2

name: cross3X
A: B D2 E1
B: D1 E2
D1: E2
D2: E1
build A: A B D2 E2

name: cross4
A1: B1 D2
A2: B2 D2
B1: D1
B2: D2
D1: E2
D2: E1
build A1: A1 B1 D2 E2
build A2: A2 B2 D2 E1
upgrade A1 B2: A1 B2 D2 E2

name: cross5
A: D1
D1: E2
D2: E1
build A:       A D1 E2
upgrade* A:    A D2 E2
upgrade A D2:  A D2 E2

name: cross6
A: D2
D1: E2
D2: E1
build A:      A D2 E1
upgrade* A:   A D2 E2
upgrade A E2: A D2 E2

name: cross7
A: B C
B: D1
C: E1
D1: E2
E1: D2
build A: A B C D2 E2

name: cross8
M: A1 B1
A1: X1
B1: X2
X1: I1
X2:
build M: M A1 B1 I1 X2

name: drop
A: B1 C1
B1: D1
B2:
C2:
D2:
build A:    A B1 C1 D1
upgrade* A: A B2 C2 D2

name: simplify
A: B1 C1
B1: C2
C1: D1
C2:
build A: A B1 C2 D1

name: up1
A: B1 C1
B1:
B2:
B3:
B4:
B5.hidden:
C2:
C3:
build A:    A B1 C1
upgrade* A: A B4 C3

name: up2
A: B5.hidden C1
B1:
B2:
B3:
B4:
B5.hidden:
C2:
C3:
build A:    A B5.hidden C1
upgrade* A: A B5.hidden C3

name: down1
A: B2
B1: C1
B2: C2
build A:        A B2 C2
downgrade A C1: A B1 C1

name: down2
A: B2 E2
B1:
B2: C2 F2
C1:
D1:
C2: D2 E2
D2: B2
E2: D2
E1:
F1:
build A:        A B2 C2 D2 E2 F2
downgrade A F1: A B1 C1 D1 E1 F1

name: downcross1
A: B2 C1
B1: C2
B2: C1
C1: D2
C2:
D1:
D2:
build A:        A B2 C1 D2
downgrade A D1: A       D1

name: downcross2
A: B2
B1: C1
B2: D2
C1:
D1:
D2:
build A:        A B2    D2
downgrade A D1: A B1 C1 D1

name: downcycle
A: A B2
B2: A
B1:
build A:        A B2
downgrade A B1: A B1

name: downhiddenartifact
A: B3 C2
A1: B3
B1: E1
B2.hidden:
B3: D2
C1: B2.hidden
C2: D2
D1:
D2:
build A1: A1 B3 D2
downgrade A1 D1: A1 B1 D1 E1
build A: A B3 C2 D2
downgrade A D1: A B2.hidden C1 D1

name: downhiddencross
A: B3 C3
B1: C2.hidden
B2.hidden:
B3: D2
C1: B2.hidden
C2.hidden:
C3: D2
D1:
D2:
build A: A B3 C3 D2
downgrade A D1: A B2.hidden C2.hidden D1

name: noprev1
A: B4 C2
B2.hidden:
C2:
build A:               A B4        C2
downgrade A B2.hidden: A B2.hidden C2

name: noprev2
A: B4 C2
B2.hidden:
B1:
C2:
build A:               A B4        C2
downgrade A B2.hidden: A B2.hidden C2

name: noprev3
A: B4 C2
B3:
B2.hidden:
C2:
build A:               A B4        C2
downgrade A B2.hidden: A B2.hidden C2

name: cycle1
A: B1
B1: A1
B2: A2
B3: A3
build A:      A B1
upgrade A B2: A B2
upgrade* A:   A B3

name: cycle2
A: B1
A1: C1
A2: D1
B1: A1
B2: A2
C1: A2
C2:
D2:
build A:    A B1 C1 D1
upgrade* A: A B2 C2 D2

name: cycle3
M: A1 C2
A1: B1
B1: C1
B2: C2
C1:
C2: B2
build M: M A1 B2 C2
req M:     A1 B2
req M A:   A1 B2
req M C:   A1 C2

name: req1
A: B1 C1 D1 E1 F1
B1: C1 E1 F1
req A:   B1    D1
req A C: B1 C1 D1

name: req2
A: G1 H1
G1: H1
H1: G1
req A:   G1
req A G: G1
req A H: H1

name: req3
M: A1 B1
A1: X1
B1: X2
X1: I1
X2:
req M: A1 B1

name: reqnone
M: Anone B1 D1 E1
B1: Cnone D1
E1: Fnone
build M: M B1 D1 E1
req M:     B1    E1

name: reqdup
M: A1 B1
A1: B1
B1:
req M A A: A1

name: reqcross
M: A1 B1 C1
A1: B1 C1
B1: C1
C1:
req M A B: A1 B1
"""


def parse_test_data(data):
    """Parse the test data string into a list of scenarios."""
    scenarios = []
    current = None

    for line in data.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        colon_idx = line.index(":")
        key = line[:colon_idx].strip()
        val = line[colon_idx + 1:].strip()

        fields = key.split()

        if fields[0] == "name":
            if current is not None:
                scenarios.append(current)
            current = {"name": val, "graph": [], "tests": []}
        elif fields[0] in ("build", "upgrade*", "upgrade", "downgrade", "req"):
            cmd = fields[0]
            args = fields[1:]
            current["tests"].append((cmd, args, val))
        elif fields[0] == "upgradereq":
            pass  # Skip compound operation tests
        else:
            # Module definition line
            current["graph"].append(line)

    if current is not None:
        scenarios.append(current)

    return scenarios


SCENARIOS = parse_test_data(TEST_DATA)


def write_graph_file(graph_lines):
    """Write graph lines to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".graph", prefix="mvs_")
    with os.fdopen(fd, "w") as f:
        for gline in graph_lines:
            f.write(gline + "\n")
    return path


def run_mvs(graph_path, command, args):
    """Run the mvs tool and return stdout stripped."""
    cmd = [BINARY, graph_path, command] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return None, result.stderr.strip()
    return result.stdout.strip(), None


def get_all_test_cases():
    """Generate (scenario, test_case) pairs for parametrization."""
    cases = []
    for s in SCENARIOS:
        for t in s["tests"]:
            cases.append((s, t))
    return cases


def make_test_id(scenario, test_case):
    """Generate a unique test ID."""
    cmd, args, _ = test_case
    cmd_name = cmd.replace("*", "star")
    args_str = "_".join(args) if args else "noargs"
    return f"{scenario['name']}_{cmd_name}_{args_str}"


ALL_CASES = get_all_test_cases()


@pytest.fixture(scope="session", autouse=True)
def build_binary():
    """Compile the Go binary once per session."""
    result = subprocess.run(
        ["go", "build", "-o", BINARY, "."],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Build failed: {result.stderr}"


@pytest.mark.parametrize(
    "scenario,test_case",
    ALL_CASES,
    ids=[make_test_id(s, t) for s, t in ALL_CASES],
)
def test_mvs_operation(scenario, test_case, tmp_path):
    """Test a single MVS operation against expected output."""
    cmd, args, expected = test_case

    # Write the graph to a temp file
    graph_path = str(tmp_path / "graph.txt")
    with open(graph_path, "w") as f:
        for gline in scenario["graph"]:
            f.write(gline + "\n")

    # Map command names for CLI
    if cmd == "upgrade*":
        cli_cmd = "upgrade-all"
    else:
        cli_cmd = cmd

    output, err = run_mvs(graph_path, cli_cmd, args)

    assert output is not None, (
        f"mvs {cli_cmd} failed for scenario '{scenario['name']}': {err}"
    )

    # Normalize whitespace for comparison
    expected_normalized = " ".join(expected.split())
    output_normalized = " ".join(output.split())

    assert output_normalized == expected_normalized, (
        f"Scenario '{scenario['name']}', {cmd} {' '.join(args)}:\n"
        f"  Expected: {expected_normalized}\n"
        f"  Got:      {output_normalized}"
    )
