A Node.js CLI tool at `/app` formats ICU MessageFormat patterns with locale-aware plural resolution. The TypeScript codebase currently fails to compile and produces incorrect output for many inputs.

**CLI:**
```
node /app/dist/index.js '<pattern>' '<locale>' '<values_json>'
```

**Build:**
```
cd /app && npm install && npx tsc
```

TypeScript source in `/app/src/` must compile cleanly to `/app/dist/`.

**Plural resolution** must evaluate the CLDR plural rule expressions shipped in `/app/data/supplemental/plurals.json` (cardinal) and `ordinals.json` (ordinal). The evaluator must correctly interpret the full expression grammar used in these data files to resolve plural categories for any number and locale present in the data.

**Supported locales (cardinal):** en, fr, ar, cy, ru, pt, pl, ja.
**Supported locale (ordinal):** en.

**Required behaviors:**

- Exact-match selectors (`=N`) compare against the raw input value; plural category resolution uses the offset-adjusted value.
- `#` in plural/selectordinal branches is replaced with the offset-adjusted value formatted via `Intl.NumberFormat`. In select branches, `#` is literal text.
- Apostrophe quoting (ICU 4.8): `'` before `{`, `}`, `<`, `>`, or `#` (in plural/selectordinal context) opens a quoted span closed by the next unescaped `'`. `''` is a literal apostrophe. `'` not before a syntax character is literal.
- `false`, `null`, `undefined` produce empty string; `0` produces `"0"`.
- Select/plural option maps must be prototype-safe.

**Success criteria:** `npm install && npx tsc` succeeds; all verification tests pass.
