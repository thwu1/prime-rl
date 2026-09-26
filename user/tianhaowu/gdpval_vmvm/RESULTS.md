# Nemotron 3 Super GDPval Kimi-Surrogate Result

## Result

- Coverage: **178 / 178** selected tasks, one policy rollout per task
- Mean task reward: **0.5870786516853933**
  - 99 task wins, 11 task ties, and 68 task losses
- Valid pairwise votes: **395 wins / 295 losses / 0 ties**
- Invalid judge responses: **22** of 712 calls
- Bradley-Terry Elo against the public human-expert anchor at 1000:
  **1050.7100318593189**
- Normalized score: **27.535501592965943**
- Task-clustered 95% confidence interval:
  - Elo: **1003.5728744682854-1097.8471892503524**
  - normalized score: **25.178643723414268-29.89235946251762**

This is a local Kimi K2.6 surrogate result, not an official Artificial
Analysis result. The separately recorded 2026-08-22 Artificial Analysis
snapshot is 698.06 Elo / 9.903 normalized points and uses unpublished
references, judge outcomes, sandbox details, and parser behavior.

## Protocol

- Policy: `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16`, checkpoint
  `d51eab0d1f979ebc26b546e634a04f450d99158e`
- Judge: `Kimi-K2.6`, protocol checkpoint
  `2755962d07cb42aa2d988a35bcb65cd4a9c2de82`
- Dataset: `openai/gdpval` revision
  `11e7900cdcac61bc4daf59e65feb238acda98fbf`
- Scoring: four alternating pairwise comparisons per task against the public
  human-expert deliverable, anchored at Elo 1000
- Semantic fingerprint:
  `3faea627249aea817ed09be81acd46525bf6e98b34a1da43160e9d8d5e2454fc`

## Audit

The archived audit completed twice under different Python hash seeds with
`ok: true`:

- 178 planned tasks, results, candidates, and valid attempt chains
- 180 attempt rows: 178 completions and two safe pre-candidate VMVM retries
- no missing tasks, fatal errors, model errors, model timeouts, or judge retries
- 178 immutable candidate manifests and 178 judge journals
- zero generated `.pyc` files in the archived implementation

Important SHA-256 values:

```text
5b2db560d36380ba1053f318d2c46b2999608f4636473e86d90e3210093f9864  summary.json
e15d8de100638157910c63941024607569aa0b3a60b98ce5c40b3bae9f5eb524  results.jsonl
a4b4e21b034ac365c8656e412749bf212ce82d456a9ecd9f82549508fb49e7f3  attempts.jsonl
ea0cd4fb4051931fb924c12536ef84e475bb6e22ad5851734278c433aa71c874  run_plan.json
57381e28e85387e61bccd94ffc443c25ee05646ccbd8f28ce9333328512fd33e  run_metadata.json
42de0849fa4dea43e71c711cac86bb0324e297b813fef9870679f3ad52d06019  implementation.tar.gz
```

The retained internal artifact root is:

```text
/checkpoint/ram/tianhaowu/gdpval_vmvm/nemotron_super_kimi_178-20260822-3faea627-j10913801-k10643065
```
