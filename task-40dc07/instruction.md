A Node.js application at `/app/` uses a `featureToggle()` utility to gate features behind runtime flags. The flag `feature-pricing-v2` has been permanently enabled in production and must be completely eliminated from the source code.

Source files under `/app/src/` reference this toggle through a variety of coding patterns. After the toggle is removed, each module must behave as if `feature-pricing-v2` were unconditionally `true` — the "new" code path should be the only one remaining. Any code, declarations, or imports that exist solely to support the disabled path should be cleaned up.

The application uses other feature toggles (`feature-free-shipping`, `feature-search-refinement`) that must remain completely unaffected.

**Constraints:**
- `/app/src/utils/featureToggle.js` must not be modified
- All transformed files must be syntactically valid JavaScript and produce correct results

```
```