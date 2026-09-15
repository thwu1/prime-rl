Three vendor AES-256 CTR_DRBG implementations at `/app/candidates/` (`impl_A.py`, `impl_B.py`, `impl_C.py`) have been submitted for NIST CAVP validation. Each exposes a `CTR_DRBG` class with `__init__(use_df=True)`, `instantiate(entropy_input, nonce, personalization_string=b"")`, `reseed(entropy_input, additional_input=b"")`, `generate(requested_bits, additional_input=b"")`, and `key`/`v` byte attributes reflecting internal state. Each implementation has distinct conformance defects that cause different CAVP configuration subsets to fail.

Raw CAVS 14.3 test vector files are at `/app/cavs_raw/CTR_DRBG_AES256.txt`. The file contains five test groups covering the configurations `df_basic`, `df_addl`, `df_pers`, `nodf_basic`, and `df_reseed`, with intermediate Key/V state values annotated at each DRBG lifecycle point. OpenSSL 3.x and PyCryptodome are available on the system.

Produce the following files at `/app/`:

**`conformance_report.json`** — Top-level keys: `impl_A`, `impl_B`, `impl_C`, `recommendation`. Each implementation entry contains: `overall_status` (`"pass"` or `"fail"`), `configurations` dict mapping each config ID to `{"status": "pass"|"fail", "vectors_passed": N, "vectors_total": M}`, `defects` list (each with `component` and `description`), and `bcc_verifications` list (each entry containing at minimum `key_hex` and `match` fields). The `recommendation` value names the implementation closest to full conformance.

**`reference_impl.py`** — A correct AES-256 CTR_DRBG per NIST SP 800-90A Rev.1 Section 10.2. Must expose a `CTR_DRBG` class with the same interface as the vendor implementations, whose `key` and `v` byte attributes match the intermediate states in the CAVS test vectors after each operation.

**`cavs_parser.py`** — Module exposing `parse_cavs_file(filepath)` that returns a list of test group dicts with their test vectors and associated intermediate state data.

**`harness.py`** — Module exposing `evaluate_implementation(module_path, parsed_vectors)` that evaluates a candidate CTR_DRBG implementation against parsed CAVP test vectors and returns an evaluation dict.