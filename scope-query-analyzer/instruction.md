Cursorless is a structural code-editing system whose language-specific editing scopes are defined by tree-sitter query files (`.scm`) with a domain-specific capture naming convention. Four production Cursorless query files are at `/app/queries/` (Python, Java, JavaScript, TypeScript) with matching sample source files at `/app/samples/` (`python.scm` maps to `python_sample.py`, `java.scm` to `java_sample.java`, `javascript.scm` to `javascript_sample.js`, `typescript.scm` to `typescript_sample.ts`).

Pre-installed packages: `tree-sitter==0.25.2`, `tree-sitter-python==0.25.0`, `tree-sitter-java==0.23.5`, `tree-sitter-javascript==0.25.0`, `tree-sitter-typescript==0.23.2`.

Produce `/app/compiled_scopes.json` — a comprehensive static and dynamic analysis of the Cursorless scope system across all four query files. The JSON must conform to this schema (per-file keys use basenames like `python.scm`; all lists sorted alphabetically and deduplicated; predicate names retain their `#` prefix):

```json
{
  "query_validation": {
    "<file>": { "valid": "<bool>", "pattern_count": "<int>", "capture_count": "<int>" }
  },
  "imports": {
    "<file>": ["<imported_filename>"]
  },
  "scope_types": {
    "<file>": ["<scope_type_id>"]
  },
  "facets": {
    "<file>": { "<scope_type>": ["<facet>"] }
  },
  "predicates": {
    "filters": { "<#predicate>": "<total_count>" },
    "directives": { "<#predicate>": "<total_count>" }
  },
  "node_types": {
    "<file>": ["<named_node_type>"]
  },
  "cross_language_matrix": {
    "<scope_type>": ["<file>"]
  },
  "execution_results": {
    "<file>": {
      "total_capture_hits": "<int>",
      "unique_captures_matched": "<int>",
      "scope_types_matched": ["<scope_type>"]
    }
  }
}
```

The tool must correctly interpret Cursorless's query file conventions and the tree-sitter query language to perform this analysis. You need to understand the hierarchical capture naming scheme that Cursorless uses to encode scope semantics, the query file's comment and import conventions, the tree-sitter predicate taxonomy, and how to distinguish public from private scope identifiers. `query_validation` and `execution_results` require programmatic use of the tree-sitter Python bindings to validate queries against their language grammars and execute them against sample code. `predicates` aggregates occurrence counts across all four files. Only scope types that have at least one facet should appear in `facets`. `node_types` must exclude wildcard identifiers.