"""Tests for the CSP cooperative concurrency Guile Scheme module.

Verifies that /app/csp.scm correctly implements tasks, channels,
select, and a deadlock-detecting scheduler using delimited continuations.

"""

import subprocess
import shutil
import pytest

GUILE = shutil.which("guile") or shutil.which("guile-3.0") or "guile"
GUILE_FLAGS = ["--no-auto-compile", "-L", "/app"]


def run_guile(code, timeout=20):
    result = subprocess.run(
        [GUILE] + GUILE_FLAGS + ["-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


# ---------------------------------------------------------------------------
# Module loading
# ---------------------------------------------------------------------------

def test_module_loads():
    r = run_guile('(use-modules (csp)) (display "ok")')
    assert r.returncode == 0, f"Module failed to load: {r.stderr}"
    assert r.stdout.strip() == "ok"


# ---------------------------------------------------------------------------
# Task basics
# ---------------------------------------------------------------------------

def test_spawn_and_run_simple():
    """Tasks that don't yield complete immediately."""
    r = run_guile(
        "(use-modules (csp))"
        "(let* ((t1 (spawn (lambda () 10)))"
        "       (t2 (spawn (lambda () 20)))"
        "       (results (run-scheduler (list t1 t2))))"
        "  (display (sort results <)))"
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert r.stdout.strip() == "(10 20)"


def test_yield_round_robin():
    """yield! causes round-robin scheduling."""
    r = run_guile(
        "(use-modules (csp))"
        "(let ((log '()))"
        "  (define (make-logger name n)"
        "    (spawn (lambda ()"
        "      (let loop ((i 0))"
        "        (when (< i n)"
        "          (set! log (cons (cons name i) log))"
        "          (yield!)"
        "          (loop (+ i 1))))"
        "      name)))"
        "  (let* ((t1 (make-logger 'a 3))"
        "         (t2 (make-logger 'b 2))"
        "         (results (run-scheduler (list t1 t2))))"
        "    (display (reverse log))))"
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    out = r.stdout.strip()
    assert out == "((a . 0) (b . 0) (a . 1) (b . 1) (a . 2))"


def test_task_state_after_completion():
    """task-dead? and task-result work after scheduler finishes."""
    r = run_guile(
        "(use-modules (csp))"
        "(let ((t (spawn (lambda () 42))))"
        "  (run-scheduler (list t))"
        "  (display (task-dead? t))"
        '  (display " ")'
        "  (display (task-result t)))"
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert r.stdout.strip() == "#t 42"


# ---------------------------------------------------------------------------
# Synchronous (unbuffered) channels
# ---------------------------------------------------------------------------

def test_sync_channel_basic():
    """Synchronous channel: sender blocks until receiver is ready."""
    r = run_guile(
        "(use-modules (csp))"
        "(let ((ch (make-channel)))"
        "  (let* ((t1 (spawn (lambda () (channel-send! ch 99) 'sent)))"
        "         (t2 (spawn (lambda () (channel-recv! ch)))))"
        "    (let ((results (run-scheduler (list t1 t2))))"
        "      (display (sort-list results (lambda (a b)"
        "        (string<? (format #f \"~a\" a) (format #f \"~a\" b))))))))"
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    out = r.stdout.strip()
    assert "99" in out
    assert "sent" in out


def test_sync_channel_ordering():
    """Synchronous channel preserves send/recv value pairing."""
    r = run_guile(
        "(use-modules (csp))"
        "(let ((ch (make-channel)))"
        "  (let* ((t1 (spawn (lambda ()"
        "           (channel-send! ch 10)"
        "           (channel-send! ch 20)"
        "           (channel-send! ch 30)"
        "           'done-send)))"
        "         (t2 (spawn (lambda ()"
        "           (let* ((a (channel-recv! ch))"
        "                  (b (channel-recv! ch))"
        "                  (c (channel-recv! ch)))"
        "             (list a b c))))))"
        "    (let ((results (run-scheduler (list t1 t2))))"
        "      (display results))))"
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    out = r.stdout.strip()
    assert "(10 20 30)" in out


def test_sync_channel_recv_blocks_first():
    """Receiver blocks first, sender unblocks it."""
    r = run_guile(
        "(use-modules (csp))"
        "(let ((ch (make-channel)))"
        "  (let* ((t1 (spawn (lambda () (channel-recv! ch))))"
        "         (t2 (spawn (lambda () (yield!) (channel-send! ch 77) 'ok))))"
        "    (let ((results (run-scheduler (list t1 t2))))"
        "      (display results))))"
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    out = r.stdout.strip()
    assert "77" in out


# ---------------------------------------------------------------------------
# Buffered channels
# ---------------------------------------------------------------------------

def test_buffered_channel_no_block():
    """Buffered channel: sends don't block until buffer is full."""
    r = run_guile(
        "(use-modules (csp))"
        "(let ((ch (make-channel 3)))"
        "  (let* ((t1 (spawn (lambda ()"
        "           (channel-send! ch 1)"
        "           (channel-send! ch 2)"
        "           (channel-send! ch 3)"
        "           'filled)))"
        "         (t2 (spawn (lambda ()"
        "           (list (channel-recv! ch)"
        "                 (channel-recv! ch)"
        "                 (channel-recv! ch))))))"
        "    (let ((results (run-scheduler (list t1 t2))))"
        "      (display results))))"
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    out = r.stdout.strip()
    assert "(1 2 3)" in out
    assert "filled" in out


def test_buffered_channel_blocks_when_full():
    """Buffered channel blocks sender when buffer is full."""
    r = run_guile(
        "(use-modules (csp))"
        "(let ((ch (make-channel 1)))"
        "  (let* ((t1 (spawn (lambda ()"
        "           (channel-send! ch 'a)"
        "           (channel-send! ch 'b)"
        "           'done-send)))"
        "         (t2 (spawn (lambda ()"
        "           (let* ((v1 (channel-recv! ch))"
        "                  (v2 (channel-recv! ch)))"
        "             (list v1 v2))))))"
        "    (let ((results (run-scheduler (list t1 t2))))"
        "      (display results))))"
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    out = r.stdout.strip()
    assert "(a b)" in out


# ---------------------------------------------------------------------------
# Channel close
# ---------------------------------------------------------------------------

def test_channel_close_recv_sentinel():
    """Closed + drained channel returns 'channel-closed sentinel on recv."""
    r = run_guile(
        "(use-modules (csp))"
        "(let ((ch (make-channel 2)))"
        "  (let* ((t1 (spawn (lambda ()"
        "           (channel-send! ch 1)"
        "           (channel-send! ch 2)"
        "           (channel-close! ch)"
        "           'closed)))"
        "         (t2 (spawn (lambda ()"
        "           (let* ((a (channel-recv! ch))"
        "                  (b (channel-recv! ch))"
        "                  (c (channel-recv! ch)))"
        "             (list a b c))))))"
        "    (let ((results (run-scheduler (list t1 t2))))"
        "      (display results))))"
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    out = r.stdout.strip()
    assert "(1 2 channel-closed)" in out


def test_channel_close_send_error():
    """Sending to a closed channel raises 'channel-closed error."""
    r = run_guile(
        "(use-modules (csp))"
        "(let ((ch (make-channel)))"
        "  (let* ((t1 (spawn (lambda ()"
        "           (channel-close! ch)"
        "           'closer)))"
        "         (t2 (spawn (lambda ()"
        "           (catch 'channel-closed"
        "             (lambda () (channel-send! ch 1) 'should-not-reach)"
        "             (lambda (key . args) 'caught-closed))))))"
        "    (let ((results (run-scheduler (list t1 t2))))"
        "      (display results))))"
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    out = r.stdout.strip()
    assert "caught-closed" in out


def test_close_unblocks_waiting_receiver():
    """Closing a channel unblocks receivers that are waiting."""
    r = run_guile(
        "(use-modules (csp))"
        "(let ((ch (make-channel)))"
        "  (let* ((t1 (spawn (lambda () (channel-recv! ch))))"
        "         (t2 (spawn (lambda () (yield!) (channel-close! ch) 'closed))))"
        "    (let ((results (run-scheduler (list t1 t2))))"
        "      (display results))))"
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    out = r.stdout.strip()
    assert "channel-closed" in out


# ---------------------------------------------------------------------------
# Fan-in: multiple producers, one consumer
# ---------------------------------------------------------------------------

def test_fan_in():
    """Multiple producers send to one channel, single consumer collects all."""
    r = run_guile(
        "(use-modules (csp))"
        "(let ((ch (make-channel 5)))"
        "  (let* ((p1 (spawn (lambda () (channel-send! ch 10) 'p1)))"
        "         (p2 (spawn (lambda () (channel-send! ch 20) 'p2)))"
        "         (p3 (spawn (lambda () (channel-send! ch 30) 'p3)))"
        "         (consumer (spawn (lambda ()"
        "           (let loop ((acc '()) (n 0))"
        "             (if (= n 3) (sort acc <)"
        "                 (loop (cons (channel-recv! ch) acc) (+ n 1))))))))"
        "    (let ((results (run-scheduler (list p1 p2 p3 consumer))))"
        "      (display results))))"
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    out = r.stdout.strip()
    assert "(10 20 30)" in out


# ---------------------------------------------------------------------------
# Pipeline: chain of tasks communicating via channels
# ---------------------------------------------------------------------------

def test_pipeline():
    """Pipeline: producer -> doubler -> collector via two channels."""
    r = run_guile(
        "(use-modules (csp))"
        "(let ((ch1 (make-channel 3))"
        "      (ch2 (make-channel 3)))"
        "  (let* ((producer (spawn (lambda ()"
        "           (channel-send! ch1 1)"
        "           (channel-send! ch1 2)"
        "           (channel-send! ch1 3)"
        "           (channel-close! ch1)"
        "           'produced)))"
        "         (doubler (spawn (lambda ()"
        "           (let loop ()"
        "             (let ((v (channel-recv! ch1)))"
        "               (if (eq? v 'channel-closed)"
        "                   (begin (channel-close! ch2) 'doubled)"
        "                   (begin (channel-send! ch2 (* v 2))"
        "                          (loop))))))))"
        "         (collector (spawn (lambda ()"
        "           (let loop ((acc '()))"
        "             (let ((v (channel-recv! ch2)))"
        "               (if (eq? v 'channel-closed)"
        "                   (reverse acc)"
        "                   (loop (cons v acc)))))))))"
        "    (let ((results (run-scheduler (list producer doubler collector))))"
        "      (display results))))"
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    out = r.stdout.strip()
    assert "(2 4 6)" in out


# ---------------------------------------------------------------------------
# Select
# ---------------------------------------------------------------------------

def test_select_picks_ready_channel():
    """select returns the first ready clause."""
    r = run_guile(
        "(use-modules (csp))"
        "(let ((ch1 (make-channel 1))"
        "      (ch2 (make-channel 1)))"
        "  (let* ((t1 (spawn (lambda ()"
        "           (channel-send! ch2 'val2)"
        "           'sent)))"
        "         (t2 (spawn (lambda ()"
        "           (let ((ready (select (list (cons ch1 'recv)"
        "                                     (cons ch2 'recv)))))"
        "             (cons (eq? (car ready) ch2) (cdr ready)))))))"
        "    (let ((results (run-scheduler (list t1 t2))))"
        "      (display results))))"
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    out = r.stdout.strip()
    assert "(#t . recv)" in out


def test_select_earliest_wins_tie():
    """When multiple channels are ready, select prefers the earliest clause."""
    r = run_guile(
        "(use-modules (csp))"
        "(let ((ch1 (make-channel 1))"
        "      (ch2 (make-channel 1)))"
        "  (let* ((t1 (spawn (lambda ()"
        "           (channel-send! ch1 'v1)"
        "           (channel-send! ch2 'v2)"
        "           'sent)))"
        "         (t2 (spawn (lambda ()"
        "           (yield!)"
        "           (let ((ready (select (list (cons ch1 'recv)"
        "                                     (cons ch2 'recv)))))"
        "             (eq? (car ready) ch1))))))"
        "    (let ((results (run-scheduler (list t1 t2))))"
        "      (display results))))"
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    out = r.stdout.strip()
    assert "#t" in out


# ---------------------------------------------------------------------------
# Deadlock detection
# ---------------------------------------------------------------------------

def test_deadlock_detected():
    """Scheduler detects deadlock when all tasks are blocked."""
    r = run_guile(
        "(use-modules (csp))"
        "(let ((ch (make-channel)))"
        "  (let* ((t1 (spawn (lambda () (channel-recv! ch))))"
        "         (t2 (spawn (lambda () (channel-recv! ch)))))"
        "    (catch 'deadlock"
        "      (lambda () (run-scheduler (list t1 t2)) 'no-deadlock)"
        "      (lambda (key . args) (display 'deadlock-caught)))))",
        timeout=10,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert r.stdout.strip() == "deadlock-caught"


def test_no_false_deadlock():
    """No false deadlock when tasks can make progress."""
    r = run_guile(
        "(use-modules (csp))"
        "(let ((ch (make-channel)))"
        "  (let* ((t1 (spawn (lambda () (channel-send! ch 1) 'sent)))"
        "         (t2 (spawn (lambda () (channel-recv! ch)))))"
        "    (let ((results (run-scheduler (list t1 t2))))"
        "      (display 'ok))))"
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert r.stdout.strip() == "ok"


# ---------------------------------------------------------------------------
# Completion order
# ---------------------------------------------------------------------------

def test_completion_order():
    """Results are returned in task completion order."""
    r = run_guile(
        "(use-modules (csp))"
        "(let* ((t1 (spawn (lambda () (yield!) (yield!) 'last)))"
        "       (t2 (spawn (lambda () (yield!) 'middle)))"
        "       (t3 (spawn (lambda () 'first))))"
        "  (display (run-scheduler (list t1 t2 t3))))"
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert r.stdout.strip() == "(first middle last)"
