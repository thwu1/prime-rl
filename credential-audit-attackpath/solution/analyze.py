#!/usr/bin/env python3
"""
Analyze cracked credentials against AD structure and password policy.
Includes a pure-Python NTLM fallback cracker for environments where
john/hashcat may not crack all hashes.

Generates /app/report/findings.json.

"""

import json
import os
import struct
import subprocess
from collections import defaultdict


# ---------------------------------------------------------------------------
# Pure-Python MD4 (for NTLM fallback cracking when hashlib MD4 unavailable)
# ---------------------------------------------------------------------------

def _md4(data: bytes) -> str:
    def f(x, y, z):
        return (x & y) | (~x & z)

    def g(x, y, z):
        return (x & y) | (x & z) | (y & z)

    def h(x, y, z):
        return x ^ y ^ z

    def left_rotate(n, b):
        return ((n << b) | (n >> (32 - b))) & 0xFFFFFFFF

    msg = bytearray(data)
    orig_len = len(msg)
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg += struct.pack("<Q", orig_len * 8)

    a0, b0, c0, d0 = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476

    for i in range(0, len(msg), 64):
        block = msg[i : i + 64]
        M = struct.unpack("<16I", block)
        a, b, c, d = a0, b0, c0, d0

        for j in range(16):
            val = (a + f(b, c, d) + M[j]) & 0xFFFFFFFF
            shifts = [3, 7, 11, 19]
            a, d, c, b = d, c, b, left_rotate(val, shifts[j % 4])

        for j in range(16):
            idx = [0, 4, 8, 12, 1, 5, 9, 13, 2, 6, 10, 14, 3, 7, 11, 15][j]
            val = (a + g(b, c, d) + M[idx] + 0x5A827999) & 0xFFFFFFFF
            shifts = [3, 5, 9, 13]
            a, d, c, b = d, c, b, left_rotate(val, shifts[j % 4])

        for j in range(16):
            idx = [0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15][j]
            val = (a + h(b, c, d) + M[idx] + 0x6ED9EBA1) & 0xFFFFFFFF
            shifts = [3, 9, 11, 15]
            a, d, c, b = d, c, b, left_rotate(val, shifts[j % 4])

        a0 = (a0 + a) & 0xFFFFFFFF
        b0 = (b0 + b) & 0xFFFFFFFF
        c0 = (c0 + c) & 0xFFFFFFFF
        d0 = (d0 + d) & 0xFFFFFFFF

    return struct.pack("<4I", a0, b0, c0, d0).hex()


def ntlm_hash(password: str) -> str:
    return _md4(password.encode("utf-16-le"))


# ---------------------------------------------------------------------------
# Rule-based candidate generator (simplified hashcat-style rules)
# ---------------------------------------------------------------------------

def apply_rules(word: str) -> list[str]:
    """Generate password candidates by applying common enterprise patterns."""
    candidates = set()
    candidates.add(word)
    candidates.add(word.lower())
    candidates.add(word.capitalize())
    candidates.add(word.upper())

    specials = ["!", "#", "$", "@", "%", "&"]
    years = ["2024", "2023", "2025", "24", "23", "25"]

    for base in [word, word.lower(), word.capitalize()]:
        for s in specials:
            candidates.add(base + s)
            candidates.add(s + base)
            for y in years:
                candidates.add(base + s + y)
                candidates.add(base + y + s)
                candidates.add(base.capitalize() + s + y)
                candidates.add(base.capitalize() + y + s)
        for y in years:
            candidates.add(base + y)
            candidates.add(base.capitalize() + y)

    return list(candidates)


def python_ntlm_crack(user_hash_map: dict[str, str], wordlist_path: str) -> dict[str, str]:
    """Fallback Python-based NTLM cracker using rules."""
    words = []
    try:
        with open(wordlist_path) as f:
            words = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return {}

    # Build hash -> user lookup
    hash_to_users = defaultdict(list)
    for user, h in user_hash_map.items():
        hash_to_users[h.lower()].append(user)

    remaining_hashes = set(h.lower() for h in user_hash_map.values())
    cracked = {}

    for word in words:
        if not remaining_hashes:
            break
        candidates = apply_rules(word)
        for candidate in candidates:
            if not remaining_hashes:
                break
            h = ntlm_hash(candidate)
            if h in remaining_hashes:
                remaining_hashes.discard(h)
                for user in hash_to_users[h]:
                    cracked[user] = candidate

    return cracked


# ---------------------------------------------------------------------------
# Load results from external crackers
# ---------------------------------------------------------------------------

def load_john_results() -> dict[str, str]:
    """Parse john --show output."""
    creds = {}
    try:
        result = subprocess.run(
            ["john", "--show", "--format=nt", "/tmp/pwdump_hashes.txt"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        for line in result.stdout.strip().split("\n"):
            if ":" in line and not line.startswith("#") and "password hashes" not in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    user = parts[0].strip()
                    pwd = parts[1].strip()
                    if user and pwd:
                        creds[user] = pwd
    except Exception:
        pass
    return creds


def load_hashcat_results(user_hash_map: dict[str, str]) -> dict[str, str]:
    """Parse hashcat output file."""
    creds = {}
    try:
        if not os.path.exists("/tmp/hashcat_output.txt"):
            return creds
        hash_to_user = {}
        for user, h in user_hash_map.items():
            hash_to_user[h.lower()] = user

        with open("/tmp/hashcat_output.txt") as f:
            for line in f:
                line = line.strip()
                if line:
                    # outfile-format=2 means just the password
                    # but we need hash:password, try both
                    if ":" in line:
                        parts = line.split(":", 1)
                        h = parts[0].lower()
                        pwd = parts[1]
                        if h in hash_to_user:
                            creds[hash_to_user[h]] = pwd
                    else:
                        # Just the password, can't map back
                        pass
    except Exception:
        pass
    return creds


# ---------------------------------------------------------------------------
# Policy analysis
# ---------------------------------------------------------------------------

def check_policy_violations(
    creds: dict[str, str], policy: dict
) -> tuple[dict[str, list[str]], int]:
    violations = {
        "too_short": [],
        "no_uppercase": [],
        "no_lowercase": [],
        "no_digit": [],
        "no_special": [],
    }

    min_length = policy["policy"]["minimum_password_length"]
    complexity = policy["policy"]["complexity_requirements"]

    for user, pwd in sorted(creds.items()):
        if len(pwd) < min_length:
            violations["too_short"].append(user)
        if complexity.get("must_contain_uppercase") and not any(c.isupper() for c in pwd):
            violations["no_uppercase"].append(user)
        if complexity.get("must_contain_lowercase") and not any(c.islower() for c in pwd):
            violations["no_lowercase"].append(user)
        if complexity.get("must_contain_digit") and not any(c.isdigit() for c in pwd):
            violations["no_digit"].append(user)
        if complexity.get("must_contain_special_character") and not any(
            not c.isalnum() for c in pwd
        ):
            violations["no_special"].append(user)

    all_violators = set()
    for v_list in violations.values():
        all_violators.update(v_list)

    return violations, len(all_violators)


# ---------------------------------------------------------------------------
# AD attack graph analysis
# ---------------------------------------------------------------------------

ABUSABLE_RIGHTS = {
    "GenericAll",
    "GenericWrite",
    "WriteDACL",
    "WriteOwner",
    "SeBackupPrivilege",
    "ReadGMSAPassword",
    "ForceChangePassword",
}


def build_attack_graph(
    ad_data: dict, cracked_users: set[str]
) -> list[dict]:
    """Build directed graph of abusable AD relationships, find paths to DA."""
    group_members = {}
    for group in ad_data["groups"]:
        group_members[group["name"]] = set(group.get("members", []))

    edges = defaultdict(list)

    for acl in ad_data.get("acls", []):
        right = acl["right"]
        if right not in ABUSABLE_RIGHTS:
            continue

        source = acl["source"]
        target = acl["target"]
        source_type = acl["source_type"]
        target_type = acl["target_type"]

        source_users = (
            group_members.get(source, set()) if source_type == "group" else {source}
        )

        if right == "GenericAll" and target_type == "ou" and "Domain Controllers" in target:
            for u in source_users:
                edges[u].append(
                    (
                        "Domain Admins",
                        "DCSync",
                        f"GenericAll on Domain Controllers OU via {source} membership "
                        f"enables DCSync to extract all domain credentials",
                    )
                )

        elif right == "GenericAll" and target_type == "group":
            for u in source_users:
                edges[u].append(
                    (
                        target,
                        "GenericAll - Add Members",
                        f"GenericAll on {target} group allows adding arbitrary members",
                    )
                )

        elif right == "GenericWrite" and target_type == "user":
            for u in source_users:
                edges[u].append(
                    (
                        target,
                        "GenericWrite - Targeted Kerberoasting/RBCD",
                        f"GenericWrite on {target} allows setting SPN for Kerberoasting "
                        f"or configuring resource-based constrained delegation",
                    )
                )

        elif right == "SeBackupPrivilege":
            for u in source_users:
                edges[u].append(
                    (
                        "Domain Admins",
                        "SeBackupPrivilege - NTDS.dit Extraction",
                        f"SeBackupPrivilege on {target} allows extracting NTDS.dit "
                        f"to obtain all domain hashes including Domain Admin",
                    )
                )

        elif right == "ReadGMSAPassword":
            for u in source_users:
                edges[u].append(
                    (
                        target,
                        "ReadGMSAPassword",
                        f"Can read GMSA password of {target} to impersonate that account",
                    )
                )

    # Constrained delegation
    for user in ad_data["users"]:
        delegation = user.get("delegation")
        if delegation and delegation.get("type") == "constrained":
            for t in delegation.get("allowed_to_delegate_to", []):
                if "dc01" in t.lower():
                    edges[user["samaccountname"]].append(
                        (
                            "Domain Admins",
                            "Constrained Delegation - S4U2Self/S4U2Proxy",
                            f"Constrained delegation to {t} allows impersonating "
                            f"any user including Domain Admin to the Domain Controller",
                        )
                    )
                    break

    # Resolve multi-hop paths
    da_direct = {}

    # Pass 1: direct edges to Domain Admins
    for u, edge_list in edges.items():
        for target, technique, desc in edge_list:
            if target == "Domain Admins" and u not in da_direct:
                da_direct[u] = [(u, "Domain Admins", technique, desc)]

    # Pass 2: edges to Server Admins (which leads to DA via DCSync)
    for u, edge_list in edges.items():
        if u in da_direct:
            continue
        for target, technique, desc in edge_list:
            if target == "Server Admins":
                da_direct[u] = [
                    (u, "Server Admins", technique, desc),
                    (
                        "Server Admins",
                        "Domain Admins",
                        "DCSync",
                        "Server Admins has GenericAll on Domain Controllers OU, enabling DCSync",
                    ),
                ]
                break

    # Pass 3: GMSA chains (e.g. user -> svc_monitor -> DA)
    for u, edge_list in edges.items():
        if u in da_direct:
            continue
        for target, technique, desc in edge_list:
            if target in da_direct:
                da_direct[u] = [(u, target, technique, desc)] + da_direct[target]
                break

    # Pass 4: longer chains (user -> intermediate -> intermediate_with_path)
    for u, edge_list in edges.items():
        if u in da_direct:
            continue
        for target, technique, desc in edge_list:
            if target in da_direct:
                da_direct[u] = [(u, target, technique, desc)] + da_direct[target]
                break

    # Build output for cracked accounts only
    attack_paths = []
    for user in sorted(cracked_users):
        if user in da_direct:
            steps = da_direct[user]
            attack_paths.append(
                {
                    "start_account": user,
                    "path_steps": [
                        {
                            "from": s[0],
                            "to": s[1],
                            "technique": s[2],
                            "description": s[3],
                        }
                        for s in steps
                    ],
                    "total_steps": len(steps),
                }
            )

    return attack_paths


def find_most_dangerous(
    attack_paths: list[dict], violations: dict[str, list[str]], creds: dict[str, str]
) -> str | None:
    """Account with shortest DA path AND at least one policy violation.
    Tiebreaker: shortest password length."""
    all_violators = set()
    for v_list in violations.values():
        all_violators.update(v_list)

    candidates = []
    for path in attack_paths:
        user = path["start_account"]
        steps = path["total_steps"]
        if user in all_violators:
            pwd_len = len(creds.get(user, ""))
            candidates.append((steps, pwd_len, user))

    if not candidates:
        candidates = [
            (p["total_steps"], len(creds.get(p["start_account"], "")), p["start_account"])
            for p in attack_paths
        ]

    candidates.sort()
    return candidates[0][2] if candidates else None


def identify_misconfigurations(ad_data: dict) -> list[str]:
    misconfigs = []
    for acl in ad_data.get("acls", []):
        notes = acl.get("notes", "")
        if "MISCONFIGURATION" in notes.upper():
            misconfigs.append(
                f"{acl['source']} has {acl['right']} on {acl['target']}: {notes}"
            )

    for user in ad_data["users"]:
        delegation = user.get("delegation")
        if delegation and delegation.get("type") == "constrained":
            for t in delegation.get("allowed_to_delegate_to", []):
                if "dc01" in t.lower():
                    misconfigs.append(
                        f"{user['samaccountname']} has constrained delegation to "
                        f"Domain Controller ({t}), allowing impersonation of any user"
                    )

    for user in ad_data["users"]:
        if user.get("password_never_expires") and user.get("spn"):
            last_set = user.get("last_password_set", "")
            if "2023" in last_set:
                misconfigs.append(
                    f"Service account {user['samaccountname']} has a non-expiring password "
                    f"last set on {last_set} (stale)"
                )

    return misconfigs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Load user:hash mapping
    user_hash_map = {}
    if os.path.exists("/tmp/user_hash_map.txt"):
        with open("/tmp/user_hash_map.txt") as f:
            for line in f:
                parts = line.strip().split(":", 1)
                if len(parts) == 2:
                    user_hash_map[parts[0]] = parts[1]

    # Collect cracked creds from john
    creds = load_john_results()
    print(f"[*] John cracked: {len(creds)} passwords")

    # Collect from hashcat
    hc_creds = load_hashcat_results(user_hash_map)
    for user, pwd in hc_creds.items():
        if user not in creds:
            creds[user] = pwd
    print(f"[*] After hashcat: {len(creds)} total")

    # Python fallback cracker for any remaining hashes
    remaining = {u: h for u, h in user_hash_map.items() if u not in creds}
    if remaining:
        print(f"[*] Running Python fallback cracker for {len(remaining)} remaining hashes...")
        fallback = python_ntlm_crack(remaining, "/tmp/combined_wordlist.txt")
        for user, pwd in fallback.items():
            if user not in creds:
                creds[user] = pwd
        print(f"[*] After fallback: {len(creds)} total")

    # Load AD structure and password policy
    with open("/app/config/ad_structure.json") as f:
        ad_data = json.load(f)
    with open("/app/config/password_policy.json") as f:
        policy = json.load(f)

    # Policy violations
    violations, total_violators = check_policy_violations(creds, policy)
    print(f"[*] Policy violations: {total_violators} accounts")

    # Attack paths
    attack_paths = build_attack_graph(ad_data, set(creds.keys()))
    print(f"[*] Attack paths to DA: {len(attack_paths)}")

    # Most dangerous account
    most_dangerous = find_most_dangerous(attack_paths, violations, creds)
    print(f"[*] Most dangerous account: {most_dangerous}")

    # Risk summary
    shortest = min((p["total_steps"] for p in attack_paths), default=0)
    misconfigs = identify_misconfigurations(ad_data)

    findings = {
        "cracked_credentials": creds,
        "total_cracked": len(creds),
        "policy_violations": violations,
        "total_policy_violations": total_violators,
        "attack_paths": attack_paths,
        "most_dangerous_account": most_dangerous,
        "risk_summary": {
            "accounts_with_da_path": len(attack_paths),
            "shortest_path_steps": shortest,
            "critical_misconfigurations": misconfigs,
        },
    }

    os.makedirs("/app/report", exist_ok=True)
    with open("/app/report/findings.json", "w") as f:
        json.dump(findings, f, indent=2)

    print("[*] Report written to /app/report/findings.json")


if __name__ == "__main__":
    main()
