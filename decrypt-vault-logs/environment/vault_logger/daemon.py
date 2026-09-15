"""
Vault audit logging daemon.

Lifecycle
---------
1. Load the encryption key from the hardware security module.
2. Select the configured encryption engine (v1, v2, or v3).
3. Open (or create) the SQLite database.
4. Enter the main loop: accept audit events, encrypt them, persist
   the ciphertext.

Engine selection is driven by the deployment manifest at
``/app/config/deployment_manifest.json``.
"""

import signal
import sys
import time

from .config import KEY_PATH, HEARTBEAT_INTERVAL_SEC
from .formatters import EntryFormatter
from .storage import AuditStore


class VaultDaemon:

    def __init__(self, engine_version: int = 3):
        self.running = False
        self.store = AuditStore()
        self.engine = None
        self._engine_version = engine_version

    # ── engine management ─────────────────────────────────────────────

    def _load_key(self) -> bytes:
        with open(KEY_PATH, 'rb') as fh:
            key = fh.read(32)
        if len(key) < 16:
            raise RuntimeError("HSM key must be at least 16 bytes")
        return key

    def _load_engine(self):
        """Instantiate the configured encryption engine."""
        key = self._load_key()
        if self._engine_version == 1:
            from .engines.ecb_v1 import ECBEngine
            self.engine = ECBEngine(key[:16])
        elif self._engine_version == 2:
            from .engines.ctr_v2 import CTREngine
            self.engine = CTREngine.create_session(key)
        elif self._engine_version == 3:
            from .engines.gcm_v3 import GCMEngine
            self.engine = GCMEngine(key)
        else:
            raise ValueError(f"Unknown engine version: {self._engine_version}")

    # ── low-level entry writer ────────────────────────────────────────

    def _write_entry(self, entry_type: str, plaintext: bytes,
                     timestamp: int = None):
        ts = timestamp if timestamp is not None else int(time.time())
        if self._engine_version == 2:
            seq, ct = self.engine.encrypt(plaintext)
            self.store.store_entry(
                self.engine.session_id, seq, entry_type,
                self._engine_version, ct, ts,
            )
        elif self._engine_version == 1:
            ct = self.engine.encrypt(plaintext)
            self.store.store_entry(
                0, 0, entry_type, self._engine_version, ct, ts,
            )
        else:
            ct = self.engine.encrypt(plaintext)
            self.store.store_entry(
                0, 0, entry_type, self._engine_version, ct, ts,
            )

    # ── public entry producers ────────────────────────────────────────

    def emit_heartbeat(self):
        ts = int(time.time())
        if self._engine_version == 2:
            payload = EntryFormatter.format_heartbeat(
                self.engine.session_id,
                self.engine.next_seq,
                ts,
            )
        else:
            payload = EntryFormatter.format_heartbeat(0, 0, ts)
        self._write_entry('HEARTBEAT', payload, timestamp=ts)

    def log_audit(self, user: str, action: str, resource: str):
        ts = int(time.time())
        payload = EntryFormatter.format_audit(user, action, resource, ts)
        self._write_entry('AUDIT', payload, timestamp=ts)

    def log_secret(self, name: str, value: str):
        ts = int(time.time())
        payload = EntryFormatter.format_secret(name, value)
        self._write_entry('SECRET', payload, timestamp=ts)

    def log_alert(self, level: str, message: str):
        ts = int(time.time())
        payload = EntryFormatter.format_alert(level, message, ts)
        self._write_entry('ALERT', payload, timestamp=ts)

    def log_access(self, user: str, granted: bool, resource: str):
        ts = int(time.time())
        payload = EntryFormatter.format_access(user, granted, resource, ts)
        self._write_entry('ACCESS', payload, timestamp=ts)

    # ── lifecycle ─────────────────────────────────────────────────────

    def start(self):
        self._load_engine()
        self.store.connect()
        self.running = True

        def _shutdown(signum, frame):
            self.running = False

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

        while self.running:
            self.emit_heartbeat()
            time.sleep(HEARTBEAT_INTERVAL_SEC)

        self.store.close()


if __name__ == '__main__':
    VaultDaemon().start()
