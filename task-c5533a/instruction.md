A cryptographic module vendor has submitted ACVP (Automated Cryptographic Validation Protocol) validation responses as part of FIPS 140-3 certification. The ACVP test vector prompts are in `/app/vectors/` and the vendor's submitted responses are in `/app/vendor_responses/` (filenames correspond between directories).

The Cryptographic Module Validation Program has flagged potential inaccuracies in the vendor's results. The test vectors include both Algorithm Function Tests (AFT) and Monte Carlo Tests (MCT), spanning multiple algorithm families with distinct processing requirements. Perform an independent compliance audit:

1. Independently compute the correct ACVP response for every test vector in `/app/vectors/` and write them to `/app/results/` (filenames must match those in `/app/vectors/`). Each output file must be a JSON object preserving `vsId`, `algorithm`, and `revision` from the corresponding input, with a `testGroups` array containing computed results for every test case. All hex string values in the output must be uppercase. For MCT test cases, the output must include a `resultsArray` containing results for all 100 outer iterations.

2. Produce a compliance audit report at `/app/audit_report.json` documenting every discrepancy between the vendor's submitted responses and your independently computed correct results, in this format:

```json
{
  "total_test_cases": 0,
  "total_discrepancies": 0,
  "files": {
    "<filename>": {
      "discrepancies": [
        {
          "tgId": 0,
          "tcId": 0,
          "fields": {
            "<field_name>": {
              "vendor": "<vendor_value_or_absent>",
              "correct": "<correct_value_or_absent>"
            }
          }
        }
      ]
    }
  }
}
```

The test vector files conform to the NIST ACVP JSON specification. You must determine from the data itself what cryptographic operations each test vector requires, including the correct iteration algorithm for Monte Carlo Tests, and how to compute them correctly.