from network.dns import DNSResolver


def test_resolve():
    r = DNSResolver()
    ip = r.resolve("example.com")
    assert ip == "127.0.0.1"


def test_cache():
    r = DNSResolver()
    r.resolve("example.com")
    assert "example.com" in r.cache
    r.clear_cache()
    assert len(r.cache) == 0
