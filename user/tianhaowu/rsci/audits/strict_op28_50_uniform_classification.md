# Strict OP28 50-trajectory uniform manual audit

This audit separates literal difference from semantic error in the OP28
strict-filter training shard. The deterministic selection is uniform over the
50,000 accepted trajectories: it takes the 50 smallest SHA-256 ranks under
seed `strict-op28-50-uniform-trajectories-v1`, without conditioning on any
error indicator. All 50 selected rows have distinct prompt IDs.

The full question, model response, canonical generator response, and automated
diagnostics are preserved in
`/checkpoint/ram-h100-2/tianhaowu/rsci/audits/strict-op28-50-uniform-trajectories-v1/dossier.md`.

## Rates

Literal text difference is not a useful correctness metric here. Exactly
0/50,000 model responses match the canonical response, even after whitespace
normalization, because correct solutions may rename temporary variables,
reorder independent definitions, and sum terms in a different order.

The released strict verifier guarantees that all required semantic node names,
final values, and dependency sets match. It does not validate every written
equality, mutable one-letter symbol use, or extra predicted graph node. Full
shard diagnostics therefore provide bounds rather than an exact semantic-error
rate:

| Full-shard indicator | Rows | Rate | Interpretation |
| --- | ---: | ---: | --- |
| Explicit numeric contradiction | 383 | 0.766% | Conservative defect lower bound: a written numeric equality is false. |
| Extra parsed graph node | 2,242 | 4.484% | Structural difference; may be unsupported, wrong, or a valid distractor. |
| Stateful symbol-substitution contradiction | 7,779 | 15.558% | Broad alias/stale-symbol indicator; some sequential shadowing can be valid. |
| Union of the three indicators | 9,595 | 19.190% | Screening rate, not a proven defect rate. |

Manual review finds 7 genuine semantic defects in the uniform 50-row sample:
14.0%, with a 95% Wilson interval of 6.95–26.19%. The remaining 43 are
semantically valid alternatives to the canonical derivation.

| Manual class | Count | Share |
| --- | ---: | ---: |
| Canonical-equivalent alternative derivation | 43 | 86% |
| Stale-symbol or aliasing contradiction | 6 | 12% |
| Aliasing plus unsupported/false extra subgraph | 1 | 2% |

## Per-trajectory classification

| # | Trajectory | Class | Manual finding |
| ---: | --- | --- | --- |
| 1 | `frontier_24ae328f30c1ee05c9f5ca56` | Valid alternative | Different ordering and sequential `n`/`o` shadowing; every source value and equality remains consistent. |
| 2 | `frontier_3224b6b91df6af756e66f21b` | Valid alternative | Reorders independent definitions and additions without changing any quantity. |
| 3 | `frontier_3e57f6929dceb5e8eb6d6d75` | Valid alternative | Reuses one-letter symbols sequentially, but each right-hand side uses the correct prior value. |
| 4 | `frontier_1105aa6c124ade24283c61cb` | Valid alternative | Same graph and arithmetic with a different accumulator order. |
| 5 | `frontier_5942b01c851d197860809988` | Valid alternative | Canonical-equivalent values, dependencies, and final total. |
| 6 | `frontier_791f1dd1cd3cfa837626e920` | Valid alternative | Different summation order; all equations are numerically and semantically valid. |
| 7 | `frontier_c10243723dd2187cc5683c99` | Stale-symbol alias | Maple bear `L=28` is overwritten by accumulator `L=11`; `L + L = 11 + 28` then uses both meanings simultaneously. |
| 8 | `frontier_78f36a535be02c65cda8fe50` | Valid alternative | Reordered sums and consistent sequential shadowing only. |
| 9 | `frontier_d1eef7edf0ad09ac2b33b970` | Valid alternative | Target symbols reuse earlier letters, but all old/new values are used in a consistent sequence. |
| 10 | `frontier_25628f13eb7ec9ea5364a9bc` | Valid alternative | The `N` accumulator shadows an earlier value without a stale later reference. |
| 11 | `frontier_e373fc7fd7f94d88134983b1` | Valid alternative | Same quantities and arithmetic under a different definition order. |
| 12 | `frontier_247f32d4173f692ce6d65245` | Valid alternative | Sequential reuse of `n` correctly carries the Clearwater value into the Ruby equation. |
| 13 | `frontier_4daf40da7e5c7bec73fc9f73` | Stale-symbol alias | Westhaven public-highschool `e=2` is overwritten by accumulator `e=20`, then later cited again as `e=2` for Hawkesbury regional school. |
| 14 | `frontier_5390567cd6015a54e8c02a65` | Valid alternative | Correctly copies the Bundle parrot value through a reused `o`; no stale use follows. |
| 15 | `frontier_c27ebbdc9b3cd750d325e46d` | Valid alternative | Self-updating `N` is sequential and numerically consistent. |
| 16 | `frontier_1ccd67c4287aaaa7525a55e3` | Valid alternative | Equivalent graph with different accumulation order. |
| 17 | `frontier_92107ad82ec4bf72442c2718` | Stale-symbol alias | Golden solemn `N=2` becomes accumulator `N=4`, while `N + N = 4 + 2` requires both meanings at once. |
| 18 | `frontier_d8d2fc97ab857b8b249c6dd2` | Stale-symbol alias | Shoreline culinarian `a=8` is overwritten by accumulator `a=12`, but Riverton private school later cites stale `a=8`. |
| 19 | `frontier_d26dd597b89c326aa557a12c` | Valid alternative | All prompt relations and totals match; only order and letters differ. |
| 20 | `frontier_ccfed20637275cde9e387474` | Valid alternative | `L=L+N` is a consistent sequential accumulation with no stale downstream use. |
| 21 | `frontier_bb4f76bc2d1abfb5c866656e` | Valid alternative | Canonical-equivalent dependencies and arithmetic. |
| 22 | `frontier_3f0394c0f3a6c56d4e511bd2` | Valid alternative | Same graph and values with reordered additions. |
| 23 | `frontier_382e39b65b4b93461875907f` | Valid alternative | `a=a=4` copies a same-valued prompt source; it is redundant-looking but correct. |
| 24 | `frontier_be700a9ea0987fb2142217f8` | Valid alternative | Stops once the requested Oakbridge regional value is derived; the derivation is correct. |
| 25 | `frontier_d943de947f1c548836ee863d` | Valid alternative | `t=t=2` copies the correct Clearwater elementary value into Riverton private school. |
| 26 | `frontier_89f51db8ced760e9f056cbe9` | Valid alternative | Different sum order with no arithmetic or dependency error. |
| 27 | `frontier_8f06984e5d397fac2bed44e5` | Valid alternative | Sequential target-symbol reuse remains consistent through the final total. |
| 28 | `frontier_55a257cf4278becf0b9417d6` | Valid alternative | All Hamilton, Bundle, and Jefferson values match the canonical graph. |
| 29 | `frontier_420110410263dd06972a509c` | Valid alternative | Reordered Bundle and Jefferson totals are correct. |
| 30 | `frontier_d5a7666a75865d5f1539893a` | Valid alternative | `N=t+N` intentionally uses the old Taylor value before overwriting `N`; no stale use follows. |
| 31 | `frontier_c64e96b21a032e4df74395d9` | Valid alternative | Same prompt-defined quantities with consistent shadowing. |
| 32 | `frontier_d4aebc32c204ce39cce414c4` | Valid alternative | Self-update of Westhaven `N` is sequential and correct. |
| 33 | `frontier_d5a620c7fb15ed3c6f4690d9` | Valid alternative | Equivalent aggregation order and values. |
| 34 | `frontier_527d2a04badb0733fb5b0c60` | Valid alternative | Correctly derives the requested Hawkesbury value without computing its unused total. |
| 35 | `frontier_2a553989acb90899b77195f1` | Stale-symbol alias | Cedar eagle `L=4` is overwritten by accumulator `L=8`; Pine owl and crow later cite stale `L=4`. |
| 36 | `frontier_fb3f047662643aa655cdf6bb` | Aliasing + false extras | Evervale `o` simultaneously denotes regional school 5 and accumulator 23. It also invents unsupported Westhaven/Glenfield nodes and writes false extra arithmetic `83 + 31 = 90`. |
| 37 | `frontier_bfed0c37d39a2bca6d7b44f1` | Valid alternative | Self-updating `N` correctly maps Verdi thriller 1 to West Sahara thriller 5. |
| 38 | `frontier_1e640783db8d15de46bb78b7` | Valid alternative | Same causal graph and exact arithmetic. |
| 39 | `frontier_6c3b8174f3abd17e9a9e68ec` | Valid alternative | Uses a running `s` total and later shadowing consistently. |
| 40 | `frontier_e72e5b3dbe495b17f79cd749` | Valid alternative | Different addition order only. |
| 41 | `frontier_7f2537df95a9f20f499dc1dd` | Valid alternative | Reused `a` retains the same value until all dependent nodes are resolved. |
| 42 | `frontier_cc613bc518e189b522f37fb9` | Valid alternative | Canonical-equivalent derivation and final total. |
| 43 | `frontier_d01ed5a7d63dab0d2764c972` | Valid alternative | `p=p=4` copies the correct Hawkesbury culinarian value into Westhaven regional school. |
| 44 | `frontier_348f51b17a96ab9da87a3418` | Valid alternative | Same dependencies and arithmetic under a different accumulator order. |
| 45 | `frontier_67898c26ddac63d7e173ebde` | Valid alternative | Equivalent Pine, Cedar, and Maple computation. |
| 46 | `frontier_165ee9b6081181a477b40261` | Stale-symbol alias | In Hawkesbury total, `s + s = 6 + 2` uses `s` as both the accumulator 6 and private-middle-school value 2. |
| 47 | `frontier_f84cc888b47df133944e62b9` | Valid alternative | Same values and dependencies with reordered sums. |
| 48 | `frontier_51357717d63c20a0fc4a6ceb` | Valid redundant definition | Riverton regional school is defined twice under different letters, both as 3; the duplicate is unnecessary but not wrong. |
| 49 | `frontier_12da8cdf20a6883fb8aca418` | Valid alternative | Sequential reuse in Oakridge total is internally consistent. |
| 50 | `frontier_cfb7040b5a9079b183fa8249` | Valid alternative | Same semantic graph and exact arithmetic. |

## Why the strict verifier accepts the seven defects

For each parsed semantic node, the verifier checks its parameter name,
dependency letters, and the final literal after the last equality sign. It
does not execute every intermediate equality with a stateful symbol table.
Consequently, a trajectory can write an ambiguous or false expression, append
the correct gold literal, and still reproduce the expected graph. Extra nodes
are also excluded from the `perfect` decision. This explains both the
stale-symbol cases and the unsupported extra subgraph in trajectory 36.
