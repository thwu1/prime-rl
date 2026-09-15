#!/usr/bin/env python3
"""
Supply Chain Malware Forensic Analysis - Solution
Analyzes 4 suspicious packages, deobfuscates payloads, extracts IOCs.
"""

import json
import base64
import zlib
import os
import re


def analyze_rapid_json_parse():
    """
    Analyze rapid-json-parse: XOR + reversed base64 obfuscation.
    Key: "VaLiD_3098", constant: 0x14D (333), index formula: 5*i*i % 10
    """
    with open("/app/suspects/rapid-json-parse/lib/telemetry.js", "r") as f:
        content = f.read()

    encoded_strings = {}
    for match in re.finditer(r'_s\[(\d+)\]\s*=\s*"([^"]+)"', content):
        idx = int(match.group(1))
        encoded_strings[idx] = match.group(2)

    key_match = re.search(r'const _cfg\s*=\s*"([^"]+)"', content)
    const_match = re.search(r'const _m\s*=\s*(0x[0-9a-fA-F]+|\d+)', content)
    key = key_match.group(1) if key_match else "VaLiD_3098"
    constant = int(const_match.group(1), 0) if const_match else 333

    def js_key_to_digits(key_str):
        return [int(c) if c.isdigit() else 0 for c in key_str]

    def decode_xor(xored_str, key_str, const_val, mult=5, klen=10):
        digits = js_key_to_digits(key_str)
        result = []
        for i, ch in enumerate(xored_str):
            idx = (mult * i * i) % klen
            d = digits[idx]
            xor_val = ord(ch) ^ d ^ const_val
            result.append(chr(xor_val))
        return "".join(result)

    def decode_full(encoded, key_str, const_val):
        step1 = encoded.replace("_", "=")
        step2 = step1[::-1]
        step3_bytes = base64.b64decode(step2)
        step3_str = step3_bytes.decode("utf-8")
        return decode_xor(step3_str, key_str, const_val)

    decoded = {}
    for idx, enc in sorted(encoded_strings.items()):
        decoded[idx] = decode_full(enc, key, constant)

    deobfuscated_strings = list(decoded.values())

    return {
        "name": "rapid-json-parse",
        "version": "2.4.1",
        "ecosystem": "npm",
        "attack_type": "RAT dropper / remote access trojan",
        "obfuscation_technique": "Two-layer encoding: reversed base64 (string reversed, underscores replaced with = padding, base64-decoded) then XOR cipher (each character XORed with digit from key 'VaLiD_3098' at index 5*i*i%10, XORed with constant 0x14D/333)",
        "execution_trigger": "npm postinstall lifecycle hook in package.json executes lib/telemetry.js",
        "deobfuscated_strings": deobfuscated_strings,
        "iocs": {
            "domains": ["svc-update.darkoperator.net"],
            "ips": ["185.220.101.34"],
            "urls": ["http://svc-update.darkoperator.net:8443/"],
            "file_paths": [
                "/Library/Caches/com.apple.cfprefsd.agent",
                "/tmp/.X11-unix/.cache",
                "/tmp/ld.py"
            ],
            "credentials": [],
            "ports": [8443],
            "targeted_env_vars": []
        },
        "anti_forensics": [
            "Self-deletion: deletes telemetry.js via fs.unlink(__filename)",
            "Evidence removal: deletes package.json containing postinstall hook",
            "Evidence replacement: renames package.bak to package.json to restore clean manifest",
            "macOS dropper mimics Apple system daemon naming (com.apple.cfprefsd.agent)",
            "Platform-specific payload delivery (darwin/win32/linux branches)"
        ],
        "severity": "critical"
    }


def analyze_go_financial_calc():
    """
    Analyze go-financial-calc: DNS TXT command injection in init() goroutine.
    """
    with open("/app/suspects/go-financial-calc/decimal.go", "r") as f:
        content = f.read()

    init_match = re.search(
        r'func init\(\)\s*\{.*?net\.LookupTXT\("([^"]+)"\).*?\}',
        content, re.DOTALL
    )
    c2_domain = init_match.group(1) if init_match else "cdn-telemetry.freeddns.org"

    with open("/app/suspects/go-financial-calc/go.mod", "r") as f:
        gomod = f.read()
    module_match = re.search(r'module\s+(\S+)', gomod)
    module_path = module_match.group(1) if module_match else ""

    return {
        "name": "go-financial-calc",
        "version": "v1.3.3 (inferred from module)",
        "ecosystem": "go",
        "attack_type": "DNS TXT record command injection / backdoor",
        "obfuscation_technique": "Minimal obfuscation - malicious init() goroutine hidden within 500+ lines of legitimate decimal math library code. Suspicious imports (net, os/exec, time) buried among legitimate imports.",
        "execution_trigger": "Go init() function - executes automatically when package is imported, before main(). Goroutine runs in background polling DNS TXT records every 5 minutes.",
        "deobfuscated_strings": [
            c2_domain,
            "net.LookupTXT",
            "exec.Command",
            "5 * time.Minute",
            module_path
        ],
        "iocs": {
            "domains": ["cdn-telemetry.freeddns.org", "freeddns.org"],
            "ips": [],
            "urls": [],
            "file_paths": [],
            "credentials": [],
            "ports": [],
            "targeted_env_vars": []
        },
        "anti_forensics": [
            "Malicious code concealed within legitimate shopspring/decimal library clone",
            "Module path 'nicksprint' is a typosquat of legitimate 'shopspring'",
            "DNS TXT lookups blend in with normal DNS traffic, evading network monitoring",
            "No filesystem artifacts - persistence via dependency itself",
            "Silent error handling - DNS lookup failures silently retry",
            "Dead code: func main(){} appended but never called (package, not executable)"
        ],
        "severity": "critical"
    }


def analyze_eth_wallet_utils():
    """
    Analyze eth-wallet-utils: Array rotation cipher with Telegram exfiltration.
    """
    with open("/app/suspects/eth-wallet-utils/dist/index.cjs", "r") as f:
        content = f.read()

    array_match = re.search(r'return\s*\[(.*?)\]', content, re.DOTALL)
    if array_match:
        raw = array_match.group(1)
        strings = re.findall(r'"([^"]*)"', raw)
    else:
        strings = []

    checksum_match = re.search(r'!==\s*(0x[0-9a-fA-F]+|\d+)', content)
    target = int(checksum_match.group(1), 0) if checksum_match else 716

    arr = list(strings)
    for _ in range(len(arr)):
        s = sum(ord(c) for c in arr[0])
        if s == target:
            break
        arr.append(arr.pop(0))

    telegram_url = ""
    bot_token = ""
    chat_id = ""
    for s in arr:
        if "telegram.org" in s:
            telegram_url = s
            token_match = re.search(r'bot(\d+:[A-Za-z0-9_-]+)', s)
            if token_match:
                bot_token = token_match.group(1)
        if re.match(r'^-?\d{10,}$', s):
            chat_id = s

    return {
        "name": "eth-wallet-utils",
        "version": "5.8.1",
        "ecosystem": "npm",
        "attack_type": "Private key theft / credential exfiltration via Telegram",
        "obfuscation_technique": "Array rotation cipher: a 16-element string array is returned by _0x4a7c(), an IIFE rotates it until the character code sum of the first element equals 0x2cc (716 = checksum for 'chat_id'). A resolver function _0x5c2d maps hex indices (0x0-0xf) to rotated array positions, hiding string references behind opaque hex lookups.",
        "execution_trigger": "Wallet constructor _initFromKey() method - fires when a private key is passed to create a wallet. The stolen key is sent to Telegram before the wallet object is returned.",
        "deobfuscated_strings": arr,
        "iocs": {
            "domains": ["api.telegram.org"],
            "ips": [],
            "urls": [telegram_url],
            "file_paths": [],
            "credentials": [
                f"Telegram bot token: {bot_token}",
                f"Telegram chat ID: {chat_id}"
            ],
            "ports": [],
            "targeted_env_vars": []
        },
        "anti_forensics": [
            "Obfuscated string references via hex indices (_0x5c2d(0xb), etc.)",
            "Source map mismatch: compiled CJS has injected line not in TypeScript source (src/index.ts version 5.8.0 vs package.json 5.8.1)",
            "Legitimate library clone - clones @ethersproject/wallet structure to appear authentic",
            "Silent catch: exfiltration failures silently swallowed (.catch(() => {}))"
        ],
        "severity": "critical"
    }


def analyze_pydata_tools():
    """
    Analyze pydata-tools: base64+zlib compressed reverse shell in setup.py.
    """
    with open("/app/suspects/pydata-tools/setup.py", "r") as f:
        content = f.read()

    payload_match = re.search(r'_d\s*=\s*"([A-Za-z0-9+/=]+)"', content)
    encoded_payload = payload_match.group(1) if payload_match else ""

    if encoded_payload:
        decoded = zlib.decompress(base64.b64decode(encoded_payload)).decode()
    else:
        decoded = ""

    ips = re.findall(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', decoded)
    ports = re.findall(r',\s*(\d{4,5})\)', decoded)
    urls = re.findall(r'https?://[^\s"\']+', decoded)
    env_vars = re.findall(r'"([A-Z_]+)"', decoded)

    return {
        "name": "pydata-tools",
        "version": "1.3.2",
        "ecosystem": "pypi",
        "attack_type": "Reverse shell and environment variable exfiltration",
        "obfuscation_technique": "Base64 encoding + zlib compression: malicious Python payload is zlib-compressed, then base64-encoded, stored as string literal _d in setup.py, and executed via exec(zlib.decompress(base64.b64decode(_d))) during package installation",
        "execution_trigger": "setup.py CustomInstall command class (cmdclass={'install': CustomInstall}) - _post_install() method executes after standard install, decodes and runs the payload",
        "deobfuscated_strings": [decoded.strip()],
        "iocs": {
            "domains": ["paste.darknet.services"],
            "ips": ips,
            "urls": urls,
            "file_paths": ["/bin/sh"],
            "credentials": [],
            "ports": [int(p) for p in ports],
            "targeted_env_vars": env_vars
        },
        "anti_forensics": [
            "Payload hidden in compressed+encoded blob - not visible via static text search",
            "CustomInstall class name suggests legitimate post-install behavior",
            "Exception handling silences all errors during exploitation",
            "Payload only executes on Linux/macOS, skipping Windows (avoids sandbox detection)"
        ],
        "severity": "critical"
    }


def main():
    report = {
        "packages": [
            analyze_rapid_json_parse(),
            analyze_go_financial_calc(),
            analyze_eth_wallet_utils(),
            analyze_pydata_tools()
        ]
    }

    with open("/app/forensic_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Forensic report written to /app/forensic_report.json")
    print(f"Analyzed {len(report['packages'])} packages")
    for pkg in report["packages"]:
        print(f"  - {pkg['name']}: {pkg['attack_type']} [{pkg['severity']}]")


if __name__ == "__main__":
    main()
