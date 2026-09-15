A ByteLevel BPE tokenizer configuration is at `/app/tokenizer.json`. Pre-encoded token ID sequences are at `/app/sequences.json`, and SHA-256 hashes of the correct decoded plaintext for each sequence are in `/app/expected_hashes.txt`. A C-based hash validator at `/app/validator.c` can be compiled using `make -C /app` and run as `/app/validator`.

An initial decoder attempt at `/app/buggy_decoder.py` produces correct output for some basic sequences but silently corrupts others — certain Unicode characters in the decoded output are replaced by unrelated control characters or garbage bytes. Relevant portions of the upstream tokenizer library's Rust source code are available at `/app/reference/` for analysis.

**Deliverable 1 — `/app/decode.py`**: A correct decoder that reads `/app/sequences.json`, decodes every token ID sequence to its expected plaintext, and writes `/app/decoded_output.json` as `{"results": {"<seq_id>": "<decoded_text>", ...}}`. All 18 sequences must pass the compiled C validator. Only Python standard library imports are permitted — `tokenizers` and `transformers` packages must not be used.

**Deliverable 2 — `/app/audit_report.json`**: Write `/app/audit.py` to analyze the tokenizer's added tokens for susceptibility to the same class of decode corruption exhibited by the buggy decoder. The script must produce `/app/audit_report.json` with the following structure:

```json
{
  "hazardous_tokens": [
    {
      "id": "<int: token id>",
      "content": "<token text>",
      "hazardous_chars": ["<char>", "..."],
      "normalized": "<bool: from token config>",
      "risk": "high|low"
    }
  ],
  "safe_token_ids": ["<int>", "..."],
  "summary": "<string: analysis summary>"
}
```

Risk classification must reflect whether a given token's configuration makes the corruption pattern unrecoverable versus correctable by a properly-implemented decoder.