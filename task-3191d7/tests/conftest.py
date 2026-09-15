"""Pytest fixtures for NexAuth scanner verification.

Regenerates ground truth tokens from the same deterministic seed
used during corpus generation. No ground truth file is stored
in the Docker image.

"""

import json
import os
import random
import zlib
import pytest

_SEED = 73219486
_BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

_TOKEN_DEFS = {
    "nxa": {"prefix": "nxa_", "payload_len": 30, "cksum_input": "full_prefix",
            "complement": False},
    "nxs": {"prefix": "nxs_", "payload_len": 30, "cksum_input": "prefix_letters",
            "complement": False},
    "nxr": {"prefix": "nxr_", "payload_len": 36, "cksum_input": "full_prefix",
            "complement": False},
    "nxd": {"prefix": "nxd_", "payload_len": 30, "cksum_input": "payload_only",
            "complement": False},
    "nxi": {"prefix": "nxi_", "payload_len": 30, "cksum_input": "full_prefix",
            "complement": True},
}


def _b62enc(n, width=6):
    if n == 0:
        return _BASE62[0] * width
    d = []
    while n:
        d.append(_BASE62[n % 62])
        n //= 62
    d.reverse()
    return "".join(d).rjust(width, _BASE62[0])


def _rand_payload(length, rng):
    return "".join(rng.choice(_BASE62) for _ in range(length))


def _crc_for(ttype, prefix, payload):
    td = _TOKEN_DEFS[ttype]
    ci = td["cksum_input"]
    if ci == "full_prefix":
        data = prefix + payload
    elif ci == "prefix_letters":
        data = prefix.rstrip("_") + payload
    elif ci == "payload_only":
        data = payload
    else:
        data = prefix + payload
    c = zlib.crc32(data.encode()) & 0xFFFFFFFF
    if td["complement"]:
        c = (~c) & 0xFFFFFFFF
    return c


def _mk_token(ttype, valid, rng):
    td = _TOKEN_DEFS[ttype]
    payload = _rand_payload(td["payload_len"], rng)
    c = _crc_for(ttype, td["prefix"], payload)
    cksum = _b62enc(c)
    tok = td["prefix"] + payload + cksum
    if not valid:
        i = _BASE62.index(tok[-1])
        tok = tok[:-1] + _BASE62[(i + 7) % 62]
    return tok


def _generate_ground_truth():
    rng = random.Random(_SEED)
    toks = []
    for ttype in sorted(_TOKEN_DEFS.keys()):
        for _ in range(10):
            toks.append({"token": _mk_token(ttype, True, rng),
                         "type": ttype, "valid": True})
        for _ in range(3):
            toks.append({"token": _mk_token(ttype, False, rng),
                         "type": ttype, "valid": False})
    rng.shuffle(toks)
    return toks


_GROUND_TRUTH = _generate_ground_truth()


@pytest.fixture
def ground_truth():
    return _GROUND_TRUTH


@pytest.fixture
def report():
    path = "/app/report.json"
    assert os.path.exists(path), "report.json not found at /app/report.json"
    with open(path) as f:
        return json.load(f)
