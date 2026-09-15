"""
CAVS 14.3 CTR_DRBG test vector parser.

Parses the proprietary NIST bracketed format with intermediate Key/V state
annotations from ** INSTANTIATE / ** GENERATE / ** RESEED blocks.

"""

import re


def parse_cavs_file(filepath):
    """Parse a CAVS 14.3 CTR_DRBG test vector file.

    Returns a list of test group dicts, each containing:
    - 'config': dict of configuration parameters from [bracketed] headers
    - 'vectors': list of test vector dicts, each with input fields and
      'states' dict mapping phase names to {'Key': hex, 'V': hex}
    """
    with open(filepath) as f:
        content = f.read()

    groups = []
    sections = re.split(r"(?=\[AES-256 )", content)

    for section in sections:
        section = section.strip()
        if not section.startswith("[AES-256"):
            continue

        lines = section.split("\n")
        config = {}
        i = 0

        # Parse bracketed configuration headers
        while i < len(lines):
            line = lines[i].strip()
            m = re.match(r"\[(.+?)\]", line)
            if m:
                kv = m.group(1)
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    config[k.strip()] = v.strip()
                else:
                    config["algorithm"] = kv
                i += 1
            elif line.startswith("COUNT"):
                break
            else:
                i += 1

        # Parse test vectors with intermediate states
        vectors = []
        current = None
        current_phase = None
        ai_count = 0

        while i < len(lines):
            raw_line = lines[i]
            line = raw_line.strip()

            if not line or line.startswith("#"):
                i += 1
                continue

            if line.startswith("COUNT"):
                if current is not None:
                    vectors.append(current)
                current = {
                    "count": int(line.split("=")[1].strip()),
                    "states": {},
                }
                current_phase = None
                ai_count = 0

            elif line.startswith("**"):
                phase_text = line.upper()
                if "INSTANTIATE" in phase_text:
                    current_phase = "instantiate"
                elif "FIRST" in phase_text:
                    current_phase = "generate1"
                elif "SECOND" in phase_text:
                    current_phase = "generate2"
                elif "RESEED" in phase_text:
                    current_phase = "reseed"
                else:
                    current_phase = None

            elif "=" in line and current is not None:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()

                if k in ("Key", "V") and current_phase:
                    if current_phase not in current["states"]:
                        current["states"][current_phase] = {}
                    current["states"][current_phase][k] = v
                elif k == "AdditionalInput":
                    ai_count += 1
                    current[f"AdditionalInput{ai_count}"] = v
                else:
                    current[k] = v

            i += 1

        if current is not None:
            vectors.append(current)

        groups.append({"config": config, "vectors": vectors})

    return groups
