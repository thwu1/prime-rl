A TypeScript type dependency graph analyzer exists at `/app/`. When built and run against the target project at `/app/target-project/`, it must produce a JSON array to stdout describing every exported symbol, its direct type dependencies, its transitive dependency closure, and any cyclic dependency groups.

**Build and run:**
```
cd /app && npm install && npx tsc && node dist/analyzer.js target-project/tsconfig.json
```

**Output schema:** A JSON array, sorted by `file` (ascending) then by `line` (ascending). Each element:
```json
{
  "name": "<symbol name>",
  "kind": "<interface|type|enum|function|class>",
  "file": "<path relative to target project root>",
  "line": "<1-based line number of declaration>",
  "dependencies": ["<alphabetically sorted direct project-symbol names>"],
  "transitiveDependencies": ["<alphabetically sorted, all symbols reachable via dependency edges, excluding self>"],
  "cyclicWith": ["<alphabetically sorted, other symbols mutually reachable via dependency chains, excluding self>"]
}
```

**Dependency rules:**
- Include only symbols declared in the target project's own source files.
- Exclude built-in/global types (`string`, `number`, `Date`, `Promise`, `Array`, `Partial`, `Pick`, `Omit`, `Record`, `Capitalize`, etc.), generic type parameters, and type variables introduced by `infer`.
- Extract type references from all positions: heritage clauses and their type arguments, generic constraints, property types, method parameter/return types, and within compound/nested type expressions (unions, intersections, tuples, mapped types, conditional types, indexed access types, keyof operators, array types, function types).
- Recursive types that reference themselves must include their own name in `dependencies`.
- `transitiveDependencies` contains the full set of symbols reachable by following dependency edges, excluding the symbol itself. Self-referential types with no other project deps have empty transitive sets.
- `cyclicWith` lists other symbols from which this symbol is reachable and that are reachable from this symbol through dependency chains. Groups of size 1 (including self-referential types) produce empty `cyclicWith`.

**Scope:**
The target project at `/app/target-project/` contains six source files exercising inheritance chains with type arguments, generic constraints, utility types, mapped types, conditional types with `infer`, recursive types, intersection types, tuple types, indexed access types, `keyof` type operators, cross-file imports, and mutually recursive interface/type declarations that form dependency cycles.

The current implementation at `/app/src/analyzer.ts` compiles and runs but produces incomplete and incorrect results. Fix it so that the output matches the specification above for the provided target project.
