#!/usr/bin/env python3
"""Generate forensic evidence for AD attack chain forensic analysis task.

Scenario: Attacker compromised t.chen via phishing, Kerberoasted svc_sqlprod,
exploited ADCS ESC1 vulnerability in VPNAccess template to impersonate
Domain Admin j.rodriguez via certificate with forged UPN SAN.
"""

import json
import os
import hmac
import hashlib
import struct
import random
import datetime as dt

from Crypto.Hash import MD4
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

random.seed(42)
BASE = "/app/evidence"

# ================================================================
# Directory setup
# ================================================================
def setup_dirs():
    for d in [BASE, f"{BASE}/parsed_tickets", f"{BASE}/certificates"]:
        os.makedirs(d, exist_ok=True)
    os.makedirs("/app/answers", exist_ok=True)

# ================================================================
# Crypto helpers
# ================================================================
def ntlm(pw):
    h = MD4.new()
    h.update(pw.encode('utf-16le'))
    return h.digest()

def rc4(key, data):
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]
    i = j = 0
    out = bytearray()
    for b in data:
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        out.append(b ^ S[(S[i] + S[j]) % 256])
    return bytes(out)

def make_krb5tgs(pw, user, realm, spn):
    """Generate valid $krb5tgs$23$ hash crackable by john/hashcat."""
    nt = ntlm(pw)
    k1 = hmac.new(nt, struct.pack('<I', 2), hashlib.md5).digest()
    plain = bytes(random.getrandbits(8) for _ in range(248))
    chk = hmac.new(k1, plain, hashlib.md5).digest()
    k3 = hmac.new(k1, chk, hashlib.md5).digest()
    enc = rc4(k3, plain)
    return f"$krb5tgs$23$*{user}${realm}${spn}*${chk.hex()}${enc.hex()}"

# ================================================================
# Name pools
# ================================================================
FIRST = [
    "James","Mary","Robert","Patricia","John","Jennifer","Michael","Linda",
    "David","Elizabeth","William","Barbara","Richard","Susan","Joseph","Jessica",
    "Thomas","Sarah","Christopher","Karen","Charles","Lisa","Daniel","Nancy",
    "Matthew","Betty","Anthony","Margaret","Mark","Sandra","Donald","Ashley",
    "Steven","Dorothy","Andrew","Kimberly","Paul","Emily","Joshua","Donna"
]
LAST = [
    "Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis",
    "Wilson","Anderson","Thomas","Taylor","Moore","Jackson","Martin",
    "Lee","Perez","Thompson","White","Harris","Clark","Lewis","Walker",
    "Young","Allen","King","Wright","Scott","Torres","Hill"
]
DEPTS = ["Marketing","Engineering","Finance","HR","Sales","Legal","Operations","IT"]

# ================================================================
# AD Snapshot generation
# ================================================================
def gen_regular_users():
    users = []
    seen = set()
    for i in range(32):
        fn, ln = FIRST[i], LAST[i % len(LAST)]
        sam = f"{fn[0].lower()}.{ln.lower()}"
        if sam in seen:
            sam = f"{fn[:2].lower()}.{ln.lower()}"
        seen.add(sam)
        dept = DEPTS[i % len(DEPTS)]
        users.append({
            "dn": f"CN={fn} {ln},OU={dept},OU=Departments,DC=meridian,DC=local",
            "objectClass": "user",
            "sAMAccountName": sam,
            "userPrincipalName": f"{sam}@meridian.local",
            "displayName": f"{fn} {ln}",
            "description": f"{dept} Staff",
            "memberOf": [
                "CN=Domain Users,CN=Users,DC=meridian,DC=local",
                f"CN={dept},OU=Department Groups,DC=meridian,DC=local"
            ],
            "userAccountControl": 512,
            "servicePrincipalName": [],
            "msDS-AllowedToDelegateTo": [],
            "msDS-AllowedToActOnBehalfOfOtherIdentity": None,
            "adminCount": 0,
            "pwdLastSet": f"2024-{random.randint(1,10):02d}-{random.randint(1,28):02d}T10:00:00Z",
            "lastLogon": f"2024-11-{random.randint(10,14)}T{random.randint(8,17):02d}:{random.randint(0,59):02d}:00Z",
            "whenCreated": f"2023-{random.randint(1,12):02d}-{random.randint(1,28):02d}T08:00:00Z",
            "enabled": True
        })
    return users

def gen_special_users():
    return [
        {
            "dn": "CN=Tom Chen,OU=Marketing,OU=Departments,DC=meridian,DC=local",
            "objectClass": "user",
            "sAMAccountName": "t.chen",
            "userPrincipalName": "t.chen@meridian.local",
            "displayName": "Tom Chen",
            "description": "Marketing Analyst - Digital Campaigns",
            "memberOf": [
                "CN=Domain Users,CN=Users,DC=meridian,DC=local",
                "CN=Marketing,OU=Department Groups,DC=meridian,DC=local"
            ],
            "userAccountControl": 512,
            "servicePrincipalName": [],
            "msDS-AllowedToDelegateTo": [],
            "msDS-AllowedToActOnBehalfOfOtherIdentity": None,
            "adminCount": 0,
            "pwdLastSet": "2024-09-15T10:30:00Z",
            "lastLogon": "2024-11-15T08:23:41Z",
            "whenCreated": "2023-03-01T08:00:00Z",
            "enabled": True
        },
        {
            "dn": "CN=SQL Production Service,OU=Service Accounts,DC=meridian,DC=local",
            "objectClass": "user",
            "sAMAccountName": "svc_sqlprod",
            "userPrincipalName": "svc_sqlprod@meridian.local",
            "displayName": "SQL Production Service",
            "description": "Service account for production SQL Server instance on SQL01",
            "memberOf": [
                "CN=Domain Users,CN=Users,DC=meridian,DC=local",
                "CN=SQL Admins,OU=Service Groups,DC=meridian,DC=local",
                "CN=VPN Users,OU=Service Groups,DC=meridian,DC=local"
            ],
            "userAccountControl": 524800,
            "servicePrincipalName": [
                "MSSQLSvc/SQL01.meridian.local:1433",
                "MSSQLSvc/SQL01.meridian.local"
            ],
            "msDS-AllowedToDelegateTo": [
                "MSSQLSvc/DB-ANALYTICS.meridian.local:1433",
                "MSSQLSvc/DB-ANALYTICS.meridian.local"
            ],
            "msDS-AllowedToActOnBehalfOfOtherIdentity": None,
            "TRUSTED_TO_AUTH_FOR_DELEGATION": True,
            "adminCount": 0,
            "pwdLastSet": "2024-01-10T14:00:00Z",
            "lastLogon": "2024-11-15T12:00:00Z",
            "whenCreated": "2022-06-15T09:00:00Z",
            "enabled": True
        },
        {
            "dn": "CN=Backup Service,OU=Service Accounts,DC=meridian,DC=local",
            "objectClass": "user",
            "sAMAccountName": "svc_backup",
            "userPrincipalName": "svc_backup@meridian.local",
            "displayName": "Backup Service",
            "description": "Service account for Veeam Backup on BACKUP01",
            "memberOf": [
                "CN=Domain Users,CN=Users,DC=meridian,DC=local",
                "CN=Backup Operators,CN=Builtin,DC=meridian,DC=local"
            ],
            "userAccountControl": 512,
            "servicePrincipalName": [
                "CIFS/BACKUP01.meridian.local",
                "HOST/BACKUP01.meridian.local"
            ],
            "msDS-AllowedToDelegateTo": [],
            "msDS-AllowedToActOnBehalfOfOtherIdentity": None,
            "adminCount": 0,
            "pwdLastSet": "2024-03-20T09:00:00Z",
            "lastLogon": "2024-11-14T23:00:00Z",
            "whenCreated": "2022-01-10T08:00:00Z",
            "enabled": True
        },
        {
            "dn": "CN=Web Application Service,OU=Service Accounts,DC=meridian,DC=local",
            "objectClass": "user",
            "sAMAccountName": "svc_web",
            "userPrincipalName": "svc_web@meridian.local",
            "displayName": "Web Application Service",
            "description": "Service account for IIS on WEB01",
            "memberOf": [
                "CN=Domain Users,CN=Users,DC=meridian,DC=local",
                "CN=Web Admins,OU=Service Groups,DC=meridian,DC=local"
            ],
            "userAccountControl": 512,
            "servicePrincipalName": [
                "HTTP/WEB01.meridian.local",
                "HTTP/WEB01.meridian.local:443"
            ],
            "msDS-AllowedToDelegateTo": [],
            "msDS-AllowedToActOnBehalfOfOtherIdentity": None,
            "adminCount": 0,
            "pwdLastSet": "2024-05-12T11:00:00Z",
            "lastLogon": "2024-11-15T06:00:00Z",
            "whenCreated": "2022-09-01T08:00:00Z",
            "enabled": True
        },
        {
            "dn": "CN=Juan Rodriguez,OU=IT,OU=Departments,DC=meridian,DC=local",
            "objectClass": "user",
            "sAMAccountName": "j.rodriguez",
            "userPrincipalName": "j.rodriguez@meridian.local",
            "displayName": "Juan Rodriguez",
            "description": "IT Director",
            "memberOf": [
                "CN=Domain Users,CN=Users,DC=meridian,DC=local",
                "CN=Domain Admins,CN=Users,DC=meridian,DC=local",
                "CN=IT,OU=Department Groups,DC=meridian,DC=local",
                "CN=Enterprise Admins,CN=Users,DC=meridian,DC=local"
            ],
            "userAccountControl": 512,
            "servicePrincipalName": [],
            "msDS-AllowedToDelegateTo": [],
            "msDS-AllowedToActOnBehalfOfOtherIdentity": None,
            "adminCount": 1,
            "pwdLastSet": "2024-10-01T08:00:00Z",
            "lastLogon": "2024-11-15T09:32:07Z",
            "whenCreated": "2021-01-15T08:00:00Z",
            "enabled": True
        },
        {
            "dn": "CN=Kavita Patel,OU=IT,OU=Departments,DC=meridian,DC=local",
            "objectClass": "user",
            "sAMAccountName": "k.patel",
            "userPrincipalName": "k.patel@meridian.local",
            "displayName": "Kavita Patel",
            "description": "Senior Systems Administrator",
            "memberOf": [
                "CN=Domain Users,CN=Users,DC=meridian,DC=local",
                "CN=Domain Admins,CN=Users,DC=meridian,DC=local",
                "CN=IT,OU=Department Groups,DC=meridian,DC=local"
            ],
            "userAccountControl": 512,
            "servicePrincipalName": [],
            "msDS-AllowedToDelegateTo": [],
            "msDS-AllowedToActOnBehalfOfOtherIdentity": None,
            "adminCount": 1,
            "pwdLastSet": "2024-08-22T14:00:00Z",
            "lastLogon": "2024-11-14T16:30:00Z",
            "whenCreated": "2021-06-01T08:00:00Z",
            "enabled": True
        },
        {
            "dn": "CN=Michael OConnor,OU=IT,OU=Departments,DC=meridian,DC=local",
            "objectClass": "user",
            "sAMAccountName": "m.oconnor",
            "userPrincipalName": "m.oconnor@meridian.local",
            "displayName": "Michael O'Connor",
            "description": "Network Administrator",
            "memberOf": [
                "CN=Domain Users,CN=Users,DC=meridian,DC=local",
                "CN=DnsAdmins,CN=Users,DC=meridian,DC=local",
                "CN=IT,OU=Department Groups,DC=meridian,DC=local"
            ],
            "userAccountControl": 512,
            "servicePrincipalName": [],
            "msDS-AllowedToDelegateTo": [],
            "msDS-AllowedToActOnBehalfOfOtherIdentity": None,
            "adminCount": 0,
            "pwdLastSet": "2024-07-15T10:00:00Z",
            "lastLogon": "2024-11-14T17:00:00Z",
            "whenCreated": "2022-02-01T08:00:00Z",
            "enabled": True
        },
        {
            "dn": "CN=ADFS Service,OU=Service Accounts,DC=meridian,DC=local",
            "objectClass": "user",
            "sAMAccountName": "svc_adfs",
            "userPrincipalName": "svc_adfs@meridian.local",
            "displayName": "ADFS Service",
            "description": "Service account for AD Federation Services",
            "memberOf": [
                "CN=Domain Users,CN=Users,DC=meridian,DC=local"
            ],
            "userAccountControl": 512,
            "servicePrincipalName": [],
            "msDS-AllowedToDelegateTo": [
                "HOST/ADFS01.meridian.local"
            ],
            "msDS-AllowedToActOnBehalfOfOtherIdentity": None,
            "adminCount": 0,
            "pwdLastSet": "2024-06-01T08:00:00Z",
            "lastLogon": "2024-11-15T07:00:00Z",
            "whenCreated": "2023-01-15T08:00:00Z",
            "enabled": True
        }
    ]

def gen_computers():
    return [
        {
            "dn": "CN=DC01,OU=Domain Controllers,DC=meridian,DC=local",
            "objectClass": "computer", "sAMAccountName": "DC01$",
            "dNSHostName": "DC01.meridian.local",
            "operatingSystem": "Windows Server 2022 Standard",
            "userAccountControl": 532480,
            "servicePrincipalName": ["ldap/DC01.meridian.local","HOST/DC01.meridian.local","GC/DC01.meridian.local"],
            "msDS-AllowedToDelegateTo": [],
            "TRUSTED_FOR_DELEGATION": True
        },
        {
            "dn": "CN=SQL01,OU=Servers,DC=meridian,DC=local",
            "objectClass": "computer", "sAMAccountName": "SQL01$",
            "dNSHostName": "SQL01.meridian.local",
            "operatingSystem": "Windows Server 2022 Standard",
            "userAccountControl": 4096,
            "servicePrincipalName": ["HOST/SQL01.meridian.local","MSSQLSvc/SQL01.meridian.local:1433"],
            "msDS-AllowedToDelegateTo": []
        },
        {
            "dn": "CN=BACKUP01,OU=Servers,DC=meridian,DC=local",
            "objectClass": "computer", "sAMAccountName": "BACKUP01$",
            "dNSHostName": "BACKUP01.meridian.local",
            "operatingSystem": "Windows Server 2022 Standard",
            "userAccountControl": 532480,
            "servicePrincipalName": ["HOST/BACKUP01.meridian.local","CIFS/BACKUP01.meridian.local"],
            "msDS-AllowedToDelegateTo": [],
            "TRUSTED_FOR_DELEGATION": True
        },
        {
            "dn": "CN=WEB01,OU=Servers,DC=meridian,DC=local",
            "objectClass": "computer", "sAMAccountName": "WEB01$",
            "dNSHostName": "WEB01.meridian.local",
            "operatingSystem": "Windows Server 2022 Standard",
            "userAccountControl": 4096,
            "servicePrincipalName": ["HOST/WEB01.meridian.local","HTTP/WEB01.meridian.local"],
            "msDS-AllowedToDelegateTo": []
        },
        {
            "dn": "CN=DB-ANALYTICS,OU=Servers,DC=meridian,DC=local",
            "objectClass": "computer", "sAMAccountName": "DB-ANALYTICS$",
            "dNSHostName": "DB-ANALYTICS.meridian.local",
            "operatingSystem": "Windows Server 2022 Standard",
            "userAccountControl": 4096,
            "servicePrincipalName": ["HOST/DB-ANALYTICS.meridian.local","MSSQLSvc/DB-ANALYTICS.meridian.local:1433"],
            "msDS-AllowedToDelegateTo": []
        },
        {
            "dn": "CN=ADCS01,OU=Servers,DC=meridian,DC=local",
            "objectClass": "computer", "sAMAccountName": "ADCS01$",
            "dNSHostName": "ADCS01.meridian.local",
            "operatingSystem": "Windows Server 2022 Standard",
            "userAccountControl": 4096,
            "servicePrincipalName": ["HOST/ADCS01.meridian.local"],
            "msDS-AllowedToDelegateTo": []
        },
        {
            "dn": "CN=FILE01,OU=Servers,DC=meridian,DC=local",
            "objectClass": "computer", "sAMAccountName": "FILE01$",
            "dNSHostName": "FILE01.meridian.local",
            "operatingSystem": "Windows Server 2022 Standard",
            "userAccountControl": 4096,
            "servicePrincipalName": ["HOST/FILE01.meridian.local","CIFS/FILE01.meridian.local"],
            "msDS-AllowedToDelegateTo": []
        },
        {
            "dn": "CN=WS-MKTG04,OU=Workstations,DC=meridian,DC=local",
            "objectClass": "computer", "sAMAccountName": "WS-MKTG04$",
            "dNSHostName": "WS-MKTG04.meridian.local",
            "operatingSystem": "Windows 11 Enterprise",
            "userAccountControl": 4096,
            "servicePrincipalName": ["HOST/WS-MKTG04.meridian.local"],
            "msDS-AllowedToDelegateTo": []
        }
    ]

def gen_groups():
    return [
        {"dn":"CN=Domain Users,CN=Users,DC=meridian,DC=local","sAMAccountName":"Domain Users","description":"All domain users","members":"(all users)"},
        {"dn":"CN=Domain Admins,CN=Users,DC=meridian,DC=local","sAMAccountName":"Domain Admins","description":"Designated administrators of the domain","members":["j.rodriguez","k.patel"]},
        {"dn":"CN=Enterprise Admins,CN=Users,DC=meridian,DC=local","sAMAccountName":"Enterprise Admins","description":"Designated administrators of the enterprise","members":["j.rodriguez"]},
        {"dn":"CN=DnsAdmins,CN=Users,DC=meridian,DC=local","sAMAccountName":"DnsAdmins","description":"DNS Administrators Group","members":["m.oconnor"]},
        {"dn":"CN=Backup Operators,CN=Builtin,DC=meridian,DC=local","sAMAccountName":"Backup Operators","description":"Backup Operators can override security restrictions","members":["svc_backup"]},
        {"dn":"CN=SQL Admins,OU=Service Groups,DC=meridian,DC=local","sAMAccountName":"SQL Admins","description":"SQL Server administration group","members":["svc_sqlprod"]},
        {"dn":"CN=VPN Users,OU=Service Groups,DC=meridian,DC=local","sAMAccountName":"VPN Users","description":"Users authorized for VPN certificate enrollment","members":["svc_sqlprod","j.smith","m.johnson","r.williams"]},
        {"dn":"CN=Web Admins,OU=Service Groups,DC=meridian,DC=local","sAMAccountName":"Web Admins","description":"Web server administration","members":["svc_web"]},
        {"dn":"CN=Marketing,OU=Department Groups,DC=meridian,DC=local","sAMAccountName":"Marketing","description":"Marketing department","members":["t.chen","j.smith","p.brown"]},
        {"dn":"CN=Engineering,OU=Department Groups,DC=meridian,DC=local","sAMAccountName":"Engineering","description":"Engineering department","members":["m.johnson","j.jones","d.davis"]},
        {"dn":"CN=Finance,OU=Department Groups,DC=meridian,DC=local","sAMAccountName":"Finance","description":"Finance department","members":["r.williams","p.garcia","e.wilson"]},
        {"dn":"CN=IT,OU=Department Groups,DC=meridian,DC=local","sAMAccountName":"IT","description":"IT department","members":["j.rodriguez","k.patel","m.oconnor"]},
        {"dn":"CN=Cert Publishers,CN=Users,DC=meridian,DC=local","sAMAccountName":"Cert Publishers","description":"Members are permitted to publish certificates","members":["DC01$","ADCS01$"]},
        {"dn":"CN=Protected Users,CN=Users,DC=meridian,DC=local","sAMAccountName":"Protected Users","description":"Members of this group are afforded additional protections","members":["k.patel"]},
        {"dn":"CN=Schema Admins,CN=Users,DC=meridian,DC=local","sAMAccountName":"Schema Admins","description":"Schema Administrators","members":["j.rodriguez"]}
    ]

def gen_cert_templates():
    return [
        {
            "name": "User",
            "displayName": "User",
            "objectClass": "pKICertificateTemplate",
            "msPKI-Certificate-Name-Flag": 0x82000000,
            "msPKI-Enrollment-Flag": 41,
            "msPKI-RA-Signature": 0,
            "pKIExtendedKeyUsage": ["1.3.6.1.5.5.7.3.4","1.3.6.1.5.5.7.3.2","1.3.6.1.4.1.311.10.3.4"],
            "pKIExtendedKeyUsage_names": ["Secure Email","Client Authentication","Encrypting File System"],
            "enrollment_permissions": {"enroll":["MERIDIAN\\Domain Users"],"autoenroll":["MERIDIAN\\Domain Users"]},
            "validity_period": "1 year",
            "flags": {"ENROLLEE_SUPPLIES_SUBJECT": False,"CT_FLAG_ENROLLEE_SUPPLIES_SUBJECT_ALT_NAME": False}
        },
        {
            "name": "Machine",
            "displayName": "Machine",
            "objectClass": "pKICertificateTemplate",
            "msPKI-Certificate-Name-Flag": 0x18000000,
            "msPKI-Enrollment-Flag": 32,
            "msPKI-RA-Signature": 0,
            "pKIExtendedKeyUsage": ["1.3.6.1.5.5.7.3.2","1.3.6.1.5.5.7.3.1"],
            "pKIExtendedKeyUsage_names": ["Client Authentication","Server Authentication"],
            "enrollment_permissions": {"enroll":["MERIDIAN\\Domain Computers"],"autoenroll":["MERIDIAN\\Domain Computers"]},
            "validity_period": "1 year",
            "flags": {"ENROLLEE_SUPPLIES_SUBJECT": False,"CT_FLAG_ENROLLEE_SUPPLIES_SUBJECT_ALT_NAME": False}
        },
        {
            "name": "WebServerAuth",
            "displayName": "Web Server Authentication",
            "objectClass": "pKICertificateTemplate",
            "msPKI-Certificate-Name-Flag": 0x08000000,
            "msPKI-Enrollment-Flag": 0,
            "msPKI-RA-Signature": 1,
            "pKIExtendedKeyUsage": ["1.3.6.1.5.5.7.3.1"],
            "pKIExtendedKeyUsage_names": ["Server Authentication"],
            "enrollment_permissions": {"enroll":["MERIDIAN\\Web Admins"],"autoenroll":[]},
            "validity_period": "2 years",
            "flags": {"ENROLLEE_SUPPLIES_SUBJECT": True,"CT_FLAG_ENROLLEE_SUPPLIES_SUBJECT_ALT_NAME": True}
        },
        {
            "name": "VPNAccess",
            "displayName": "VPN Access Certificate",
            "objectClass": "pKICertificateTemplate",
            "msPKI-Certificate-Name-Flag": 1,
            "msPKI-Enrollment-Flag": 0,
            "msPKI-RA-Signature": 0,
            "pKIExtendedKeyUsage": ["1.3.6.1.5.5.7.3.2"],
            "pKIExtendedKeyUsage_names": ["Client Authentication"],
            "msPKI-Certificate-Application-Policy": ["1.3.6.1.5.5.7.3.2"],
            "enrollment_permissions": {"enroll":["MERIDIAN\\VPN Users"],"autoenroll":[]},
            "validity_period": "1 year",
            "renewal_period": "6 weeks",
            "flags": {"ENROLLEE_SUPPLIES_SUBJECT": True,"CT_FLAG_ENROLLEE_SUPPLIES_SUBJECT_ALT_NAME": True}
        },
        {
            "name": "CodeSigning",
            "displayName": "Code Signing",
            "objectClass": "pKICertificateTemplate",
            "msPKI-Certificate-Name-Flag": 0x82000000,
            "msPKI-Enrollment-Flag": 0,
            "msPKI-RA-Signature": 0,
            "pKIExtendedKeyUsage": ["1.3.6.1.5.5.7.3.3"],
            "pKIExtendedKeyUsage_names": ["Code Signing"],
            "enrollment_permissions": {"enroll":["MERIDIAN\\Engineering"],"autoenroll":[]},
            "validity_period": "1 year",
            "flags": {"ENROLLEE_SUPPLIES_SUBJECT": False,"CT_FLAG_ENROLLEE_SUPPLIES_SUBJECT_ALT_NAME": False}
        },
        {
            "name": "SmartCardLogon",
            "displayName": "Smart Card Logon",
            "objectClass": "pKICertificateTemplate",
            "msPKI-Certificate-Name-Flag": 0x18000000,
            "msPKI-Enrollment-Flag": 0,
            "msPKI-RA-Signature": 0,
            "pKIExtendedKeyUsage": ["1.3.6.1.4.1.311.20.2.2","1.3.6.1.5.5.7.3.2"],
            "pKIExtendedKeyUsage_names": ["Smart Card Logon","Client Authentication"],
            "enrollment_permissions": {"enroll":["MERIDIAN\\Domain Users"],"autoenroll":[]},
            "validity_period": "1 year",
            "flags": {"ENROLLEE_SUPPLIES_SUBJECT": False,"CT_FLAG_ENROLLEE_SUPPLIES_SUBJECT_ALT_NAME": False}
        }
    ]

def gen_ad_snapshot():
    regular = gen_regular_users()
    special = gen_special_users()
    return {
        "snapshot_time": "2024-11-16T02:00:00Z",
        "domain_info": {
            "name": "meridian.local",
            "netbios": "MERIDIAN",
            "domain_sid": "S-1-5-21-3842873421-1492877721-2853267891",
            "forest_root": "meridian.local",
            "domain_functional_level": "Windows Server 2022",
            "schema_version": 88
        },
        "trust_relationships": [
            {
                "trusted_domain": "partner.local",
                "trust_direction": "Bidirectional",
                "trust_type": "Forest",
                "trust_attributes": "FOREST_TRANSITIVE",
                "sid_filtering": True,
                "selective_authentication": False
            }
        ],
        "certificate_authorities": [
            {
                "name": "MERIDIAN-DC01-CA",
                "dns_name": "DC01.meridian.local",
                "certificate_templates": ["User","Machine","WebServerAuth","VPNAccess","CodeSigning","SmartCardLogon"],
                "ca_type": "Enterprise Root CA",
                "web_enrollment": True,
                "EDITF_ATTRIBUTESUBJECTALTNAME2": False
            }
        ],
        "certificate_templates": gen_cert_templates(),
        "users": regular + special,
        "computers": gen_computers(),
        "groups": gen_groups()
    }

# ================================================================
# Security event log
# ================================================================
def gen_events():
    events = []
    eid = 1000

    # Background noise: normal TGT/TGS for various users
    noise_users = ["j.smith","m.johnson","r.williams","p.brown","j.jones",
                   "m.garcia","d.davis","e.wilson","w.anderson","b.thomas",
                   "k.patel","m.oconnor","j.rodriguez"]
    noise_spns = [
        "CIFS/FILE01.meridian.local","HTTP/WEB01.meridian.local",
        "ldap/DC01.meridian.local","HOST/SQL01.meridian.local",
        "CIFS/DC01.meridian.local","HOST/WEB01.meridian.local",
        "HOST/FILE01.meridian.local"
    ]

    for hour in range(7, 19):
        for _ in range(random.randint(5, 9)):
            user = random.choice(noise_users)
            eid += 1
            events.append({
                "EventRecordID": eid,
                "EventID": 4768,
                "TimeCreated": f"2024-11-15T{hour:02d}:{random.randint(0,59):02d}:{random.randint(0,59):02d}Z",
                "TargetUserName": user,
                "TargetDomainName": "MERIDIAN.LOCAL",
                "TicketEncryptionType": "0x12",
                "PreAuthType": "2",
                "IpAddress": f"10.10.{random.randint(1,50)}.{random.randint(10,250)}",
                "Status": "0x0",
                "ServiceName": "krbtgt"
            })

            if random.random() > 0.3:
                eid += 1
                events.append({
                    "EventRecordID": eid,
                    "EventID": 4769,
                    "TimeCreated": f"2024-11-15T{hour:02d}:{random.randint(0,59):02d}:{random.randint(0,59):02d}Z",
                    "TargetUserName": f"{user}@MERIDIAN.LOCAL",
                    "ServiceName": random.choice(noise_spns),
                    "TicketEncryptionType": "0x12",
                    "IpAddress": f"10.10.{random.randint(1,50)}.{random.randint(10,250)}",
                    "Status": "0x0",
                    "TicketOptions": "0x40810000"
                })

    # Some failed pre-auth (noise)
    for _ in range(8):
        eid += 1
        events.append({
            "EventRecordID": eid,
            "EventID": 4771,
            "TimeCreated": f"2024-11-15T{random.randint(8,17):02d}:{random.randint(0,59):02d}:{random.randint(0,59):02d}Z",
            "TargetUserName": random.choice(noise_users),
            "TargetDomainName": "MERIDIAN.LOCAL",
            "Status": "0x18",
            "PreAuthType": "2",
            "IpAddress": f"10.10.{random.randint(1,50)}.{random.randint(10,250)}",
            "FailureCode": "0x18"
        })

    # ====== ATTACK EVENTS ======

    # 1. t.chen TGT (initial compromise - normal looking)
    events.append({
        "EventRecordID": 5001,
        "EventID": 4768,
        "TimeCreated": "2024-11-15T08:23:41Z",
        "TargetUserName": "t.chen",
        "TargetDomainName": "MERIDIAN.LOCAL",
        "TicketEncryptionType": "0x12",
        "PreAuthType": "2",
        "IpAddress": "10.10.14.33",
        "Status": "0x0",
        "ServiceName": "krbtgt"
    })

    # 2. Kerberoasting - TGS requests with RC4 (etype 0x17)
    for spn, ts in [
        ("MSSQLSvc/SQL01.meridian.local:1433", "08:45:12"),
        ("MSSQLSvc/SQL01.meridian.local", "08:45:15"),
        ("CIFS/BACKUP01.meridian.local", "08:46:33"),
        ("HOST/BACKUP01.meridian.local", "08:46:35"),
        ("HTTP/WEB01.meridian.local", "08:46:44"),
        ("HTTP/WEB01.meridian.local:443", "08:46:45")
    ]:
        events.append({
            "EventRecordID": 5010 + len([e for e in events if e.get("EventRecordID",0)>5000]),
            "EventID": 4769,
            "TimeCreated": f"2024-11-15T{ts}Z",
            "TargetUserName": "t.chen@MERIDIAN.LOCAL",
            "ServiceName": spn,
            "TicketEncryptionType": "0x17",
            "IpAddress": "10.10.14.33",
            "Status": "0x0",
            "TicketOptions": "0x40810000"
        })

    # 3. svc_sqlprod TGT from attacker workstation
    events.append({
        "EventRecordID": 5020,
        "EventID": 4768,
        "TimeCreated": "2024-11-15T09:15:33Z",
        "TargetUserName": "svc_sqlprod",
        "TargetDomainName": "MERIDIAN.LOCAL",
        "TicketEncryptionType": "0x12",
        "PreAuthType": "2",
        "IpAddress": "10.10.14.33",
        "Status": "0x0",
        "ServiceName": "krbtgt"
    })

    # 4. Certificate request and issuance
    events.append({
        "EventRecordID": 5030,
        "EventID": 4886,
        "TimeCreated": "2024-11-15T09:28:51Z",
        "Requester": "MERIDIAN\\svc_sqlprod",
        "CertificateTemplate": "VPNAccess",
        "IpAddress": "10.10.14.33",
        "Attributes": "CertificateTemplate:VPNAccess\nSAN:otherName:1.3.6.1.4.1.311.20.2.3;UTF8:j.rodriguez@meridian.local"
    })
    events.append({
        "EventRecordID": 5031,
        "EventID": 4887,
        "TimeCreated": "2024-11-15T09:28:52Z",
        "Requester": "MERIDIAN\\svc_sqlprod",
        "CertificateTemplate": "VPNAccess",
        "SubjectName": "CN=svc_sqlprod",
        "SerialNumber": "4A00000008B3C2F1E7D94A2100000000000008",
        "Disposition": "Issued"
    })

    # 5. PKINIT TGT for j.rodriguez (certificate-based auth)
    events.append({
        "EventRecordID": 5040,
        "EventID": 4768,
        "TimeCreated": "2024-11-15T09:32:07Z",
        "TargetUserName": "j.rodriguez",
        "TargetDomainName": "MERIDIAN.LOCAL",
        "TicketEncryptionType": "0x12",
        "PreAuthType": "16",
        "CertIssuerName": "MERIDIAN-DC01-CA",
        "CertSerialNumber": "4A00000008B3C2F1E7D94A2100000000000008",
        "IpAddress": "10.10.14.33",
        "Status": "0x0",
        "ServiceName": "krbtgt"
    })

    # 6. j.rodriguez accessing DC (post-compromise)
    events.append({
        "EventRecordID": 5041,
        "EventID": 4769,
        "TimeCreated": "2024-11-15T09:32:15Z",
        "TargetUserName": "j.rodriguez@MERIDIAN.LOCAL",
        "ServiceName": "CIFS/DC01.meridian.local",
        "TicketEncryptionType": "0x12",
        "IpAddress": "10.10.14.33",
        "Status": "0x0",
        "TicketOptions": "0x40810000"
    })
    events.append({
        "EventRecordID": 5042,
        "EventID": 4769,
        "TimeCreated": "2024-11-15T09:32:22Z",
        "TargetUserName": "j.rodriguez@MERIDIAN.LOCAL",
        "ServiceName": "ldap/DC01.meridian.local",
        "TicketEncryptionType": "0x12",
        "IpAddress": "10.10.14.33",
        "Status": "0x0",
        "TicketOptions": "0x40810000"
    })

    events.sort(key=lambda e: e["TimeCreated"])
    return events

# ================================================================
# Kerberoast hashes
# ================================================================
def gen_kerberoast_hashes():
    hashes = []
    # Crackable hash
    hashes.append(make_krb5tgs("Producti0n!", "svc_sqlprod", "MERIDIAN.LOCAL",
                               "MSSQLSvc/SQL01.meridian.local"))
    # Non-crackable hashes (strong passwords)
    hashes.append(make_krb5tgs(
        "x" + hashlib.sha256(b"backup_svc_strong_2024_v2").hexdigest()[:28] + "!Q",
        "svc_backup", "MERIDIAN.LOCAL", "CIFS/BACKUP01.meridian.local"))
    hashes.append(make_krb5tgs(
        "x" + hashlib.sha256(b"web_svc_strong_2024_v2").hexdigest()[:28] + "!Q",
        "svc_web", "MERIDIAN.LOCAL", "HTTP/WEB01.meridian.local"))
    return "\n".join(hashes) + "\n"

# ================================================================
# Parsed ticket files
# ================================================================
def gen_parsed_tickets():
    tickets = {
        "ticket_001_tgt_tchen.txt": """Forensic Capture Report
Source Host: WS-MKTG04.meridian.local (10.10.14.33)
Capture Timestamp: 2024-11-15 08:24:02 UTC
Extracted from: LSASS memory dump

Ticket cache: FILE:/tmp/krb5cc_tchen
Default principal: t.chen@MERIDIAN.LOCAL

Valid starting       Expires              Service principal
11/15/2024 08:23:41  11/15/2024 18:23:41  krbtgt/MERIDIAN.LOCAL@MERIDIAN.LOCAL
\trenew until 11/22/2024 08:23:41
\tEtype (skey, tkt): aes256-cts-hmac-sha1-96, aes256-cts-hmac-sha1-96
\tFlags: FRIA
""",
        "ticket_002_tgs_services.txt": """Forensic Capture Report
Source Host: WS-MKTG04.meridian.local (10.10.14.33)
Capture Timestamp: 2024-11-15 08:48:01 UTC
Extracted from: LSASS memory dump

Ticket cache: FILE:/tmp/krb5cc_tchen
Default principal: t.chen@MERIDIAN.LOCAL

Valid starting       Expires              Service principal
11/15/2024 08:45:12  11/15/2024 18:23:41  MSSQLSvc/SQL01.meridian.local:1433@MERIDIAN.LOCAL
\tEtype (skey, tkt): arcfour-hmac-md5, arcfour-hmac-md5
\tFlags: FRAO

11/15/2024 08:46:33  11/15/2024 18:23:41  CIFS/BACKUP01.meridian.local@MERIDIAN.LOCAL
\tEtype (skey, tkt): arcfour-hmac-md5, arcfour-hmac-md5
\tFlags: FRAO

11/15/2024 08:46:44  11/15/2024 18:23:41  HTTP/WEB01.meridian.local@MERIDIAN.LOCAL
\tEtype (skey, tkt): arcfour-hmac-md5, arcfour-hmac-md5
\tFlags: FRAO
""",
        "ticket_003_tgt_svc_sqlprod.txt": """Forensic Capture Report
Source Host: WS-MKTG04.meridian.local (10.10.14.33)
Capture Timestamp: 2024-11-15 09:16:05 UTC
Extracted from: LSASS memory dump

Ticket cache: FILE:/tmp/krb5cc_svc_sqlprod
Default principal: svc_sqlprod@MERIDIAN.LOCAL

Valid starting       Expires              Service principal
11/15/2024 09:15:33  11/15/2024 19:15:33  krbtgt/MERIDIAN.LOCAL@MERIDIAN.LOCAL
\trenew until 11/22/2024 09:15:33
\tEtype (skey, tkt): aes256-cts-hmac-sha1-96, aes256-cts-hmac-sha1-96
\tFlags: FRIA
""",
        "ticket_004_tgt_jrodriguez.txt": """Forensic Capture Report
Source Host: WS-MKTG04.meridian.local (10.10.14.33)
Capture Timestamp: 2024-11-15 09:33:00 UTC
Extracted from: LSASS memory dump

Ticket cache: FILE:/tmp/krb5cc_jrodriguez
Default principal: j.rodriguez@MERIDIAN.LOCAL

Valid starting       Expires              Service principal
11/15/2024 09:32:07  11/15/2024 19:32:07  krbtgt/MERIDIAN.LOCAL@MERIDIAN.LOCAL
\trenew until 11/22/2024 09:32:07
\tEtype (skey, tkt): aes256-cts-hmac-sha1-96, aes256-cts-hmac-sha1-96
\tFlags: FRIA
\tPre-auth type: PA-PK-AS-REQ (16)
\tCertificate Issuer: CN=MERIDIAN-DC01-CA, DC=meridian, DC=local
\tCertificate Subject: CN=svc_sqlprod
\tCertificate Serial: 4A00000008B3C2F1E7D94A2100000000000008
"""
    }
    return tickets

# ================================================================
# Wordlist
# ================================================================
def gen_wordlist():
    words = set()
    bases = ["Password","Welcome","Company","Meridian","Admin","Server",
             "Service","Network","Database","Backup","System","Access",
             "Account","Project","Security","Manager","Desktop","Office",
             "Shadow","Master","Dragon","Monkey","Qwerty","Letmein",
             "Football","Baseball","Trustno","Superman","Batman","Iloveyou"]
    suffixes = ["1","!","123","2023","2024","2023!","2024!","@1","#1","01","1!"]
    seasons = ["Spring","Summer","Fall","Winter","Autumn"]
    years = ["2022","2023","2024","2025"]

    for b in bases:
        for s in suffixes:
            words.add(f"{b}{s}")
    for s in seasons:
        for y in years:
            words.add(f"{s}{y}")
            words.add(f"{s}{y}!")
            words.add(f"{s}{y}#")

    words.update([
        "P@ssw0rd","Passw0rd!","Ch@ngeme1","Pr0duction","Producti0n!",
        "D@tabase1","Sql$erver1","B@ckup2024","W3bServ!ce","S3curity!",
        "M3ridian!","N3tw0rk01","@ccess2024","Pr0ject!","M@nager01",
        "Adm1n2024","R00tAccess","S3rv1ce!","Op3rations","C0mpany2024!",
        "Inf0Sec01","R3dTeam!","Cyb3rS3c!","H@ckth3Box","Pent3st!"
    ])

    words = list(words)
    random.shuffle(words)
    return words

# ================================================================
# Certificates (X.509)
# ================================================================
def gen_certificates():
    # CA key and cert
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    ca_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "MERIDIAN-DC01-CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Meridian Corp"),
    ])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc))
        .not_valid_after(dt.datetime(2026, 12, 31, tzinfo=dt.timezone.utc))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                         content_commitment=False, key_encipherment=False,
                         data_encipherment=False, key_agreement=False,
                         encipher_only=False, decipher_only=False),
            critical=True
        )
        .sign(ca_key, hashes.SHA256())
    )

    # Attacker's certificate (ESC1 exploitation)
    atk_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    upn = "j.rodriguez@meridian.local"
    upn_bytes = upn.encode('utf-8')
    upn_der = bytes([0x0C, len(upn_bytes)]) + upn_bytes
    upn_oid = x509.ObjectIdentifier("1.3.6.1.4.1.311.20.2.3")

    atk_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "svc_sqlprod"),
        ]))
        .issuer_name(ca_name)
        .public_key(atk_key.public_key())
        .serial_number(0x4A00000008B3C2F1E7D94A2100000000000008)
        .not_valid_before(dt.datetime(2024, 11, 15, 9, 28, 52, tzinfo=dt.timezone.utc))
        .not_valid_after(dt.datetime(2025, 11, 15, 9, 28, 52, tzinfo=dt.timezone.utc))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.OtherName(upn_oid, upn_der),
                x509.RFC822Name("svc_sqlprod@meridian.local"),
            ]),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([
                x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
            ]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    return ca_key, ca_cert, atk_key, atk_cert

# ================================================================
# Main
# ================================================================
def main():
    setup_dirs()

    # AD snapshot
    ad = gen_ad_snapshot()
    with open(f"{BASE}/ad_snapshot.json", "w") as f:
        json.dump(ad, f, indent=2)

    # Security events
    events = gen_events()
    with open(f"{BASE}/security_events.json", "w") as f:
        json.dump(events, f, indent=2)

    # Kerberoast hashes
    with open(f"{BASE}/kerberoast_hashes.txt", "w") as f:
        f.write(gen_kerberoast_hashes())

    # Parsed tickets
    for fname, content in gen_parsed_tickets().items():
        with open(f"{BASE}/parsed_tickets/{fname}", "w") as f:
            f.write(content)

    # Wordlist
    with open(f"{BASE}/wordlist.txt", "w") as f:
        f.write("\n".join(gen_wordlist()) + "\n")

    # Certificates
    ca_key, ca_cert, atk_key, atk_cert = gen_certificates()

    with open(f"{BASE}/certificates/ca_cert.pem", "wb") as f:
        f.write(ca_cert.public_bytes(serialization.Encoding.PEM))

    with open(f"{BASE}/certificates/recovered_cert.pem", "wb") as f:
        f.write(atk_cert.public_bytes(serialization.Encoding.PEM))

    with open(f"{BASE}/certificates/recovered_key.pem", "wb") as f:
        f.write(atk_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()
        ))

    print("Evidence generation complete.")

if __name__ == "__main__":
    main()
