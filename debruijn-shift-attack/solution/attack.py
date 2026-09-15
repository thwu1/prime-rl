#!/usr/bin/env python3
"""SIGMA-7 Attack Tool.

Pipeline:
1. Parse /app/zones.dat binary config → zone params + passphrase + encoding tables
2. Decrypt /app/seed.enc with openssl → master seed
3. Derive auth key (SHA-256(seed)[:16])
4. Start receiver daemon, build UDP client
5. Generate De Bruijn sequences for each zone
6. Encode physical bitstreams for OOK/tri-state zones
7. Submit via authenticated UDP SUBMIT and collect cracked codes
8. Write results.json and sequence files
"""


import struct
import subprocess
import socket
import hashlib
import json
import os
import sys
import time

# Protocol constants (from receiver analysis)
MAGIC = b'\xdb\xbf'
OP_LIST   = 0x01
OP_INFO   = 0x02
OP_SUBMIT = 0x03
ST_OK      = 0x00
ST_ERR     = 0x01
ST_CRACKED = 0x02
ST_FAIL    = 0x03

FLAG_OOK      = 0x01
FLAG_TRISTATE = 0x02
FLAG_MULTI    = 0x04


# ---- Binary config parser ----

def parse_zones_dat(path):
    """Parse the packed binary zone configuration."""
    with open(path, 'rb') as f:
        d = f.read()

    p = 0
    assert d[p:p+4] == b'ZDAT', "Bad magic in zones.dat"
    p += 4
    _ver = d[p]; p += 1
    nz = d[p]; p += 1
    pp_len = d[p]; p += 1
    passphrase = d[p:p+pp_len].decode('ascii'); p += pp_len

    zones = []
    for _ in range(nz):
        zid = d[p]; k = d[p+1]; n = d[p+2]; flags = d[p+3]; p += 4
        name_len = d[p]; p += 1
        name = d[p:p+name_len].decode('ascii'); p += name_len
        extra_len = struct.unpack('<H', d[p:p+2])[0]; p += 2
        extra = d[p:p+extra_len]; p += extra_len

        encoding = None
        n_min = n_max = None

        if flags & (FLAG_OOK | FLAG_TRISTATE):
            encoding = {}
            ep = 0
            ns = extra[ep]; ep += 1
            for _ in range(ns):
                sv = extra[ep]; ep += 1
                plen = extra[ep]; ep += 1
                encoding[sv] = list(extra[ep:ep+plen]); ep += plen

        if flags & FLAG_MULTI:
            n_min = extra[0]
            n_max = extra[1]

        zones.append({
            'id': zid, 'name': name, 'k': k, 'n': n,
            'flags': flags, 'encoding': encoding,
            'n_min': n_min, 'n_max': n_max,
            'label': chr(ord('A') + zid),
        })

    return zones, passphrase


# ---- Crypto helpers ----

def decrypt_seed(enc_path, passphrase):
    """Decrypt master seed using openssl."""
    r = subprocess.run([
        'openssl', 'enc', '-aes-256-cbc', '-d', '-pbkdf2', '-iter', '100000',
        '-in', enc_path, '-pass', 'pass:' + passphrase
    ], capture_output=True, text=True)
    if r.returncode != 0:
        print("Decryption failed: " + r.stderr, file=sys.stderr)
        sys.exit(1)
    return r.stdout.strip()


def compute_auth_key(seed):
    """Derive 16-byte authentication key from seed."""
    return hashlib.sha256(seed.encode()).digest()[:16]


# ---- De Bruijn sequence generator ----

def de_bruijn(k, n):
    """Generate linear De Bruijn sequence B(k, n) using necklace enumeration."""
    a = [0] * (k * n)
    seq = []

    def db(t, p):
        if t > n:
            if n % p == 0:
                seq.extend(a[1:p + 1])
        else:
            a[t] = a[t - p]
            db(t + 1, p)
            for j in range(a[t - p] + 1, k):
                a[t] = j
                db(t + 1, t)

    db(1, 1)
    return seq + seq[:n - 1]


# ---- Encoding helpers ----

def encode_physical(logical_seq, encoding):
    """Encode logical symbols to physical bits using encoding table."""
    phys = []
    for sym in logical_seq:
        phys.extend(encoding[sym])
    return phys


# ---- UDP client ----

def udp_send(sock, opcode, req_id, payload):
    """Send a protocol request and receive response."""
    msg = MAGIC + struct.pack('>BHH', opcode, req_id, len(payload)) + payload
    sock.sendto(msg, ('127.0.0.1', 7331))
    data, _ = sock.recvfrom(65535)
    assert len(data) >= 7 and data[:2] == MAGIC, "Bad response"
    status = data[2]
    rid = struct.unpack('>H', data[3:5])[0]
    rlen = struct.unpack('>H', data[5:7])[0]
    rpay = data[7:7 + rlen]
    return status, rid, rpay


def save_seq(seq, path):
    with open(path, 'w') as f:
        f.write(' '.join(map(str, seq)))


# ---- Main attack ----

def main():
    print("=== SIGMA-7 Attack Tool ===\n")

    # Step 1: Parse binary config
    zones, passphrase = parse_zones_dat('/app/zones.dat')
    print("Parsed {} zones from zones.dat".format(len(zones)))
    print("Extracted passphrase: '{}'".format(passphrase))

    # Step 2: Decrypt master seed
    seed = decrypt_seed('/app/seed.enc', passphrase)
    print("Decrypted seed: {}".format(seed))

    # Step 3: Derive auth key
    auth_key = compute_auth_key(seed)
    print("Auth key: {}".format(auth_key.hex()))

    # Step 4: Create UDP client
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(10)

    os.makedirs('/app/sequences', exist_ok=True)
    results = {}
    req_id = 0
    labels = {0: 'A', 1: 'B', 2: 'C', 3: 'D', 4: 'E'}

    for z in zones:
        zid = z['id']
        label = labels[zid]
        k, n, flags = z['k'], z['n'], z['flags']
        print("\n=== Zone {} ({}) k={} n={} flags=0x{:02x} ===".format(
            label, z['name'], k, n, flags))

        if flags & FLAG_MULTI:
            # Multi-length zone: B(2, n_max) covers all lengths n_min..n_max
            # Pigeonhole: B(2,12) has 4096 windows of length 12, so all
            # possible m-length strings (m < 12) appear as substrings.
            seq = de_bruijn(k, n)
            save_seq(seq, '/app/sequences/{}.txt'.format(label))

            payload = (struct.pack('>B', zid) + auth_key +
                       struct.pack('>I', len(seq)) + bytes(seq))
            req_id += 1
            st, _, rpay = udp_send(sock, OP_SUBMIT, req_id, payload)

            results[label] = {'sequence_length': len(seq)}
            if st == ST_CRACKED:
                nc = rpay[0]
                p = 1
                for _ in range(nc):
                    nn = rpay[p]; p += 1
                    cl = rpay[p]; p += 1
                    code = rpay[p:p + cl].decode(); p += cl
                    results[label][str(nn)] = {'code': code}
                    print("  n={}: code={}".format(nn, code))
            else:
                print("  FAILED (status={})".format(st))
                if rpay:
                    print("  Detail: {}".format(rpay))

        else:
            # Standard or encoded zone
            seq = de_bruijn(k, n)
            save_seq(seq, '/app/sequences/{}.txt'.format(label))

            if z['encoding']:
                phys = encode_physical(seq, z['encoding'])
                save_seq(phys, '/app/sequences/{}_physical.txt'.format(label))
                submit_seq = phys
            else:
                submit_seq = seq

            payload = (struct.pack('>B', zid) + auth_key +
                       struct.pack('>I', len(submit_seq)) + bytes(submit_seq))
            req_id += 1
            st, _, rpay = udp_send(sock, OP_SUBMIT, req_id, payload)

            entry = {'sequence_length': len(seq)}
            if z['encoding']:
                entry['physical_length'] = len(phys)

            if st == ST_CRACKED:
                code = rpay.decode()
                entry['code'] = code
                print("  CRACKED: code={}".format(code))
            else:
                print("  FAILED (status={})".format(st))
                if rpay:
                    print("  Detail: {}".format(rpay))

            results[label] = entry

    # Write final results
    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("\n=== Results saved to /app/results.json ===")
    sock.close()


if __name__ == '__main__':
    main()
