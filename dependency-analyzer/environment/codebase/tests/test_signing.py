from crypto.sign import sign, verify


def test_sign():
    sig = sign("hello", "secret")
    assert isinstance(sig, str)


def test_verify():
    sig = sign("hello", "secret")
    assert verify("hello", sig, "secret")
    assert not verify("world", sig, "secret")
