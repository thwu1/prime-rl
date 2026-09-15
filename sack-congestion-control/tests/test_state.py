
"""
Verification tests for the Selective Repeat + SACK + TCP Reno
reliable transport protocol.

Tests cover:
  1. Correct file transfer with no loss
  2. Correct transfer under moderate (10%) packet loss
  3. Correct transfer under heavy (20%) loss + reordering
  4. Presence of SACK blocks in sender log (proving SACK works end-to-end)
  5. TCP Reno congestion-control dynamics (slow start, AIMD, fast retransmit)
  6. Correct transfer despite packet corruption
  7. Retransmission efficiency: SR must retransmit far fewer packets than GBN
"""

import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile

import pytest

MAX_PAYLOAD = 500


# ------------------------------------------------------------------ helpers

def _gen_file(path, size, seed=12345):
    """Write a deterministic binary blob; return its MD5."""
    rng = random.Random(seed)
    data = rng.randbytes(size)
    with open(path, "wb") as fh:
        fh.write(data)
    return hashlib.md5(data).hexdigest()


def _transfer(input_f, output_f, *, loss=0.0, delay=10.0, jitter=5.0,
              reorder=0.0, corrupt=0.0, duplicate=0.0, seed=42,
              sender_log=None, receiver_log=None, timeout=60):
    """Run a single file transfer through the protocol stack."""
    cmd = [
        sys.executable, "/app/run_transfer.py",
        "--file", input_f,
        "--output", output_f,
        "--loss", str(loss),
        "--delay", str(delay),
        "--jitter", str(jitter),
        "--reorder", str(reorder),
        "--corrupt", str(corrupt),
        "--duplicate", str(duplicate),
        "--seed", str(seed),
        "--timeout", str(timeout),
    ]
    if sender_log:
        cmd += ["--sender-log", sender_log]
    if receiver_log:
        cmd += ["--receiver-log", receiver_log]

    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout + 30)
    stdout = proc.stdout.strip()
    if not stdout:
        raise RuntimeError(
            f"run_transfer produced no output (rc={proc.returncode}): "
            f"{proc.stderr[:500]}")
    return json.loads(stdout)


# ------------------------------------------------------------------- tests

class TestReliableTransport:

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp(prefix="transport_test_")

    # helper
    def _p(self, name):
        return os.path.join(self.tmpdir, name)

    # 1 - no-loss baseline
    def test_no_loss_transfer(self):
        inp = self._p("in_noloss.bin")
        out = self._p("out_noloss.bin")
        md5 = _gen_file(inp, 102_400)

        r = _transfer(inp, out, loss=0.0, delay=5.0, jitter=2.0,
                       seed=100, timeout=25)
        assert r["success"], f"no-loss transfer failed: {r}"
        assert r["received_md5"] == md5

    # 2 - moderate loss
    def test_moderate_loss(self):
        inp = self._p("in_modloss.bin")
        out = self._p("out_modloss.bin")
        md5 = _gen_file(inp, 102_400, seed=54321)

        r = _transfer(inp, out, loss=0.10, delay=10.0, jitter=5.0,
                       seed=200, timeout=35)
        assert r["success"], f"10% loss transfer failed: {r}"
        assert r["received_md5"] == md5

    # 3 - heavy loss + reorder
    def test_heavy_loss_with_reorder(self):
        inp = self._p("in_heavy.bin")
        out = self._p("out_heavy.bin")
        md5 = _gen_file(inp, 51_200, seed=99999)

        r = _transfer(inp, out, loss=0.20, delay=15.0, jitter=10.0,
                       reorder=0.10, seed=300, timeout=55)
        assert r["success"], f"20% loss + reorder transfer failed: {r}"
        assert r["received_md5"] == md5

    # 4 - SACK blocks present
    def test_sack_blocks_present(self):
        inp = self._p("in_sack.bin")
        out = self._p("out_sack.bin")
        slog = self._p("sender_sack.json")
        _gen_file(inp, 51_200, seed=11111)

        r = _transfer(inp, out, loss=0.15, delay=10.0,
                       seed=400, sender_log=slog, timeout=40)
        assert r["success"], "SACK transfer must succeed"

        with open(slog) as fh:
            sdata = json.load(fh)
        sack_events = [e for e in sdata.get("events", [])
                       if e.get("sack_blocks") and len(e["sack_blocks"]) > 0]
        assert len(sack_events) > 0, (
            "Sender must log received SACK blocks -- none found")

    # 5 - congestion control dynamics
    def test_congestion_control_dynamics(self):
        inp = self._p("in_cc.bin")
        out = self._p("out_cc.bin")
        slog = self._p("sender_cc.json")
        _gen_file(inp, 102_400, seed=33333)

        r = _transfer(inp, out, loss=0.10, delay=10.0,
                       seed=500, sender_log=slog, timeout=40)
        assert r["success"], "CC transfer must succeed"

        with open(slog) as fh:
            sdata = json.load(fh)

        ack_evts = [e for e in sdata.get("events", [])
                    if e.get("event") == "ACK" and "cwnd" in e]
        cwnds = [e["cwnd"] for e in ack_evts]
        assert len(cwnds) >= 10, "Must have >=10 ACK events with cwnd"

        # slow start growth
        max_cwnd = max(cwnds)
        assert max_cwnd > 2.0, (
            f"cwnd should grow above 2 during slow start (max={max_cwnd})")

        # multiplicative decrease
        max_i = cwnds.index(max_cwnd)
        if max_i < len(cwnds) - 1:
            rest_min = min(cwnds[max_i:])
            assert rest_min < max_cwnd * 0.85, (
                "cwnd should drop after congestion")

        # congestion events logged
        cong_evts = [e for e in sdata.get("events", [])
                     if e.get("event") in ("FAST_RETRANSMIT", "TIMEOUT")]
        assert len(cong_evts) > 0, "Must have FAST_RETRANSMIT or TIMEOUT events"

    # 6 - corruption handling
    def test_corruption_handling(self):
        inp = self._p("in_corrupt.bin")
        out = self._p("out_corrupt.bin")
        md5 = _gen_file(inp, 51_200, seed=55555)

        r = _transfer(inp, out, loss=0.05, corrupt=0.05, delay=10.0,
                       seed=600, timeout=40)
        assert r["success"], f"corruption transfer failed: {r}"
        assert r["received_md5"] == md5

    # 7 - retransmission efficiency
    def test_retransmission_efficiency(self):
        inp = self._p("in_eff.bin")
        out = self._p("out_eff.bin")
        slog = self._p("sender_eff.json")
        _gen_file(inp, 102_400, seed=44444)

        r = _transfer(inp, out, loss=0.15, delay=10.0,
                       seed=700, sender_log=slog, timeout=40)
        assert r["success"], "Efficiency transfer must succeed"

        with open(slog) as fh:
            sdata = json.load(fh)

        stats = sdata["stats"]
        total_data_pkts = (stats["data_bytes"] + MAX_PAYLOAD - 1) // MAX_PAYLOAD
        retx = stats["total_retransmissions"]
        ratio = retx / total_data_pkts if total_data_pkts else 0

        assert ratio < 0.60, (
            f"Retransmit ratio {ratio:.2f} too high -- selective repeat "
            f"should retransmit far fewer packets than Go-Back-N "
            f"(retx={retx}, data_pkts={total_data_pkts})")
