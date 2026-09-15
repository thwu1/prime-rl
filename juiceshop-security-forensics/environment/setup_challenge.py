#!/usr/bin/env python3
"""Create forensic artifacts for the Juice Shop security forensics challenge.

Generates: RSA keys, SQLite database with users, a valid RS256 JWT,
historical coupon codes (z85-encoded), AES-encrypted progress data,
application config, and a developer backup file.
"""


import base64
import hashlib
import json
import os
import sqlite3
import struct
import subprocess
import time

INCIDENT_DIR = '/app/incident'
KEYS_DIR = '/app/.keys'
CTF_KEY = 'zLp@n=QPz;_W#ETt'

Z85_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?&<>()[]{}@%$#"


def z85_encode(data):
    """Z85-encode binary data (ZeroMQ RFC 32). Input padded to 4-byte boundary."""
    padding = (4 - len(data) % 4) % 4
    data = data + b'\x00' * padding
    result = []
    for i in range(0, len(data), 4):
        value = struct.unpack('>I', data[i:i + 4])[0]
        chars = []
        for _ in range(5):
            chars.append(Z85_CHARS[value % 85])
            value //= 85
        result.extend(reversed(chars))
    return ''.join(result)


def base64url_encode(data):
    """Base64url encode without padding."""
    if isinstance(data, str):
        data = data.encode()
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def main():
    os.makedirs(INCIDENT_DIR, exist_ok=True)
    os.makedirs(KEYS_DIR, exist_ok=True)

    generate_rsa_keys()
    create_database()
    create_jwt()
    create_coupons()
    create_encrypted_progress()
    create_config()
    create_package_backup()

    print("All forensic artifacts created successfully.")


def generate_rsa_keys():
    """Generate 2048-bit RSA key pair."""
    subprocess.run(
        ['openssl', 'genrsa', '-out', f'{KEYS_DIR}/private.pem', '2048'],
        capture_output=True, check=True
    )
    subprocess.run(
        ['openssl', 'rsa', '-in', f'{KEYS_DIR}/private.pem',
         '-pubout', '-out', f'{INCIDENT_DIR}/public.pem'],
        capture_output=True, check=True
    )


def create_database():
    """Create SQLite database with Users, Products, and Challenges tables."""
    users = [
        (1, 'admin@juice-sh.op', 'admin123', 'admin', 1, None),
        (2, 'jim@juice-sh.op', 'ncc-1701', 'customer', 1, None),
        (3, 'bender@juice-sh.op', 'OhG0dPlease1teleworK!', 'customer', 1, None),
        (4, 'chris.pike@juice-sh.op', 'mcc-1701', 'customer', 0,
         '2024-01-15T10:30:00.000Z'),
        (5, 'mc.safesearch@juice-sh.op', 'Mr. N00dles', 'customer', 1, None),
        (6, 'wurstbrot@juice-sh.op', None, 'customer', 1, None),
        (7, 'accountant@juice-sh.op', 'i am root', 'accountant', 1, None),
        (8, 'ciso@juice-sh.op', 'mD84i3rG!x', 'admin', 0,
         '2024-03-22T14:15:00.000Z'),
        (9, 'amy@juice-sh.op', 'K1fBl4!Bl4!', 'customer', 1, None),
        (10, 'support@juice-sh.op', 'J6aVjTgOpRs@ZJl!Kt#9', 'customer', 1, None),
    ]

    BCRYPT_HASH = '$2b$12$WApznUPhKKhBBuIoGnr26.aFYIoGnVuLhHjqFJMVbRw4.y7Bz9Hm'

    conn = sqlite3.connect(f'{INCIDENT_DIR}/juiceshop.sqlite')
    c = conn.cursor()

    c.execute('''CREATE TABLE Users (
        id INTEGER PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'customer',
        isActive INTEGER NOT NULL DEFAULT 1,
        deletedAt TEXT,
        createdAt TEXT DEFAULT '2024-01-01T00:00:00.000Z',
        updatedAt TEXT DEFAULT '2024-01-01T00:00:00.000Z'
    )''')

    c.execute('''CREATE TABLE Products (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        price REAL NOT NULL,
        image TEXT,
        deletedAt TEXT
    )''')

    c.execute('''CREATE TABLE Challenges (
        id INTEGER PRIMARY KEY,
        key TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        difficulty INTEGER NOT NULL,
        solved INTEGER NOT NULL DEFAULT 0
    )''')

    products = [
        (1, 'Apple Juice (1000ml)', 'The all-time classic.', 1.99,
         'apple_juice.jpg', None),
        (2, 'Orange Juice (1000ml)', 'Made from hand-picked oranges.', 2.99,
         'orange_juice.jpg', None),
        (3, 'Christmas Super-Surprise-Box (2014 Edition)',
         'Contains a random selection of 10 bottles of our tastiest juices!',
         29.99, 'undefined.jpg', '2015-02-09T00:00:00.000Z'),
        (4, 'Raspberry Juice (1000ml)', 'Made from blended Raspberry Pi.',
         4.99, 'raspberry_juice.jpg', None),
        (5, 'OWASP Juice Shop Logo (3D-printed)',
         'Handcrafted in Sweden. Extremely expensive despite lack of purpose.',
         99.99, '3d_keychain.jpg', None),
    ]
    for p in products:
        c.execute('INSERT INTO Products VALUES (?,?,?,?,?,?)', p)

    challenges = [
        (1, 'scoreBoardChallenge', 'Score Board', 'Miscellaneous', 1, 1),
        (2, 'loginAdminChallenge', 'Login Admin', 'Injection', 2, 1),
        (3, 'weakPasswordChallenge', 'Password Strength',
         'Broken Authentication', 2, 1),
        (4, 'adminSectionChallenge', 'Admin Section',
         'Broken Access Control', 2, 0),
        (5, 'forgedCouponChallenge', 'Forged Coupon',
         'Cryptographic Issues', 6, 0),
        (6, 'unionSqlInjectionChallenge', 'User Credentials',
         'Injection', 4, 0),
        (7, 'jwtUnsignedChallenge', 'Unsigned JWT',
         'Vulnerable Components', 5, 0),
    ]
    for ch in challenges:
        c.execute('INSERT INTO Challenges VALUES (?,?,?,?,?,?)', ch)

    for user in users:
        uid, email, pw, role, active, deleted = user
        if pw is None:
            h = BCRYPT_HASH
        else:
            h = hashlib.md5(pw.encode()).hexdigest()
        c.execute('INSERT INTO Users VALUES (?,?,?,?,?,?,?,?)',
                  (uid, email, h, role, active, deleted,
                   '2024-01-01T00:00:00.000Z', '2024-06-15T12:00:00.000Z'))

    conn.commit()
    conn.close()


def create_jwt():
    """Create a valid RS256-signed JWT for the admin user."""
    header = {"alg": "RS256", "typ": "JWT"}

    now = int(time.time())
    payload = {
        "status": "success",
        "data": {
            "id": 1,
            "username": "",
            "email": "admin@juice-sh.op",
            "password": hashlib.md5(b"admin123").hexdigest(),
            "role": "admin",
            "deluxeToken": "",
            "lastLoginIp": "0.0.0.0",
            "profileImage": "assets/public/images/uploads/default.svg",
            "totpSecret": "",
            "isActive": True,
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T00:00:00.000Z",
            "deletedAt": None
        },
        "iat": now,
        "exp": now + 86400
    }

    header_b64 = base64url_encode(json.dumps(header, separators=(',', ':')))
    payload_b64 = base64url_encode(json.dumps(payload, separators=(',', ':')))
    signing_input = f"{header_b64}.{payload_b64}".encode()

    result = subprocess.run(
        ['openssl', 'dgst', '-sha256', '-sign', f'{KEYS_DIR}/private.pem'],
        input=signing_input, capture_output=True, check=True
    )

    signature_b64 = base64url_encode(result.stdout)
    jwt_token = f"{header_b64}.{payload_b64}.{signature_b64}"

    with open(f'{INCIDENT_DIR}/captured_jwt.txt', 'w') as f:
        f.write(jwt_token)


def create_coupons():
    """Create historical coupon codes in z85 encoding."""
    coupons = [
        ('JAN23-10', '2023-01-15', 10),
        ('FEB23-15', '2023-02-14', 15),
        ('MAR23-20', '2023-03-10', 20),
        ('APR23-10', '2023-04-01', 10),
        ('MAY23-15', '2023-05-20', 15),
        ('JUL23-25', '2023-07-04', 25),
        ('OCT23-10', '2023-10-31', 10),
        ('DEC23-15', '2023-12-25', 15),
        ('FEB24-20', '2024-02-14', 20),
        ('JUN24-10', '2024-06-15', 10),
    ]

    with open(f'{INCIDENT_DIR}/coupon_backup.csv', 'w') as f:
        f.write('code,used_date,discount_percent\n')
        for plaintext, date, pct in coupons:
            encoded = z85_encode(plaintext.encode())
            f.write(f'{encoded},{date},{pct}\n')


def create_encrypted_progress():
    """Create AES-256-CBC encrypted hacking progress data."""
    progress = {
        "solvedChallenges": [
            "scoreBoardChallenge",
            "loginAdminChallenge",
            "weakPasswordChallenge",
            "adminSectionChallenge",
            "directoryListingChallenge",
            "forgottenDevBackupChallenge",
            "forgottenBackupChallenge",
            "unionSqlInjectionChallenge",
            "dbSchemaChallenge",
            "forgedCouponChallenge"
        ],
        "version": "17.1.1",
        "totalScore": 63
    }

    plaintext = json.dumps(progress, separators=(',', ':')).encode()

    key = hashlib.sha256(CTF_KEY.encode()).digest()
    key_hex = key.hex()

    iv = os.urandom(16)
    iv_hex = iv.hex()

    result = subprocess.run(
        ['openssl', 'enc', '-aes-256-cbc', '-K', key_hex, '-iv', iv_hex],
        input=plaintext, capture_output=True, check=True
    )
    ciphertext = result.stdout

    combined = iv + ciphertext
    encoded = base64.b64encode(combined).decode()

    with open(f'{INCIDENT_DIR}/encrypted_progress.b64', 'w') as f:
        f.write(encoded)


def create_config():
    """Create application configuration file."""
    config = {
        "server": {
            "port": 3000,
            "basePath": ""
        },
        "application": {
            "domain": "juice-sh.op",
            "name": "OWASP Juice Shop",
            "logo": "JuiceShop_Logo.png",
            "theme": "bluegrey-lightgreen",
            "showVersionNumber": True
        },
        "challenges": {
            "showSolvedNotifications": True,
            "showHints": True,
            "safetyMode": "auto",
            "ctfKey": CTF_KEY,
            "progressEncryption": {
                "algorithm": "aes-256-cbc",
                "keyDerivation": "sha256"
            }
        },
        "products": {
            "recyclePage": True,
            "feedbackEnabled": True
        }
    }

    with open(f'{INCIDENT_DIR}/app_config.json', 'w') as f:
        json.dump(config, f, indent=2)


def create_package_backup():
    """Create simulated package.json.bak with dependency info."""
    pkg = {
        "name": "juice-shop",
        "version": "17.1.1",
        "private": True,
        "description": "Probably the most modern and sophisticated insecure web application",
        "dependencies": {
            "body-parser": "~1.20.2",
            "compression": "~1.7.4",
            "cookie-parser": "~1.4.6",
            "cors": "~2.8.5",
            "express": "~4.18.2",
            "express-jwt": "0.1.3",
            "express-rate-limit": "~7.1.4",
            "hashids": "~2.3.0",
            "helmet": "~7.1.0",
            "html-entities": "~2.4.0",
            "jsonwebtoken": "0.4.0",
            "marsdb": "~0.6.11",
            "morgan": "~1.10.0",
            "multer": "~1.4.5-lts.1",
            "node-forge": "~1.3.1",
            "notevil": "~1.3.3",
            "otplib": "~12.0.1",
            "pdfkit": "~0.13.0",
            "sanitize-html": "~2.11.0",
            "sequelize": "~6.35.2",
            "serve-index": "~1.9.1",
            "socket.io": "~4.7.3",
            "sqlite3": "~5.1.7",
            "z85": "~0.0.2"
        },
        "devDependencies": {
            "@types/express": "~4.17.21",
            "@types/node": "~20.10.6",
            "jest": "~29.7.0",
            "typescript": "~5.3.3"
        }
    }

    with open(f'{INCIDENT_DIR}/package.json.bak', 'w') as f:
        json.dump(pkg, f, indent=2)


if __name__ == '__main__':
    main()
