#!/usr/bin/env python3
"""
Write YARA classification rules for ZIP structural variations and run them
against all extracted specimens to produce classification results.
"""

import subprocess
import json
import os
import glob

YARA_RULES_CONTENT = r"""
rule zip64_archive {
    meta:
        author = "forensic-pipeline"
        description = "Detects ZIP archives using Zip64 extended format records"
        severity = "informational"
    strings:
        $zip64_eocd = { 50 4B 06 06 }
        $zip64_locator = { 50 4B 06 07 }
    condition:
        $zip64_eocd and $zip64_locator
}

rule prepended_elf_archive {
    meta:
        author = "forensic-pipeline"
        description = "Detects ZIP archives with prepended ELF binary data before ZIP content"
        severity = "suspicious"
    strings:
        $elf_magic = { 7F 45 4C 46 }
        $zip_local = { 50 4B 03 04 }
    condition:
        $elf_magic at 0 and $zip_local
}

rule sjis_encoded_names {
    meta:
        author = "forensic-pipeline"
        description = "Detects ZIP archives containing Shift-JIS encoded filenames in central directory entries"
        severity = "informational"
    strings:
        $cd_header = { 50 4B 01 02 }
        $sjis_katakana_te = { 83 65 }
        $sjis_katakana_su = { 83 58 }
        $sjis_katakana_to = { 83 67 }
    condition:
        $cd_header and $sjis_katakana_te and $sjis_katakana_su and $sjis_katakana_to
}

rule multiple_eocd_signatures {
    meta:
        author = "forensic-pipeline"
        description = "Detects ZIP archives with multiple End of Central Directory signatures indicating structural ambiguity or manipulation"
        severity = "suspicious"
    strings:
        $eocd = { 50 4B 05 06 }
    condition:
        #eocd >= 2
}
"""


def main():
    # Write YARA rules file
    with open("/app/classify.yar", "w") as f:
        f.write(YARA_RULES_CONTENT)

    # Run YARA against each specimen
    specimens = sorted(glob.glob("/app/extracted/specimen_*.zip"))
    results = {}

    for specimen_path in specimens:
        filename = os.path.basename(specimen_path)
        proc = subprocess.run(
            ["yara", "/app/classify.yar", specimen_path],
            capture_output=True, text=True,
        )
        matches = []
        for line in proc.stdout.strip().split('\n'):
            line = line.strip()
            if line:
                rule_name = line.split()[0]
                matches.append(rule_name)
        results[filename] = matches

    with open("/app/yara_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("YARA classification results:")
    for filename, matches in sorted(results.items()):
        print(f"  {filename}: {matches}")


if __name__ == "__main__":
    main()
