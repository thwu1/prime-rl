The TypeScript project at `/app/` implements Unicode Extended Grapheme Cluster boundary detection per UAX #29. The implementation is broken -- it fails the majority of the official Unicode 17.0 test vectors from `GraphemeBreakTest.txt`.

Fix all issues so the segmenter fully conforms to the specification and passes every official test vector.

**Build:**
```
npm install --ignore-scripts && npx tsc
```

**CLI interface (after build):**
- `node dist/cli.js test` -- runs all official GraphemeBreakTest.txt vectors; must exit 0
- `node dist/cli.js test-json` -- same, but outputs JSON: `{"passed":N,"failed":N,"total":N,"failures":[...]}`
- `node dist/cli.js graphemes-hex <hex>...` -- segments code point arguments into grapheme clusters

**Success criteria:**
- TypeScript compilation produces no errors
- All 766 official test vectors pass (`node dist/cli.js test` exits 0)
- `node dist/cli.js test-json` outputs `{"passed":766,"failed":0,"total":766,"failures":[]}`
- The `graphemes-hex` subcommand correctly segments arbitrary code point sequences, including emoji ZWJ sequences, regional indicator flags, and Indic conjunct clusters

**Project layout:**
- `/app/src/properties.ts` -- loads Unicode character property data from `/app/data/`
- `/app/src/segmenter.ts` -- grapheme boundary detection algorithm (GB1-GB999)
- `/app/src/cli.ts` -- CLI entry point
- `/app/data/` -- Unicode data files (GraphemeBreakProperty.txt, ExtPict.txt, InCB.txt, emoji-data.txt, GraphemeBreakTest.txt) in standard UCD formats
- `/app/package.json`, `/app/tsconfig.json` -- project configuration
