#!/usr/bin/env python3
"""Generate forensic test data for iperf3 auth security audit task."""

import hashlib
import json
import os
import base64
import random
import subprocess

# Directories
os.makedirs('/app/forensics', exist_ok=True)

# Generate RSA key pair (2048-bit)
subprocess.run(
    ['openssl', 'genrsa', '-out', '/app/forensics/private.pem', '2048'],
    check=True, capture_output=True
)
subprocess.run(
    ['openssl', 'rsa', '-in', '/app/forensics/private.pem',
     '-outform', 'PEM', '-pubout', '-out', '/app/forensics/public.pem'],
    check=True, capture_output=True
)

# Users: (username, plaintext_password)
# Some passwords are crackable via wordlist, some are not.
# testuser+perftest share "password"; analyst+metrics share "qwerty123"
users = [
    ("admin", "P@ssw0rd123"),
    ("testuser", "password"),
    ("netadmin", "N3tw0rk!ng"),
    ("monitor", "Tr@ff1c"),
    ("backup", "backup2024"),
    ("operator", "0p3r@t0r"),
    ("analyst", "qwerty123"),
    ("engineer", "Th3rm@l!"),
    ("guest", "guest"),
    ("deployer", "d3pl0y_m3"),
    ("scanner", "Sc@nN3r99"),
    ("perftest", "password"),
    ("readonly", "r34d0nly!"),
    ("writer", "wr1t3r_"),
    ("sysadmin", "Adm!n2024"),
    ("dbadmin", "D@t@bas3"),
    ("netops", "n3t0ps_team"),
    ("security", "S3cur1ty!"),
    ("automation", "aut0m@te"),
    ("metrics", "qwerty123"),
]

# Create authorized_users.csv using iperf3's salting scheme:
#   salted = "{username}password"
#   hash = SHA256(salted)
with open('/app/forensics/authorized_users.csv', 'w') as f:
    for username, password in users:
        salted = "{%s}%s" % (username, password)
        hash_val = hashlib.sha256(salted.encode()).hexdigest()
        f.write("%s,%s\n" % (username, hash_val))

# Generate captured auth tokens using RSA encryption
# iperf3 auth token format: "user: %s\npwd:  %s\nts:   %d"
# Encrypted with RSA PKCS1v15 padding, then Base64-encoded
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding

with open('/app/forensics/public.pem', 'rb') as f:
    pubkey = serialization.load_pem_public_key(f.read())

tokens_plaintext = [
    ("admin", "P@ssw0rd123", 1718000000),       # valid credentials
    ("testuser", "password", 1718000100),         # valid credentials
    ("hacker", "letmein", 1718000200),            # user does not exist
    ("admin", "wrongpassword", 1718000300),        # wrong password
    ("guest", "guest", 1718000400),                # valid credentials
    ("netadmin", "N3tw0rk!ng", 1717990000),       # valid but anomalous timestamp
    ("operator", "0p3r@t0r", 1718000500),          # valid credentials
    ("admin", "P@ssw0rd123", 1718000600),          # valid, repeat user
]

captured_tokens = []
for i, (username, password, ts) in enumerate(tokens_plaintext):
    # Use the exact iperf3 format string
    plaintext = "user: %s\npwd:  %s\nts:   %d" % (username, password, ts)
    encrypted = pubkey.encrypt(plaintext.encode(), asym_padding.PKCS1v15())
    b64_token = base64.b64encode(encrypted).decode('ascii')
    captured_tokens.append({"id": i + 1, "token": b64_token})

with open('/app/forensics/captured_tokens.json', 'w') as f:
    json.dump(captured_tokens, f, indent=2)

# Generate wordlist (~20K entries)
# Includes some of the actual passwords used above
random.seed(42)
wordlist = set()

# Crackable passwords (present in wordlist)
crackable = ['P@ssw0rd123', 'password', 'backup2024', 'qwerty123', 'guest']
wordlist.update(crackable)

# Common passwords
common = [
    '123456', 'password1', 'admin', 'letmein', 'welcome', 'monkey',
    'dragon', 'master', 'login', 'abc123', 'shadow', 'sunshine',
    'princess', 'football', 'charlie', 'donald', 'batman', '1234567',
    '12345678', '123456789', 'qwerty', 'iloveyou', 'trustno1',
    'killer', 'jordan', 'jennifer', 'hunter', 'ranger', 'buster',
    'soccer', 'harley', 'george', 'pepper', 'daniel', 'hockey',
    'amanda', 'joshua', 'maggie', 'starwars', 'silver', 'william',
    'dallas', 'yankees', 'summer', 'michelle', 'hammer', 'taylor',
    'muffin', 'robert', 'computer', 'access', 'flower', 'michael',
    'ginger', 'sparky', 'thunder', 'matrix', 'cookie', 'secret',
    'samantha', 'andrea', 'phoenix', 'scooter', 'peanut', 'pirates',
    'asdfgh', 'zxcvbn', 'passwd', 'test', 'hello', 'world',
    'opensesame', 'changeme', 'default', 'root', 'toor', 'pass',
    'temp', 'temp123', 'abcdef', 'aaaaaa', 'public', 'private',
    'network', 'internet', 'server', 'client', 'database', 'backup',
    'security', 'firewall', 'router', 'switch', 'admin123', 'user',
    'guest123', 'test123', 'demo', 'sample', 'example', 'practice',
]
wordlist.update(common)

# Generate random passwords to pad out the wordlist
chars = 'abcdefghijklmnopqrstuvwxyz'
for i in range(18000):
    length = random.randint(4, 12)
    word = ''.join(random.choices(chars, k=length))
    wordlist.add(word)
    if random.random() < 0.15:
        wordlist.add(word + str(random.randint(0, 9999)))
    if random.random() < 0.08:
        wordlist.add(word.capitalize() + '!')
    if random.random() < 0.05:
        wordlist.add(word + '@' + str(random.randint(0, 999)))

wordlist = sorted(wordlist)

with open('/app/forensics/wordlist.txt', 'w') as f:
    for w in wordlist:
        f.write(w + '\n')

print("Test data generated successfully.")
print("  Users: %d" % len(users))
print("  Tokens: %d" % len(captured_tokens))
print("  Wordlist: %d entries" % len(wordlist))
