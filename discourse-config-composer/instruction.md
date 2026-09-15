Discourse deploys via a bash launcher script (`/app/reference/launcher`) that uses inline Ruby invoked inside Docker containers to parse YAML configs, resolve and merge referenced template files, and produce Docker CLI arguments. This architecture makes offline configuration analysis impossible.

Complete `/app/compose.py` — a standalone Python reimplementation of the launcher's template composition logic. A skeleton with the expected JSON output schema, bundled plugin list, and configuration issue codes is already in place.

Usage: `python3 /app/compose.py <config_file> <config_name> [--base-dir DIR]`

The launcher script is the sole specification. Study the embedded Ruby code blocks and the bash functions that invoke them — each configuration section may follow different processing rules for merging, defaulting, substitution, and output formatting. Your implementation must match the launcher's exact semantics across all section types.

The tool must also detect the configuration issues whose codes are listed in the skeleton, by analyzing the merged result against common Discourse self-hosting pitfalls. Sample configs at `/app/deployment/` contain intentional misconfigurations. Detection must be precise: correctly configured deployments must produce zero false positives.