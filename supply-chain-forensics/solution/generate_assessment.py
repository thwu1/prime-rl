#!/usr/bin/env python3
"""
Threat Intelligence Assessment Generator
Produces comparative evaluation of the four malware families.
"""

import json


def generate_assessment():
    assessment = {
        "sophistication_ranking": [
            {
                "package": "rapid-json-parse",
                "rank": 1,
                "score": 9.2,
                "justification": (
                    "Most sophisticated attack: employs a two-layer obfuscation scheme "
                    "(reversed base64 + XOR cipher with custom key scheduling using "
                    "quadratic index formula 5*i*i%10), implements comprehensive "
                    "anti-forensics (self-deletion of telemetry.js, evidence replacement "
                    "via package.bak rename, platform-specific dropper naming mimicking "
                    "Apple system daemons), and delivers a full RAT dropper with "
                    "platform-aware payloads for macOS/Linux/Windows. The operational "
                    "security is the highest of the four: dedicated C2 infrastructure "
                    "(darkoperator.net), non-standard port (8443), and multi-stage "
                    "payload delivery."
                )
            },
            {
                "package": "eth-wallet-utils",
                "rank": 2,
                "score": 7.5,
                "justification": (
                    "Second most sophisticated: uses a custom array rotation cipher "
                    "with IIFE checksum verification (target sum 0x2cc/716) to hide "
                    "all string literals, making static analysis difficult. The hex "
                    "index resolver function (_0x5c2d) adds another layer of indirection. "
                    "However, anti-forensics are weaker than rapid-json-parse (no "
                    "self-deletion, silent catch only) and the exfiltration channel "
                    "(Telegram bot API) is less operationally secure than a dedicated C2. "
                    "The source map version mismatch (5.8.0 vs 5.8.1) shows attention "
                    "to detail in the supply chain compromise vector."
                )
            },
            {
                "package": "go-financial-calc",
                "rank": 3,
                "score": 5.8,
                "justification": (
                    "Moderate sophistication: the DNS TXT covert channel is a clever "
                    "C2 mechanism that evades most network monitoring (DNS is rarely "
                    "inspected for command payloads), and hiding the init() goroutine "
                    "within 500+ lines of legitimate decimal math library code is "
                    "effective camouflage. However, the code uses minimal obfuscation — "
                    "the malicious imports (net, os/exec) and LookupTXT call are "
                    "plaintext and discoverable by simple grep. The use of free "
                    "dynamic DNS (freeddns.org) indicates lower operational resources "
                    "compared to rapid-json-parse's dedicated infrastructure."
                )
            },
            {
                "package": "pydata-tools",
                "rank": 4,
                "score": 3.4,
                "justification": (
                    "Least sophisticated: uses well-known base64+zlib encoding that "
                    "is a standard technique documented in numerous malware analysis "
                    "guides. The exec(zlib.decompress(base64.b64decode())) pattern is "
                    "instantly recognizable to any security analyst. The CustomInstall "
                    "cmdclass trigger is common in PyPI malware. Anti-forensics are "
                    "minimal (exception silencing only). The reverse shell connects "
                    "to a hardcoded IP on the default Metasploit port (4444), and the "
                    "env var exfiltration uses an underground paste service with no "
                    "encryption. This attack prioritizes speed of deployment over "
                    "stealth or persistence."
                )
            }
        ],
        "mitre_attack_mapping": {
            "rapid-json-parse": {
                "techniques": [
                    {
                        "id": "T1195.001",
                        "name": "Supply Chain Compromise: Compromise Software Dependencies",
                        "evidence": "Malicious postinstall hook in package.json triggers execution when the npm package is installed as a dependency"
                    },
                    {
                        "id": "T1027",
                        "name": "Obfuscated Files or Information",
                        "evidence": "Two-layer obfuscation: reversed base64 encoding followed by XOR cipher with key 'VaLiD_3098' and constant 0x14D, using quadratic index formula 5*i*i%10"
                    },
                    {
                        "id": "T1059.007",
                        "name": "Command and Scripting Interpreter: JavaScript",
                        "evidence": "Deobfuscated payload uses child_process.exec() to execute system commands and download secondary payloads"
                    },
                    {
                        "id": "T1071.001",
                        "name": "Application Layer Protocol: Web Protocols",
                        "evidence": "RAT dropper communicates with C2 at svc-update.darkoperator.net:8443 over HTTP to download platform-specific payloads"
                    },
                    {
                        "id": "T1070.004",
                        "name": "Indicator Removal: File Deletion",
                        "evidence": "Self-deletes telemetry.js via fs.unlink(__filename) and replaces package.json with clean package.bak to remove evidence of postinstall hook"
                    }
                ]
            },
            "go-financial-calc": {
                "techniques": [
                    {
                        "id": "T1195.001",
                        "name": "Supply Chain Compromise: Compromise Software Dependencies",
                        "evidence": "Typosquat of shopspring/decimal published as nicksprint/go-financial-calc; executes malicious code when imported as Go dependency"
                    },
                    {
                        "id": "T1071.004",
                        "name": "Application Layer Protocol: DNS",
                        "evidence": "Uses net.LookupTXT to poll DNS TXT records at cdn-telemetry.freeddns.org for command payloads, blending C2 traffic with legitimate DNS"
                    },
                    {
                        "id": "T1059",
                        "name": "Command and Scripting Interpreter",
                        "evidence": "Executes commands received from DNS TXT records via exec.Command with CombinedOutput(), providing arbitrary command execution"
                    },
                    {
                        "id": "T1036.005",
                        "name": "Masquerading: Match Legitimate Name or Location",
                        "evidence": "Module path and package structure mimic the legitimate shopspring/decimal library to appear authentic to developers"
                    }
                ]
            },
            "eth-wallet-utils": {
                "techniques": [
                    {
                        "id": "T1195.001",
                        "name": "Supply Chain Compromise: Compromise Software Dependencies",
                        "evidence": "Malicious npm package masquerades as Ethereum wallet utility; compromise occurs when imported as a dependency"
                    },
                    {
                        "id": "T1005",
                        "name": "Data from Local System",
                        "evidence": "Intercepts private keys passed to Wallet constructor _initFromKey() method, collecting cryptographic credentials from memory"
                    },
                    {
                        "id": "T1567",
                        "name": "Exfiltration Over Web Service",
                        "evidence": "Exfiltrates stolen private keys to Telegram bot API (api.telegram.org/bot6847291053:...) using sendMessage endpoint"
                    },
                    {
                        "id": "T1027",
                        "name": "Obfuscated Files or Information",
                        "evidence": "Array rotation cipher with IIFE checksum verification (target 0x2cc) and hex index resolver (_0x5c2d) obfuscates all string literals"
                    }
                ]
            },
            "pydata-tools": {
                "techniques": [
                    {
                        "id": "T1195.001",
                        "name": "Supply Chain Compromise: Compromise Software Dependencies",
                        "evidence": "Malicious setup.py with CustomInstall cmdclass executes payload during pip install of the pydata-tools package"
                    },
                    {
                        "id": "T1059.006",
                        "name": "Command and Scripting Interpreter: Python",
                        "evidence": "Compressed payload is executed via exec() during package installation, spawning a reverse shell and credential harvester"
                    },
                    {
                        "id": "T1041",
                        "name": "Exfiltration Over C2 Channel",
                        "evidence": "Harvested environment variables (AWS_SECRET_ACCESS_KEY, GITHUB_TOKEN, etc.) exfiltrated to paste.darknet.services"
                    },
                    {
                        "id": "T1059.004",
                        "name": "Command and Scripting Interpreter: Unix Shell",
                        "evidence": "Reverse shell connects to 185.193.127.42:4444 using /bin/sh, providing interactive command-line access to the compromised host"
                    }
                ]
            }
        },
        "attribution_analysis": {
            "num_clusters": 3,
            "clusters": [
                {
                    "actor_id": "TA-DARKOPS",
                    "packages": ["rapid-json-parse"],
                    "shared_ttps": [
                        "Dedicated C2 infrastructure (darkoperator.net domain, dedicated IP 185.220.101.34)",
                        "Multi-layer custom obfuscation (XOR cipher with bespoke key scheduling)",
                        "Comprehensive anti-forensics (self-deletion, evidence replacement)",
                        "Platform-aware payload delivery (macOS/Linux/Windows branching)",
                        "RAT-class malware indicating persistent access objectives"
                    ],
                    "confidence": "medium"
                },
                {
                    "actor_id": "TA-CRYPTOTHIEF",
                    "packages": ["eth-wallet-utils"],
                    "shared_ttps": [
                        "Targeted financial theft (cryptocurrency private keys)",
                        "Telegram-based exfiltration (bot API for real-time notification)",
                        "JavaScript obfuscation focused on string concealment (array rotation cipher)",
                        "Narrow targeting scope (only crypto wallet users)",
                        "Source map manipulation for supply chain credibility"
                    ],
                    "confidence": "medium"
                },
                {
                    "actor_id": "TA-MASSCOMPROMISE",
                    "packages": ["go-financial-calc", "pydata-tools"],
                    "shared_ttps": [
                        "Free or underground infrastructure (freeddns.org, paste.darknet.services)",
                        "Lower operational security (plaintext imports, default ports)",
                        "Broad credential harvesting (env vars, arbitrary command execution)",
                        "Commodity techniques adapted across ecosystems (Go typosquat, PyPI install hook)",
                        "Focus on initial access and credential theft over persistent implants"
                    ],
                    "confidence": "low"
                }
            ],
            "rationale": (
                "Three distinct actor clusters emerge from TTP and infrastructure analysis. "
                "TA-DARKOPS (rapid-json-parse) stands alone due to significantly higher "
                "operational security: dedicated domain, custom multi-layer obfuscation, "
                "comprehensive anti-forensics, and a RAT-class implant — consistent with "
                "a resourced threat actor pursuing persistent access. TA-CRYPTOTHIEF "
                "(eth-wallet-utils) operates independently with a narrowly targeted financial "
                "theft objective and Telegram-based exfiltration, a pattern common in "
                "cryptocurrency-focused criminal groups. TA-MASSCOMPROMISE groups go-financial-calc "
                "and pydata-tools based on shared low-cost infrastructure patterns (free DNS, "
                "underground paste services), lower obfuscation sophistication, and broad "
                "credential-harvesting objectives. The clustering confidence for TA-MASSCOMPROMISE "
                "is low because the two packages target different ecosystems (Go vs Python) and "
                "could plausibly be separate actors with similar resource constraints and objectives."
            )
        },
        "rule_resilience_evaluation": [
            {
                "rule_name": "XOR_Base64_RAT_Dropper",
                "target_package": "rapid-json-parse",
                "brittle_indicators": [
                    "Variable names _t1, _t2, _cfg, _m, _s — trivially renamed by any JS minifier or obfuscator",
                    "Function name patterns like '_t1 = function' — specific to this variant's code style"
                ],
                "robust_indicators": [
                    "fs.unlink(__filename) self-deletion pattern — inherent to the anti-forensics behavior",
                    "Co-occurrence of XOR decoding function + encoded string array + self-deletion — structural pattern hard to eliminate without rewriting the attack"
                ],
                "evasion_difficulty": "medium",
                "recommended_improvements": [
                    "Add behavioral YARA conditions matching the reversed-base64 decode pattern (string reversal followed by base64 decode) rather than specific variable names",
                    "Use regex patterns for the XOR key scheduling formula rather than exact variable references",
                    "Add entropy-based detection for the encoded string array (high-entropy string literals in array assignment)"
                ]
            },
            {
                "rule_name": "DNS_TXT_Command_Injection",
                "target_package": "go-financial-calc",
                "brittle_indicators": [
                    "Exact import path strings like '\"net\"' and '\"os/exec\"' — these are Go standard library imports also used by legitimate programs"
                ],
                "robust_indicators": [
                    "Co-occurrence of net.LookupTXT + exec.Command + CombinedOutput — this specific three-function chain is the core attack logic and cannot be removed without destroying the backdoor functionality",
                    "DNS lookup to arbitrary domain followed by command execution — this behavioral pattern is inherent to the DNS C2 mechanism"
                ],
                "evasion_difficulty": "medium",
                "recommended_improvements": [
                    "Add detection for the init() goroutine pattern (go func() with ticker/sleep loop calling LookupTXT)",
                    "Combine with module path analysis — flag Go modules with net+exec imports that also have typosquat-indicative module paths",
                    "Add heuristic for the combination of DNS lookup in init() with time-based polling (time.Tick or time.Sleep in a loop)"
                ]
            },
            {
                "rule_name": "Array_Rotation_Telegram_Exfil",
                "target_package": "eth-wallet-utils",
                "brittle_indicators": [
                    "Specific function names _0x4a7c and _0x5c2d — these are randomly generated obfuscator output and will differ in every variant",
                    "Exact Telegram bot token and chat ID — different for each campaign"
                ],
                "robust_indicators": [
                    "api.telegram.org combined with /bot prefix and sendMessage — this is the Telegram bot API exfiltration channel and any Telegram-based exfil must use these strings",
                    "Array rotation with checksum verification IIFE pattern — structural pattern of the obfuscation technique"
                ],
                "evasion_difficulty": "low",
                "recommended_improvements": [
                    "Replace _0x4a7c/_0x5c2d with regex patterns matching the _0x[hex]{4} naming convention common to JavaScript obfuscators",
                    "Add detection for the IIFE checksum pattern (while loop with character code sum comparison)",
                    "Detect fetch/XMLHttpRequest to api.telegram.org in any npm package as inherently suspicious regardless of obfuscation"
                ]
            },
            {
                "rule_name": "Compressed_Payload_Setup_Py",
                "target_package": "pydata-tools",
                "brittle_indicators": [
                    "Exact string 'exec(' — extremely common in legitimate Python code and only works here due to co-occurrence with zlib/base64"
                ],
                "robust_indicators": [
                    "Co-occurrence of zlib.decompress + base64.b64decode + exec() in a single file — this three-function chain is the core deobfuscation-and-execute pattern",
                    "The pattern exec(zlib.decompress(base64.b64decode(...))) is structurally necessary for compressed payload execution"
                ],
                "evasion_difficulty": "high",
                "recommended_improvements": [
                    "Add detection for CustomInstall or similar cmdclass overrides combined with exec/eval in setup.py files specifically",
                    "Use YARA math module to detect high-entropy base64 blobs (long strings of [A-Za-z0-9+/=]) co-located with decompression imports",
                    "Add detection for the marshal/compile/exec alternative encoding chain used by more sophisticated PyPI malware"
                ]
            }
        ],
        "remediation_priority": {
            "ordering": [
                "rapid-json-parse",
                "pydata-tools",
                "go-financial-calc",
                "eth-wallet-utils"
            ],
            "justification": (
                "Priority reflects blast radius and persistence capability. rapid-json-parse "
                "(RAT dropper) is highest priority: it provides full remote access to every "
                "infected system with platform-specific persistence, and its anti-forensics "
                "make detection harder over time. pydata-tools (reverse shell + env var theft) "
                "is second: it provides interactive system access AND immediately exfiltrates "
                "cloud credentials (AWS, GitHub, NPM tokens), enabling lateral movement to "
                "CI/CD and cloud infrastructure. go-financial-calc (DNS backdoor) is third: "
                "it provides persistent command execution via a covert DNS channel, but requires "
                "the attacker to actively push commands and lacks automatic credential harvesting. "
                "eth-wallet-utils (private key theft) is lowest priority: while the financial "
                "impact per-victim can be severe, the blast radius is limited to cryptocurrency "
                "users who actively create wallets with the library, and the attack provides no "
                "system-level persistence or lateral movement capability."
            )
        }
    }

    with open("/app/threat_assessment.json", "w") as f:
        json.dump(assessment, f, indent=2)

    print("Threat assessment written to /app/threat_assessment.json")


if __name__ == "__main__":
    generate_assessment()
