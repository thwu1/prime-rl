A Unicode Collation Algorithm (UCA) implementation is provided at `/app/collator.py`. It loads the Default Unicode Collation Element Table (DUCET) from `/app/allkeys.txt` and supports two variable weighting modes: Non-Ignorable and Shifted.

The implementation has bugs and missing functionality. Subsets of the official UCA conformance test data are available in `/app/test_data/` for both modes (Non-Ignorable and Shifted). The UTS #10 specification reference is at `/app/uca_spec.txt`.

Fix `/app/collator.py` so that it correctly sorts strings according to the Unicode Collation Algorithm for **both** Non-Ignorable and Shifted variable weighting modes, passing the conformance test subsets (each line must produce a sort key >= the previous line's sort key).

The conformance tests verify:
- Non-Ignorable ordering on `/app/test_data/CollationTest_NON_IGNORABLE_subset.txt`
- Shifted ordering on `/app/test_data/CollationTest_SHIFTED_subset.txt`
- Correct implicit weight derivation for code points not in the DUCET (e.g. Tangut ideographs)
- Correct sort key values for known reference strings