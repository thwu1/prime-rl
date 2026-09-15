A TypeScript ICU MessageFormat library at `/app/` has bugs in its parser and formatter, and its plural category resolver is unimplemented. The CLI reads JSON from stdin (`{"pattern": string, "locale": string, "values": object}`) and writes the formatted message to stdout via `npx tsx /app/src/index.ts`. Run `npm install` in `/app/` first.

The plural category resolver at `/app/src/plural-rules.ts` is a stub returning `'other'`. It must be implemented to evaluate CLDR plural rule expressions using the data at `/app/data/plurals.json` (cardinal) and `/app/data/ordinals.json` (ordinal). The data uses the standard CLDR supplemental JSON format; each rule string may contain the expression followed by `@integer`/`@decimal` sample annotations that are not part of the rule logic.

The parser and formatter also contain bugs. The correct behaviors are:

- **Plural arguments** (`{n, plural, offset:N =0 {...} one {...} other {...}}`): `#` substitutes `value - offset`, exact-match selectors (`=N`) match the raw value, the plural category is determined by the resolver applied to `value - offset`.
- **Selectordinal arguments**: must use ordinal plural rules.
- **ICU 4.8+ apostrophe quoting**: `''` yields a literal `'`; apostrophe before `{`, `}`, `<`, `>`, or `#` (only inside plural/selectordinal) opens a quoted region closed by the next unescaped `'`.
- **Locale-aware `#` formatting**: `#` within plural/selectordinal must format via `Intl.NumberFormat` for the active locale.
- **Multi-locale cardinal rules**: English (one/other), Russian (one/few/many/other), Arabic (zero/one/two/few/many/other), Polish (one/few/many/other), Welsh (zero/one/two/few/many/other).
- **Ordinal rules**: English ordinals (one/two/few/other).
- **Locale fallback**: `en-US` must resolve to `en` rules when absent from data.

Source files: `/app/src/types.ts`, `/app/src/parser.ts`, `/app/src/formatter.ts`, `/app/src/plural-rules.ts`, `/app/src/index.ts`.

Success: `bash /tests/test.sh` writes `1.0` to `/logs/verifier/reward.txt`.
