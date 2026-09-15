A multi-module ACVP CTR-DRBG test vector processor is located at `/app/`. It implements SP 800-90A CTR_DRBG with AES as the underlying block cipher. The codebase is organized as:

- `/app/acvp_processor.py` — main entry point; reads `/app/prompts/ctrdrbg_prompt.json`, writes `/app/responses/ctrdrbg_response.json`
- `/app/drbg/primitives.py` — AES block encryption, counter increment, XOR
- `/app/drbg/derivation.py` — Block_Cipher_df derivation function (SP 800-90A §10.3.2) and BCC
- `/app/drbg/update.py` — CTR_DRBG_Update (SP 800-90A §10.2.1.2)
- `/app/drbg/core.py` — CTR_DRBG Instantiate, Reseed, Generate (SP 800-90A §10.2.1.3–10.2.1.5)

The prompt file contains 4 test groups covering different configurations:
- AES-128 and AES-256 key sizes
- With-derivation-function mode (`derFunc: true`)
- Without-derivation-function mode (`derFunc: false`)
- Prediction resistance and explicit reseed test procedures

**Current state:** The processor has multiple algorithmic bugs distributed across different modules. Running it produces incorrect `returnedBits` for all test groups that use the derivation function, and crashes with `NotImplementedError` for the without-derivation-function test group (tgId 4), which is unimplemented.

Fix all algorithmic bugs and implement the missing without-derivation-function code path (SP 800-90A §10.2.1.3.1, §10.2.1.4.1, §10.2.1.5.1) so the processor produces correct results for all 8 test cases across all 4 test groups. The response JSON must conform to the schema documented at `/app/schema/response_schema.json`.

## Response JSON Schema

The output at `/app/responses/ctrdrbg_response.json` must be a JSON object with these properties:

| Property | Type | Required | Description |
|---|---|---|---|
| `vsId` | integer | yes | Must match the prompt's `vsId` |
| `algorithm` | string | yes | Must be `"ctrDRBG"` |
| `revision` | string | yes | Must match the prompt's `revision` |
| `testGroups` | array | yes | One entry per prompt test group |

Each `testGroups` element:

| Property | Type | Required | Description |
|---|---|---|---|
| `tgId` | integer | yes | Must match the prompt group's `tgId` |
| `tests` | array | yes | One entry per prompt test case |

Each `tests` element:

| Property | Type | Required | Description |
|---|---|---|---|
| `tcId` | integer | yes | Must match the prompt test case's `tcId` |
| `returnedBits` | string | yes | Uppercase hex-encoded output from the final DRBG generate call |

No additional properties are permitted in `testGroups` or `tests` objects.