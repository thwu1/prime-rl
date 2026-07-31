# Third-party notices

`vendor/gsm_infinite/` contains the realistic GSM-Infinite graph and text generator from [Interplay-LM-Reasoning/Interplay-LM-Reasoning](https://github.com/Interplay-LM-Reasoning/Interplay-LM-Reasoning), commit `ab728f05d81de9af38d0ca155a84166b037e355a`.

The vendored files retain the upstream generation logic. Imports were made package-relative, visualization-only dependencies were made lazy, terminal coloring was replaced by a local no-op helper, parameter-node hashing was made process-stable, and an upstream `exit(0)` failure path now raises a proposal-rejection error.

The upstream project is distributed under the MIT License; see `vendor/gsm_infinite/LICENSE`.
