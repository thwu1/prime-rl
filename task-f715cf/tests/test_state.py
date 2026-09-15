"""
Tests for the Vinaigrette signature forgery task.

"""
import os
import sys

sys.path.insert(0, "/app")
from vinaigrette import (
    Q, N, M, K,
    load_public_key,
    shake256_hash,
    eval_whipped,
    verify,
)

MESSAGE = "Forge this signature to prove you broke Vinaigrette"
SIG_FILE = "/app/signature.txt"
PK_FILE = "/app/public_key.txt"


def test_signature_file_exists():
    assert os.path.isfile(SIG_FILE), "signature.txt not found in /app/"


def test_signature_format():
    with open(SIG_FILE) as f:
        tokens = f.read().split()
    assert len(tokens) == K * N, (
        f"Expected {K * N} integers, got {len(tokens)}"
    )
    sig = [int(t) for t in tokens]
    for i, val in enumerate(sig):
        assert 0 <= val < Q, (
            f"Signature element {i} = {val} is not in F_{Q}"
        )


def test_signature_verifies():
    pk = load_public_key(PK_FILE)
    with open(SIG_FILE) as f:
        sig = [int(x) for x in f.read().split()]
    target = shake256_hash(MESSAGE)
    actual = eval_whipped(pk, sig)
    assert actual == target, (
        f"P*(sig) != H(msg): got {actual}, expected {target}"
    )


def test_signature_via_verify_function():
    pk = load_public_key(PK_FILE)
    with open(SIG_FILE) as f:
        sig = [int(x) for x in f.read().split()]
    assert verify(pk, MESSAGE, sig), "verify() returned False"
