You are given an ACVP (Automated Cryptographic Validation Protocol) prompt file at `/data/prompt.json`
containing 18 test groups for AES-CBC validation: 12 Algorithm Functional Test (AFT) groups and 6
Monte Carlo Test (MCT) groups. A specification document at `/data/spec.md` describes the MCT algorithm,
key shuffle routine, salted key evolution step, and response format.

Implement a processor that reads `/data/prompt.json`, computes all cryptographic results, and writes a
valid ACVP response to `/app/response.json`.

The prompt covers AES-CBC with key sizes 128, 192, and 256 bits in both encrypt and decrypt directions.
AFT groups require straightforward AES-CBC operations. MCT groups require implementing the Monte Carlo
test procedure: 100 outer rounds of 1000 inner iterations each, with key evolution via the AES Key
Shuffle routine followed by a salted key evolution step. The salted key evolution XORs the shuffled key
with a truncated SHA-256 hash derived from the prompt's `domainSeparator` field and the round number,
as detailed in the spec document. The decrypt MCT algorithm must be derived from the encrypt MCT
pseudocode by swapping all PT/CT references and using the decrypt operation.

The response JSON must contain the same top-level fields (`vsId`, `algorithm`, `revision`, `isSample`)
as the prompt, plus a `testGroups` array. Each test group in the response must contain `tgId` and a
`tests` array. AFT test results contain `tcId` and the computed `ct` (for encrypt) or `pt` (for
decrypt) as uppercase hex strings. MCT test results contain `tcId` and a `resultsArray` of 100 entries,
each with `key`, `iv`, `pt`, and `ct` as uppercase hex strings.