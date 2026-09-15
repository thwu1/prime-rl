"""
Verification tests for the multi-stage scatter-gather log analysis pipeline.

"""

import glob
import math
import os
import random
import subprocess
from collections import Counter

import pytest


def generate_log():
    """Generate a deterministic Apache Combined Log Format file (500 lines)."""
    rng = random.Random(42)

    hosts = [f"192.168.1.{i}" for i in range(1, 16)] + \
            [f"10.0.0.{i}" for i in range(1, 11)]

    pages = ["/", "/index.html", "/about", "/contact", "/api/v1/users",
             "/api/v1/posts", "/images/logo.png", "/css/style.css",
             "/js/app.js", "/login", "/register", "/dashboard",
             "/admin", "/search", "/api/v2/data", "/docs",
             "/favicon.ico", "/robots.txt", "/sitemap.xml", "/health"]

    days = ["01/Oct/2016", "02/Oct/2016", "03/Oct/2016",
            "04/Oct/2016", "05/Oct/2016"]

    status_choices = [200] * 7 + [301, 302, 404, 500]
    user_agents = ["Mozilla/5.0", "curl/7.68.0", "python-requests/2.25.1"]
    methods = ["GET"] * 4 + ["POST", "PUT"]

    lines = []
    for _ in range(500):
        host = rng.choice(hosts)
        day = rng.choice(days)
        hour = rng.randint(0, 23)
        minute = rng.randint(0, 59)
        second = rng.randint(0, 59)
        page = rng.choice(pages)
        status = rng.choice(status_choices)
        size = rng.randint(100, 50000)
        method = rng.choice(methods)
        ua = rng.choice(user_agents)

        timestamp = f"[{day}:{hour:02d}:{minute:02d}:{second:02d} +0000]"
        line = (f'{host} - - {timestamp} "{method} {page} HTTP/1.1" '
                f'{status} {size} "-" "{ua}"')
        lines.append(line)

    return "\n".join(lines) + "\n"


def compute_expected(log_text):
    """Compute all expected metric values from the raw log text."""
    lines = [l for l in log_text.strip().split("\n") if l]

    total_requests = len(lines)
    all_hosts = []
    all_pages = []
    all_bytes = []
    all_dates = []
    all_hours = []
    all_status = []
    host_bytes = {}
    all_sizes = []

    for line in lines:
        parts = line.split()
        host = parts[0]
        all_hosts.append(host)

        page = parts[6]
        all_pages.append(page)

        byte_count = int(parts[9])
        all_bytes.append(byte_count)
        all_sizes.append(byte_count)

        # $4 = [DD/Mon/YYYY:HH:MM:SS  ->  positions [1:12] = DD/Mon/YYYY
        date_str = parts[3][1:12]
        all_dates.append(date_str)

        hour_str = parts[3][13:15]
        all_hours.append(hour_str)

        status = parts[8]
        all_status.append(status)

        host_bytes[host] = host_bytes.get(host, 0) + byte_count

    total_bytes = sum(all_bytes)
    unique_hosts = len(set(all_hosts))
    unique_pages = len(set(all_pages))
    unique_days = len(set(all_dates))

    requests_per_day = total_requests / unique_days
    mbytes_per_day = total_bytes / unique_days / 1048576

    # Status classes
    status_counts = Counter(all_status)
    status_2xx = sum(v for k, v in status_counts.items() if k.startswith("2"))
    status_3xx = sum(v for k, v in status_counts.items() if k.startswith("3"))
    status_4xx = sum(v for k, v in status_counts.items() if k.startswith("4"))
    status_5xx = sum(v for k, v in status_counts.items() if k.startswith("5"))

    error_rate = (status_4xx + status_5xx) / total_requests * 100

    # Percentiles (nearest-rank method)
    sorted_sizes = sorted(all_sizes)
    n = len(sorted_sizes)
    p50 = sorted_sizes[math.ceil(n * 0.50) - 1]
    p95 = sorted_sizes[math.ceil(n * 0.95) - 1]
    p99 = sorted_sizes[math.ceil(n * 0.99) - 1]

    return {
        "total_requests": total_requests,
        "total_bytes": total_bytes,
        "unique_hosts": unique_hosts,
        "unique_pages": unique_pages,
        "unique_days": unique_days,
        "requests_per_day": f"{requests_per_day:.2f}",
        "mbytes_per_day": f"{mbytes_per_day:.6f}",
        "error_rate": f"{error_rate:.2f}",
        "host_counts": Counter(all_hosts),
        "page_counts": Counter(all_pages),
        "status_counts": status_counts,
        "hour_counts": Counter(all_hours),
        "host_bytes": host_bytes,
        "status_2xx": status_2xx,
        "status_3xx": status_3xx,
        "status_4xx": status_4xx,
        "status_5xx": status_5xx,
        "p50": p50,
        "p95": p95,
        "p99": p99,
    }


def run_analyzer(log_text):
    """Run /app/analyze.sh with log_text piped to stdin."""
    result = subprocess.run(
        ["bash", "/app/analyze.sh"],
        input=log_text,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result


def parse_output(output):
    """Parse analyzer output into summary dict and section dict."""
    lines = output.strip().split("\n")
    summary = {}
    sections = {}
    current_section = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("---") and stripped.endswith("---"):
            current_section = stripped.strip("-")
            sections[current_section] = []
        elif current_section is not None:
            if stripped:
                sections[current_section].append(line)
        elif ":" in line and not line.startswith("---"):
            key, _, val = line.partition(":")
            summary[key.strip()] = val.strip()

    return summary, sections


def parse_count_value(line):
    """Parse a 'count value' line (handles leading whitespace from uniq -c)."""
    parts = line.strip().split(None, 1)
    return int(parts[0]), parts[1]


# ---------------------------------------------------------------------------
# Shared fixture: generate data, run analyzer once, parse output
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def analysis():
    log_text = generate_log()
    os.makedirs("/app/data", exist_ok=True)
    with open("/app/data/access.log", "w") as f:
        f.write(log_text)

    expected = compute_expected(log_text)
    result = run_analyzer(log_text)
    summary, sections = parse_output(result.stdout)
    return result, summary, sections, expected


# ---------------------------------------------------------------------------
# Structural tests: verify required tool usage
# ---------------------------------------------------------------------------

def test_uses_flock():
    """Verify that analyze.sh uses flock for inter-process synchronization."""
    with open("/app/analyze.sh") as f:
        script = f.read()
    assert "flock" in script, (
        "analyze.sh must use flock(1) for inter-process store synchronization"
    )


def test_uses_bc():
    """Verify that analyze.sh uses bc for floating-point arithmetic."""
    with open("/app/analyze.sh") as f:
        script = f.read()
    assert "| bc" in script or "bc <<" in script or "bc -l" in script, (
        "analyze.sh must use bc(1) for floating-point derived metric computation"
    )


# ---------------------------------------------------------------------------
# Runtime correctness tests
# ---------------------------------------------------------------------------

def test_script_runs(analysis):
    result, _, _, _ = analysis
    assert result.returncode == 0, (
        f"analyze.sh exited with code {result.returncode}.\n"
        f"stderr: {result.stderr[:500]}"
    )


def test_total_requests(analysis):
    _, summary, _, expected = analysis
    assert summary.get("TOTAL_REQUESTS") == str(expected["total_requests"]), (
        f"got '{summary.get('TOTAL_REQUESTS')}', "
        f"expected '{expected['total_requests']}'"
    )


def test_total_bytes(analysis):
    _, summary, _, expected = analysis
    assert summary.get("TOTAL_BYTES") == str(expected["total_bytes"]), (
        f"got '{summary.get('TOTAL_BYTES')}', "
        f"expected '{expected['total_bytes']}'"
    )


def test_unique_hosts(analysis):
    _, summary, _, expected = analysis
    assert summary.get("UNIQUE_HOSTS") == str(expected["unique_hosts"]), (
        f"got '{summary.get('UNIQUE_HOSTS')}', "
        f"expected '{expected['unique_hosts']}'"
    )


def test_unique_pages(analysis):
    _, summary, _, expected = analysis
    assert summary.get("UNIQUE_PAGES") == str(expected["unique_pages"]), (
        f"got '{summary.get('UNIQUE_PAGES')}', "
        f"expected '{expected['unique_pages']}'"
    )


def test_unique_days(analysis):
    _, summary, _, expected = analysis
    assert summary.get("UNIQUE_DAYS") == str(expected["unique_days"]), (
        f"got '{summary.get('UNIQUE_DAYS')}', "
        f"expected '{expected['unique_days']}'"
    )


def test_requests_per_day(analysis):
    _, summary, _, expected = analysis
    assert summary.get("REQUESTS_PER_DAY") == expected["requests_per_day"], (
        f"got '{summary.get('REQUESTS_PER_DAY')}', "
        f"expected '{expected['requests_per_day']}'"
    )


def test_mbytes_per_day(analysis):
    _, summary, _, expected = analysis
    assert summary.get("MBYTES_PER_DAY") == expected["mbytes_per_day"], (
        f"got '{summary.get('MBYTES_PER_DAY')}', "
        f"expected '{expected['mbytes_per_day']}'"
    )


def test_error_rate(analysis):
    _, summary, _, expected = analysis
    assert summary.get("ERROR_RATE") == expected["error_rate"], (
        f"got '{summary.get('ERROR_RATE')}', "
        f"expected '{expected['error_rate']}'"
    )


def test_top_hosts_by_requests(analysis):
    _, _, sections, expected = analysis
    section = sections.get("TOP_HOSTS_BY_REQUESTS", [])
    assert len(section) == 10, f"Expected 10 entries, got {len(section)}"

    prev_count = float("inf")
    listed_hosts = set()
    for line in section:
        count, host = parse_count_value(line)
        assert count <= prev_count, "Not sorted descending by count"
        assert expected["host_counts"][host] == count, (
            f"Host {host}: got count {count}, "
            f"expected {expected['host_counts'][host]}"
        )
        listed_hosts.add(host)
        prev_count = count

    # Every host with a higher count than the minimum listed must appear
    min_listed = min(parse_count_value(line)[0] for line in section)
    for host, cnt in expected["host_counts"].items():
        if cnt > min_listed:
            assert host in listed_hosts, (
                f"Host {host} (count={cnt}) should be in top 10"
            )


def test_top_hosts_by_bytes(analysis):
    _, _, sections, expected = analysis
    section = sections.get("TOP_HOSTS_BY_BYTES", [])
    assert len(section) == 10, f"Expected 10 entries, got {len(section)}"

    prev_bytes = float("inf")
    for line in section:
        byte_val, host = parse_count_value(line)
        assert byte_val <= prev_bytes, "Not sorted descending by bytes"
        assert expected["host_bytes"][host] == byte_val, (
            f"Host {host}: got bytes {byte_val}, "
            f"expected {expected['host_bytes'][host]}"
        )
        prev_bytes = byte_val


def test_top_pages(analysis):
    _, _, sections, expected = analysis
    section = sections.get("TOP_PAGES", [])
    assert len(section) == 10, f"Expected 10 entries, got {len(section)}"

    prev_count = float("inf")
    for line in section:
        count, page = parse_count_value(line)
        assert count <= prev_count, "Not sorted descending by count"
        assert expected["page_counts"][page] == count, (
            f"Page {page}: got count {count}, "
            f"expected {expected['page_counts'][page]}"
        )
        prev_count = count


def test_status_codes(analysis):
    _, _, sections, expected = analysis
    section = sections.get("STATUS_CODES", [])
    assert len(section) == len(expected["status_counts"]), (
        f"Expected {len(expected['status_counts'])} status codes, "
        f"got {len(section)}"
    )

    prev_count = float("inf")
    seen_codes = set()
    for line in section:
        count, code = parse_count_value(line)
        assert count <= prev_count, "Not sorted descending"
        assert expected["status_counts"][code] == count, (
            f"Status {code}: got {count}, "
            f"expected {expected['status_counts'][code]}"
        )
        seen_codes.add(code)
        prev_count = count

    assert seen_codes == set(expected["status_counts"].keys()), (
        "Missing or extra status codes"
    )


def test_status_classes(analysis):
    _, _, sections, expected = analysis
    section = sections.get("STATUS_CLASSES", [])
    assert len(section) == 4, f"Expected 4 status class entries, got {len(section)}"

    classes = {}
    for line in section:
        key, _, val = line.strip().partition(":")
        classes[key] = int(val)

    assert classes.get("2xx") == expected["status_2xx"], (
        f"2xx: got {classes.get('2xx')}, expected {expected['status_2xx']}"
    )
    assert classes.get("3xx") == expected["status_3xx"], (
        f"3xx: got {classes.get('3xx')}, expected {expected['status_3xx']}"
    )
    assert classes.get("4xx") == expected["status_4xx"], (
        f"4xx: got {classes.get('4xx')}, expected {expected['status_4xx']}"
    )
    assert classes.get("5xx") == expected["status_5xx"], (
        f"5xx: got {classes.get('5xx')}, expected {expected['status_5xx']}"
    )


def test_hourly_distribution(analysis):
    _, _, sections, expected = analysis
    section = sections.get("HOURLY_DISTRIBUTION", [])

    actual_hours = {}
    prev_hour = -1
    for line in section:
        count, hour = parse_count_value(line)
        hour_int = int(hour)
        assert hour_int > prev_hour, (
            f"Not sorted ascending: hour {hour} after {prev_hour}"
        )
        actual_hours[hour] = count
        prev_hour = hour_int

    for hour_str, exp_count in expected["hour_counts"].items():
        assert actual_hours.get(hour_str) == exp_count, (
            f"Hour {hour_str}: got {actual_hours.get(hour_str)}, "
            f"expected {exp_count}"
        )


def test_response_size_percentiles(analysis):
    _, _, sections, expected = analysis
    section = sections.get("RESPONSE_SIZE_PERCENTILES", [])
    assert len(section) >= 3, (
        f"Expected at least 3 percentile entries, got {len(section)}"
    )

    pctls = {}
    for line in section:
        key, _, val = line.strip().partition(":")
        if val:
            pctls[key] = int(val)

    assert pctls.get("P50") == expected["p50"], (
        f"P50: got {pctls.get('P50')}, expected {expected['p50']}"
    )
    assert pctls.get("P95") == expected["p95"], (
        f"P95: got {pctls.get('P95')}, expected {expected['p95']}"
    )
    assert pctls.get("P99") == expected["p99"], (
        f"P99: got {pctls.get('P99')}, expected {expected['p99']}"
    )


# ---------------------------------------------------------------------------
# Determinism test: race-condition detector
# ---------------------------------------------------------------------------

def test_deterministic_output():
    """Run analyzer 3 times and verify outputs are identical (race-free)."""
    log_text = generate_log()
    outputs = []
    for _ in range(3):
        result = run_analyzer(log_text)
        assert result.returncode == 0, (
            f"analyze.sh failed on run: {result.stderr[:300]}"
        )
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1] == outputs[2], (
        "Non-deterministic output detected — possible race condition "
        "in inter-process synchronization"
    )


# ---------------------------------------------------------------------------
# Cleanup test: verify temp resource removal
# ---------------------------------------------------------------------------

def test_cleanup():
    """Verify that analyze.sh cleans up temporary resources on exit."""
    log_text = generate_log()
    before = (
        set(glob.glob("/tmp/logpipe.*"))
        | set(glob.glob("/tmp/logstore.*"))
        | set(glob.glob("/tmp/loglock.*"))
    )
    result = run_analyzer(log_text)
    assert result.returncode == 0
    after = (
        set(glob.glob("/tmp/logpipe.*"))
        | set(glob.glob("/tmp/logstore.*"))
        | set(glob.glob("/tmp/loglock.*"))
    )
    new_dirs = after - before
    assert len(new_dirs) == 0, (
        f"Temporary directories not cleaned up: {new_dirs}"
    )


# ---------------------------------------------------------------------------
# Small-input edge case
# ---------------------------------------------------------------------------

def test_small_input():
    """Verify with a small hand-crafted 3-line log."""
    log = (
        '1.2.3.4 - - [10/Nov/2020:12:30:00 +0000] '
        '"GET /page1 HTTP/1.1" 200 1000 "-" "bot"\n'
        '1.2.3.4 - - [10/Nov/2020:13:45:00 +0000] '
        '"GET /page2 HTTP/1.1" 404 500 "-" "bot"\n'
        '5.6.7.8 - - [11/Nov/2020:12:15:00 +0000] '
        '"GET /page1 HTTP/1.1" 200 2000 "-" "bot"\n'
    )

    result = run_analyzer(log)
    assert result.returncode == 0, f"Failed: {result.stderr[:300]}"
    summary, sections = parse_output(result.stdout)

    # Summary metrics
    assert summary["TOTAL_REQUESTS"] == "3"
    assert summary["TOTAL_BYTES"] == "3500"
    assert summary["UNIQUE_HOSTS"] == "2"
    assert summary["UNIQUE_PAGES"] == "2"
    assert summary["UNIQUE_DAYS"] == "2"
    assert summary["REQUESTS_PER_DAY"] == "1.50"

    # 3500 / 2 / 1048576 = 0.0016689300537109375 -> "0.001669"
    assert summary["MBYTES_PER_DAY"] == "0.001669"

    # Error rate: 1 error (404) out of 3 requests = 33.33%
    assert summary["ERROR_RATE"] == "33.33"

    # Status classes
    sc_section = sections.get("STATUS_CLASSES", [])
    sc = {}
    for line in sc_section:
        k, _, v = line.strip().partition(":")
        sc[k] = int(v)
    assert sc.get("2xx") == 2
    assert sc.get("3xx") == 0
    assert sc.get("4xx") == 1
    assert sc.get("5xx") == 0

    # Percentiles: sorted sizes = [500, 1000, 2000]
    # P50: ceil(3*0.50)=2 -> 1000
    # P95: ceil(3*0.95)=3 -> 2000
    # P99: ceil(3*0.99)=3 -> 2000
    p_section = sections.get("RESPONSE_SIZE_PERCENTILES", [])
    pctls = {}
    for line in p_section:
        k, _, v = line.strip().partition(":")
        if v:
            pctls[k] = int(v)
    assert pctls.get("P50") == 1000, f"P50: got {pctls.get('P50')}"
    assert pctls.get("P95") == 2000, f"P95: got {pctls.get('P95')}"
    assert pctls.get("P99") == 2000, f"P99: got {pctls.get('P99')}"
