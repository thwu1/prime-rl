
import sys
sys.path.insert(0, '/app')
import pytest


@pytest.fixture
def attack_env():
    from vaultsync import Server, AttackParams
    from dissononce.dh.x25519.x25519 import X25519DH

    server = Server()
    client_keypair = X25519DH().generate_keypair()
    server.register_user(client_keypair.public)
    params = AttackParams(client_keypair, server)
    return server, params


def test_recover_signing_key(attack_env):
    import solution
    server, params = attack_env
    recovered_key = solution.recover_signing_key(params)
    assert isinstance(recovered_key, int), "recover_signing_key must return an int"
    assert recovered_key == server.ecdsa_sk, (
        "Recovered ECDSA key does not match server's actual signing key"
    )


def test_forge_vault_update(attack_env):
    import solution
    server, params = attack_env
    target_data = b"VaultSync audit: storage compromised by attacker"
    solution.forge_vault_update(params, target_data)
    assert server.get_user_storage() == target_data, (
        f"Storage content mismatch: expected {target_data!r}, "
        f"got {server.get_user_storage()!r}"
    )
