An open-source compression library at `/app/project/` has been compromised with a supply chain backdoor that delivers a hidden binary payload through a multi-stage obfuscation pipeline embedded in the build system. Some legitimate project files also exhibit suspicious patterns (binary data, eval constructs, data transformation) but are not part of the attack.

Reverse-engineer the backdoor, extract the payload, classify all suspicious files, and then design a reusable heuristic detector that could identify this class of supply-chain build-system attack in other autotools projects.

Produce:

1. The extracted raw payload at `/app/payload.bin` and its SHA-256 hash (lowercase hex, 64 chars) at `/app/answer.txt`.

2. A forensic triage report at `/app/report.json`:
   ```json
   {
     "backdoor_entry_point": "<path relative to /app/project/>",
     "backdoor_files": ["<relative path>", ...],
     "benign_suspicious_files": ["<relative path>", ...]
   }
   ```
   - `backdoor_entry_point`: the file that initiates the backdoor's execution chain
   - `backdoor_files`: all files that are part of or consumed by the backdoor (including the entry point and any data files it references)
   - `benign_suspicious_files`: files that appear suspicious but serve legitimate purposes

3. A detection script at `/app/detect.py` that identifies supply-chain backdoor patterns in autotools-based projects. When invoked as `python3 /app/detect.py <project_dir>`, it must output JSON to stdout:
   ```json
   {"alerts": [{"file": "<path relative to project_dir>", "risk": "high|medium|low", "indicator": "<description of why this file is suspicious>"}]}
   ```
   The detector must use structural and behavioral heuristics — not hardcoded filenames — to flag build-system code injection vectors, suspicious data files consumed by build pipelines, and associated payload containers. It must classify genuinely malicious components as `"high"` risk while keeping benign-but-suspicious files at `"medium"` or `"low"`.