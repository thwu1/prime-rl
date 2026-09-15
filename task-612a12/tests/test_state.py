"""Tests for the metrics collector cascade failure debugging task.

Verifies that the agent has:
1. Fixed all collector source bugs (log buffering, size validation,
   memory leak, socket FD leak)
2. Fixed the endpoint configuration (removed HTTP endpoint)
3. Written a post-incident analysis with severity evaluation
4. Created a protocol health-check script
5. The collector compiles and handles HTTP responses gracefully
"""


import subprocess
import os
import re
import socket
import time
import threading
import signal
import pytest


# ---------------------------------------------------------------------------
# Source code static analysis tests
# ---------------------------------------------------------------------------

def test_collector_compiles():
    """The fixed collector.c must compile without errors."""
    result = subprocess.run(
        ['gcc', '-o', '/tmp/collector_test', '/app/collector.c'],
        capture_output=True, timeout=30
    )
    assert result.returncode == 0, (
        f"Compilation failed:\n{result.stderr.decode()}"
    )


def test_has_log_line_buffering():
    """collector.c must ensure log output survives abnormal termination."""
    with open('/app/collector.c') as f:
        source = f.read()

    patterns = [
        r'setlinebuf\s*\(',
        r'setvbuf\s*\([^)]*_IOLBF',
        r'setvbuf\s*\([^)]*_IONBF',
        r'setbuf\s*\(\s*logfp\s*,\s*NULL',
        r'fflush\s*\(\s*logfp\s*\)',
    ]
    found = any(re.search(p, source) for p in patterns)
    assert found, (
        "Log output must be line-buffered or explicitly flushed after each "
        "message. Without this, log data is lost when the process is killed "
        "by SIGKILL because stdio buffers are never flushed."
    )


def test_has_message_size_limit():
    """collector.c must reject unreasonably large payload sizes before malloc."""
    with open('/app/collector.c') as f:
        source = f.read()

    patterns = [
        r'msg_len\s*>\s*[A-Z_]+',
        r'msg_len\s*>=\s*[A-Z_]+',
        r'msg_len\s*>\s*\d{4,}',
        r'msg_len\s*>=\s*\d{4,}',
        r'MAX_PAYLOAD',
        r'MAX_MSG_SIZE',
        r'MAX_MESSAGE_SIZE',
        r'MAX_BUFFER',
        r'max_payload',
        r'msg_len\s*>\s*\(\s*\d',
    ]
    found = any(re.search(p, source) for p in patterns)
    assert found, (
        "No message size validation found. The collector must check msg_len "
        "against a maximum before calling malloc()."
    )


def test_truncation_path_frees_memory():
    """The truncation error path must free the allocated buffer."""
    with open('/app/collector.c') as f:
        source = f.read()

    idx = source.find('Truncated')
    assert idx != -1, "Cannot find truncation handling code"

    after_trunc = source[idx:]
    ret_idx = after_trunc.find('return')
    assert ret_idx != -1, "Cannot find return after truncation"

    cleanup_section = after_trunc[:ret_idx]

    has_free = 'free(' in cleanup_section
    has_goto = bool(re.search(r'goto\s+\w+', cleanup_section))

    assert has_free or has_goto, (
        "Truncation error path must free(buf) before returning. "
        "The leaked buffer is the primary memory leak causing OOM kills."
    )


def test_truncation_path_closes_socket():
    """The truncation error path must close the socket file descriptor."""
    with open('/app/collector.c') as f:
        source = f.read()

    idx = source.find('Truncated')
    assert idx != -1, "Cannot find truncation handling code"

    after_trunc = source[idx:]
    ret_idx = after_trunc.find('return')
    assert ret_idx != -1, "Cannot find return after truncation"

    cleanup_section = after_trunc[:ret_idx]

    has_close = 'close(' in cleanup_section
    has_goto = bool(re.search(r'goto\s+\w+', cleanup_section))

    assert has_close or has_goto, (
        "Truncation error path must close(sock) before returning. "
        "Leaked file descriptors cause fd exhaustion over time."
    )


# ---------------------------------------------------------------------------
# Configuration test
# ---------------------------------------------------------------------------

def test_config_endpoint_fixed():
    """The endpoint config must not poll the HTTP service on port 9003."""
    config_path = '/app/config/endpoints.conf'
    assert os.path.exists(config_path), f"Config file missing: {config_path}"

    with open(config_path) as f:
        lines = f.readlines()

    active = [
        line.strip() for line in lines
        if line.strip() and not line.strip().startswith('#')
    ]

    has_9003 = any('9003' in line for line in active)
    assert not has_9003, (
        "Port 9003 (HTTP service) is still active in endpoints.conf."
    )


# ---------------------------------------------------------------------------
# Postmortem analysis tests
# ---------------------------------------------------------------------------

def test_postmortem_exists():
    """A post-incident analysis must exist at /app/postmortem.md."""
    assert os.path.exists('/app/postmortem.md'), \
        "No postmortem found at /app/postmortem.md"


def test_postmortem_decodes_magic_number():
    """Postmortem must decode the anomalous value as ASCII 'HTTP'."""
    with open('/app/postmortem.md') as f:
        content = f.read()

    content_lower = content.lower().replace(' ', '')

    has_decimal = '1213486160' in content
    has_hex = '48545450' in content_lower
    assert has_decimal or has_hex, (
        "Postmortem must reference the magic number: "
        "1213486160 (decimal) or 0x48545450 (hex)"
    )

    assert 'http' in content.lower(), (
        "Postmortem must explain that the number decodes to 'HTTP'"
    )


def test_postmortem_identifies_causal_chain():
    """Postmortem must discuss the full causal chain including all bug categories."""
    with open('/app/postmortem.md') as f:
        content = f.read().lower()

    # Must mention the log buffering issue
    has_log_issue = (
        any(t in content for t in [
            'buffer', 'flush', 'fflush', 'setlinebuf', 'setvbuf',
            'unbuffer', 'line-buffer', 'line buffer', 'stdio'
        ]) or
        bool(re.search(r'log.{0,30}(buffer|flush|lost|missing)', content))
    )
    assert has_log_issue, (
        "Postmortem must discuss why collector logs were missing "
        "(stdio buffering issue with SIGKILL)"
    )

    # Must mention memory leak
    has_mem = (
        any(t in content for t in [
            'memory leak', 'mem leak', 'not freed',
            'never freed', 'leaked memory'
        ]) or
        bool(re.search(r'(memory|buffer).{0,20}leak', content))
    )
    assert has_mem, "Postmortem must discuss the memory leak"

    # Must mention fd/socket leak
    has_fd = (
        any(t in content for t in [
            'file descriptor', 'fd leak', 'socket leak',
            'descriptor leak', 'socket not closed',
            'leaked socket', 'leaked fd', 'resource leak',
            'fd exhaustion', 'file descriptor leak'
        ]) or
        bool(re.search(
            r'(socket|fd|file.descriptor).{0,20}(leak|not.close|exhaust)',
            content
        ))
    )
    assert has_fd, (
        "Postmortem must discuss the file descriptor/socket leak"
    )


def test_postmortem_evaluates_severity():
    """Postmortem must evaluate the severity/impact of each contributing bug."""
    with open('/app/postmortem.md') as f:
        content = f.read().lower()

    severity_terms = [
        'severity', 'impact', 'critical', 'root cause',
        'primary', 'contributing', 'amplif', 'cascade',
        'secondary', 'trigger'
    ]
    found = sum(1 for t in severity_terms if t in content)
    assert found >= 3, (
        f"Postmortem must evaluate severity/impact of bugs. "
        f"Expected at least 3 severity-related terms, found {found}."
    )


# ---------------------------------------------------------------------------
# Health-check script tests
# ---------------------------------------------------------------------------

def test_healthcheck_exists_and_executable():
    """healthcheck.sh must exist and be executable."""
    path = '/app/healthcheck.sh'
    assert os.path.exists(path), f"healthcheck.sh not found at {path}"
    assert os.access(path, os.X_OK), f"{path} is not executable"


def test_healthcheck_detects_mismatch():
    """healthcheck.sh must correctly identify the HTTP protocol mismatch."""
    # Create test config with all 4 endpoints including the problematic one
    test_config = '/tmp/test_all_endpoints.conf'
    with open(test_config, 'w') as f:
        f.write("svc-alpha   127.0.0.1 9001\n")
        f.write("svc-beta    127.0.0.1 9002\n")
        f.write("svc-gamma   127.0.0.1 9003\n")
        f.write("svc-delta   127.0.0.1 9004\n")

    result = subprocess.run(
        ['/app/healthcheck.sh', test_config],
        capture_output=True, text=True, timeout=30
    )

    output = (result.stdout + result.stderr).lower()

    # Must identify port 9003 or svc-gamma as problematic
    problem_words = [
        'http', 'mismatch', 'invalid', 'error', 'wrong',
        'fail', 'bad', 'unexpected', 'incompatible', 'suspect'
    ]
    has_problem = (
        ('9003' in output or 'gamma' in output) and
        any(w in output for w in problem_words)
    )
    assert has_problem, (
        f"healthcheck.sh did not identify port 9003/svc-gamma as mismatched.\n"
        f"Output: {result.stdout[:500]}"
    )

    # Must identify at least one working endpoint
    ok_words = [
        'ok', 'pass', 'valid', 'binary', 'healthy',
        'success', 'good', 'correct'
    ]
    has_ok = any(w in output for w in ok_words)
    assert has_ok, (
        f"healthcheck.sh did not identify any working endpoints.\n"
        f"Output: {result.stdout[:500]}"
    )


# ---------------------------------------------------------------------------
# Integration / runtime test
# ---------------------------------------------------------------------------

def test_collector_handles_http_gracefully():
    """The fixed collector must not consume excessive resources with HTTP responses."""
    compile_result = subprocess.run(
        ['gcc', '-o', '/tmp/collector_graceful', '/app/collector.c'],
        capture_output=True, timeout=30
    )
    if compile_result.returncode != 0:
        pytest.skip("Cannot test: compilation failed")

    # Start a mock HTTP responder on an ephemeral port
    port = 19876
    server_ready = threading.Event()

    def http_responder():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1', port))
        s.listen(5)
        s.settimeout(30)
        server_ready.set()
        try:
            for _ in range(20):
                conn, _ = s.accept()
                conn.sendall(
                    b"HTTP/1.0 200 OK\r\n"
                    b"Content-Type: text/plain\r\n"
                    b"\r\n"
                    b"OK\n"
                )
                time.sleep(0.5)
                conn.close()
        except socket.timeout:
            pass
        finally:
            s.close()

    t = threading.Thread(target=http_responder, daemon=True)
    t.start()
    server_ready.wait(timeout=5)
    time.sleep(0.5)

    test_conf = '/tmp/test_http_endpoints.conf'
    with open(test_conf, 'w') as f:
        f.write(f"http-test 127.0.0.1 {port}\n")

    proc = subprocess.Popen(
        ['/tmp/collector_graceful', test_conf],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    try:
        time.sleep(12)

        if proc.poll() is None:
            try:
                with open(f'/proc/{proc.pid}/status') as f:
                    status = f.read()
                rss_match = re.search(r'VmRSS:\s+(\d+)\s+kB', status)
                vmsz_match = re.search(r'VmSize:\s+(\d+)\s+kB', status)
                if rss_match:
                    rss_kb = int(rss_match.group(1))
                    assert rss_kb < 102400, (
                        f"Collector RSS is {rss_kb} kB (~{rss_kb // 1024} MB). "
                        f"Should be under 100 MB with HTTP responses."
                    )
                if vmsz_match:
                    vmsz_kb = int(vmsz_match.group(1))
                    assert vmsz_kb < 524288, (
                        f"Collector VmSize is {vmsz_kb} kB (~{vmsz_kb // 1024} MB). "
                        f"Should be under 512 MB — size validation not working."
                    )
            except FileNotFoundError:
                pass  # Process already exited, acceptable
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
