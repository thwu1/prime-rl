from crypto.hash import sha256, md5


def test_sha256():
    result = sha256(b"hello")
    assert len(result) == 64
    assert result == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_md5():
    result = md5(b"hello")
    assert len(result) == 32
