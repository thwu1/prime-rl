Complete the GritQL pattern at `/app/.grit/patterns/lodash_to_native.md` to migrate Lodash `_.*` utility calls to native JavaScript. The file contains inline test cases (before/after code block pairs) defining the expected transformations; the GritQL pattern body is a placeholder that must be replaced with a working implementation.

The pattern must transform these Lodash call categories to their native equivalents:
- Array iteration (`_.map`, `_.filter`, `_.find`, `_.forEach`, `_.some`, `_.every`, `_.includes`) and `_.reduce` (both 2-arg and 3-arg forms)
- Object utilities (`_.keys`/`_.values`/`_.entries` to `Object.*`)
- Type checks (`_.isArray` to `Array.isArray`, `_.isNil` to `== null`)
- Collection operations (`_.uniq` via `Set` spread, `_.flatten`/`_.flattenDeep` via `.flat()`, `_.compact` via `.filter(Boolean)`, `_.cloneDeep` via `structuredClone`)

The pattern must also handle conditional import management: remove `import _ from 'lodash'` or `const _ = require('lodash')` only when ALL `_.*` member expressions in a file have been eliminated by transformations. When untransformable calls remain (e.g. `_.debounce`), the import must be preserved.

The `grit` CLI is installed. You may create additional pattern files in `/app/.grit/patterns/` for pattern composition. The pattern is verified by `grit patterns test` (inline test cases) and by applying `grit apply lodash_to_native` to JavaScript files and checking both call transformations and import removal behavior.