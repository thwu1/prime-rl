
import subprocess
import json
import os
import pytest


def get_vault_env():
    """Return environment dict with Vault address and root token."""
    env = os.environ.copy()
    env['VAULT_ADDR'] = 'http://127.0.0.1:8200'
    try:
        with open('/app/vault-creds/root-token', 'r') as f:
            env['VAULT_TOKEN'] = f.read().strip()
    except FileNotFoundError:
        pass
    return env


def vault_cmd(args):
    """Run a vault CLI command with root token."""
    env = get_vault_env()
    return subprocess.run(
        ['vault'] + args,
        capture_output=True, text=True, env=env, timeout=30
    )


def vault_cmd_with_token(args, token):
    """Run a vault CLI command with a specific token."""
    env = get_vault_env()
    env['VAULT_TOKEN'] = token
    return subprocess.run(
        ['vault'] + args,
        capture_output=True, text=True, env=env, timeout=30
    )


class TestVaultStatus:
    def test_vault_running_and_unsealed(self):
        r = vault_cmd(['status', '-format=json'])
        assert r.returncode == 0, f"Vault not reachable: {r.stderr}"
        status = json.loads(r.stdout)
        assert status['initialized'] is True, "Vault not initialized"
        assert status['sealed'] is False, "Vault is sealed"


class TestPKIRootCA:
    def test_root_ca_mount_max_ttl(self):
        """Root CA mount max_lease_ttl must be at least 10 years."""
        r = vault_cmd(['read', '-format=json', 'sys/mounts/pki/tune'])
        assert r.returncode == 0, f"Cannot read pki tune: {r.stderr}"
        data = json.loads(r.stdout)['data']
        max_ttl = data['max_lease_ttl']
        # 10 years = 87600h = 315360000s
        assert max_ttl >= 315360000, (
            f"max_lease_ttl={max_ttl}s, need >=315360000s (10 years)"
        )

    def test_root_cert_exists(self):
        """Root CA certificate must exist."""
        r = vault_cmd(['read', '-field=certificate', 'pki/cert/ca'])
        assert r.returncode == 0, f"Cannot read root CA cert: {r.stderr}"
        assert '-----BEGIN CERTIFICATE-----' in r.stdout


class TestPKIIntermediate:
    def test_intermediate_signed_by_root(self):
        """Intermediate CA must be cryptographically signed by the root CA."""
        r1 = vault_cmd(['read', '-field=certificate', 'pki/cert/ca'])
        assert r1.returncode == 0
        root_pem = r1.stdout.strip()

        r2 = vault_cmd(['read', '-field=certificate', 'pki_int/cert/ca'])
        assert r2.returncode == 0
        int_pem = r2.stdout.strip()

        with open('/tmp/test_root.pem', 'w') as f:
            f.write(root_pem)
        with open('/tmp/test_int.pem', 'w') as f:
            f.write(int_pem)

        r = subprocess.run(
            ['openssl', 'verify', '-CAfile', '/tmp/test_root.pem', '/tmp/test_int.pem'],
            capture_output=True, text=True
        )
        assert r.returncode == 0, f"Chain verification failed: {r.stderr} {r.stdout}"


class TestPKIRole:
    def test_web_server_role_constraints(self):
        """web-server role must have proper domain restrictions."""
        r = vault_cmd(['read', '-format=json', 'pki_int/roles/web-server'])
        assert r.returncode == 0, f"Cannot read role: {r.stderr}"
        role = json.loads(r.stdout)['data']
        assert role['allow_any_name'] is False, "allow_any_name must be false"
        assert 'example.com' in role['allowed_domains'], (
            f"allowed_domains={role['allowed_domains']}, must include example.com"
        )
        assert role['allow_subdomains'] is True, "allow_subdomains must be true"
        # max_ttl <= 720h = 2592000s
        assert role['max_ttl'] <= 2592000, (
            f"max_ttl={role['max_ttl']}s, must be <=2592000s (720h)"
        )
        assert role['key_bits'] >= 4096, (
            f"key_bits={role['key_bits']}, must be >=4096"
        )


class TestPolicies:
    def test_app_readonly_functional_read(self):
        """Token with app-readonly policy should read app secrets."""
        r = vault_cmd(['token', 'create', '-policy=app-readonly',
                       '-format=json', '-ttl=5m'])
        assert r.returncode == 0, f"Cannot create token: {r.stderr}"
        token = json.loads(r.stdout)['auth']['client_token']

        r = vault_cmd_with_token(
            ['kv', 'get', '-format=json', 'secret/app/database'], token
        )
        assert r.returncode == 0, (
            f"app-readonly should read secret/app/database: {r.stderr}"
        )

    def test_app_readonly_functional_no_write(self):
        """Token with app-readonly policy must NOT write secrets."""
        r = vault_cmd(['token', 'create', '-policy=app-readonly',
                       '-format=json', '-ttl=5m'])
        assert r.returncode == 0
        token = json.loads(r.stdout)['auth']['client_token']

        r = vault_cmd_with_token(
            ['kv', 'put', 'secret/app/hackertest', 'x=y'], token
        )
        assert r.returncode != 0, "app-readonly must NOT write to secrets"

    def test_app_readonly_functional_no_pki(self):
        """Token with app-readonly policy must NOT access PKI."""
        r = vault_cmd(['token', 'create', '-policy=app-readonly',
                       '-format=json', '-ttl=5m'])
        assert r.returncode == 0
        token = json.loads(r.stdout)['auth']['client_token']

        r = vault_cmd_with_token(
            ['read', 'pki_int/roles/web-server'], token
        )
        assert r.returncode != 0, "app-readonly must NOT access PKI"

    def test_cert_issuer_can_issue(self):
        """Token with cert-issuer policy should issue certs."""
        r = vault_cmd(['token', 'create', '-policy=cert-issuer',
                       '-format=json', '-ttl=5m'])
        assert r.returncode == 0
        token = json.loads(r.stdout)['auth']['client_token']

        r = vault_cmd_with_token(
            ['write', '-format=json', 'pki_int/issue/web-server',
             'common_name=test.example.com', 'ttl=1h'], token
        )
        assert r.returncode == 0, (
            f"cert-issuer should issue certs: {r.stderr}"
        )

    def test_cert_issuer_no_root_access(self):
        """Token with cert-issuer policy must NOT generate root certs."""
        r = vault_cmd(['token', 'create', '-policy=cert-issuer',
                       '-format=json', '-ttl=5m'])
        assert r.returncode == 0
        token = json.loads(r.stdout)['auth']['client_token']

        r = vault_cmd_with_token(
            ['write', 'pki/root/generate/internal',
             'common_name=Evil Root'], token
        )
        assert r.returncode != 0, (
            "cert-issuer must NOT generate root certificates"
        )

    def test_cert_issuer_no_secrets(self):
        """Token with cert-issuer policy must NOT read KV secrets."""
        r = vault_cmd(['token', 'create', '-policy=cert-issuer',
                       '-format=json', '-ttl=5m'])
        assert r.returncode == 0
        token = json.loads(r.stdout)['auth']['client_token']

        r = vault_cmd_with_token(
            ['kv', 'get', 'secret/app/database'], token
        )
        assert r.returncode != 0, "cert-issuer must NOT read secrets"


class TestAppRole:
    def test_webapp_ttl_limits(self):
        """webapp AppRole must have finite TTL limits."""
        r = vault_cmd(['read', '-format=json', 'auth/approle/role/webapp'])
        assert r.returncode == 0
        role = json.loads(r.stdout)['data']
        assert role['token_ttl'] > 0, "token_ttl must not be 0 (infinite)"
        assert role['token_max_ttl'] > 0, "token_max_ttl must not be 0 (infinite)"
        assert role['token_ttl'] <= 86400, "token_ttl exceeds 24h"
        assert role['token_max_ttl'] <= 86400, "token_max_ttl exceeds 24h"
        assert role['token_num_uses'] > 0, "token_num_uses must be limited"

    def test_webapp_cidr_restrictions(self):
        """webapp AppRole must have CIDR restrictions on secret IDs."""
        r = vault_cmd(['read', '-format=json', 'auth/approle/role/webapp'])
        assert r.returncode == 0
        role = json.loads(r.stdout)['data']
        cidrs = role.get('secret_id_bound_cidrs', []) or []
        assert len(cidrs) > 0, "secret_id_bound_cidrs must not be empty"


class TestAudit:
    def test_audit_device_enabled(self):
        """At least one audit device must be enabled."""
        r = vault_cmd(['audit', 'list', '-format=json'])
        assert r.returncode == 0, f"Cannot list audit devices: {r.stderr}"
        data = json.loads(r.stdout)
        assert len(data) > 0, "No audit devices enabled"


class TestKVSecrets:
    def test_kv_v2_enabled(self):
        """KV secrets engine must be version 2."""
        r = vault_cmd(['secrets', 'list', '-format=json'])
        assert r.returncode == 0
        mounts = json.loads(r.stdout)
        assert 'secret/' in mounts, "secret/ mount not found"
        options = mounts['secret/'].get('options', {}) or {}
        assert options.get('version') == '2', (
            f"KV version is {options.get('version')}, expected 2"
        )

    def test_database_secret_preserved(self):
        """Database credentials must be preserved after KV upgrade."""
        r = vault_cmd(['kv', 'get', '-format=json', 'secret/app/database'])
        assert r.returncode == 0, f"Cannot read database secret: {r.stderr}"
        data = json.loads(r.stdout)['data']['data']
        assert data['username'] == 'dbuser'
        assert data['password'] == 's3cret123'

    def test_api_key_secret_preserved(self):
        """API key secret must be preserved after KV upgrade."""
        r = vault_cmd(['kv', 'get', '-format=json', 'secret/app/api-key'])
        assert r.returncode == 0, f"Cannot read api-key secret: {r.stderr}"
        data = json.loads(r.stdout)['data']['data']
        assert data['key'] == 'ak_live_xxx123'


class TestLeafCertificate:
    def test_leaf_cert_files_exist(self):
        """Leaf certificate files must exist."""
        assert os.path.isfile('/app/certs/app.example.com.crt'), "cert missing"
        assert os.path.isfile('/app/certs/app.example.com.key'), "key missing"
        assert os.path.isfile('/app/certs/ca-chain.pem'), "ca-chain missing"

    def test_leaf_cert_cn(self):
        """Leaf certificate CN must be app.example.com."""
        r = subprocess.run(
            ['openssl', 'x509', '-in', '/app/certs/app.example.com.crt',
             '-noout', '-subject'],
            capture_output=True, text=True
        )
        assert r.returncode == 0, f"Cannot parse cert: {r.stderr}"
        assert 'app.example.com' in r.stdout, (
            f"CN mismatch: {r.stdout}"
        )
