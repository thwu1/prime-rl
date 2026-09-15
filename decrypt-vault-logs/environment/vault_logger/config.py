import os

# Key is loaded from a hardware security module at runtime
KEY_PATH = os.environ.get('VAULT_KEY_PATH', '/etc/vault/master.key')
DB_PATH = os.environ.get('VAULT_DB_PATH', '/app/data/audit.db')
LOG_LEVEL = os.environ.get('VAULT_LOG_LEVEL', 'INFO')
HEARTBEAT_INTERVAL_SEC = int(os.environ.get('VAULT_HB_INTERVAL', '30'))
SESSION_LOG_DIR = os.environ.get('VAULT_SESSION_LOG_DIR', '/var/log/vault')

# v1 key export passphrase — used to decrypt the RSA private key
# that protects the wrapped v1 AES key at /app/keys/v1_wrapped.bin
V1_KEY_EXPORT_PASSPHRASE = 'vault-hsm-export-2024'
