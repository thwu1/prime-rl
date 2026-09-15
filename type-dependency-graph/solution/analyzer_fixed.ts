import * as ts from "typescript";
import * as path from "path";


interface SymbolInfo {
  name: string;
  kind: string;
  file: string;
  line: number;
  dependencies: string[];
  transitiveDependencies: string[];
  cyclicWith: string[];
}

function analyze(tsconfigPath: string): SymbolInfo[] {
  const absPath = path.resolve(tsconfigPath);
  const baseDir = path.dirname(absPath);

  const configFile = ts.readConfigFile(absPath, ts.sys.readFile);
  if (configFile.error) {
    throw new Error(
      ts.flattenDiagnosticMessageText(configFile.error.messageText, "\n")
    );
  }
  const parsed = ts.parseJsonConfigFileContent(
    configFile.config,
    ts.sys,
    baseDir
  );

  const program = ts.createProgram(parsed.fileNames, parsed.options);
  const checker = program.getTypeChecker();

  const projectPaths = new Set(parsed.fileNames.map((f) => path.resolve(f)));
  const results: SymbolInfo[] = [];

  for (const sf of program.getSourceFiles()) {
    if (sf.isDeclarationFile) continue;
    const resolved = path.resolve(sf.fileName);
    if (!projectPaths.has(resolved)) continue;

    const relFile = path.relative(baseDir, sf.fileName);

    ts.forEachChild(sf, (node) => {
      if (
        !(
          ts.getCombinedModifierFlags(node as ts.Declaration) &
          ts.ModifierFlags.Export
        )
      )
        return;

      let name: string | undefined;
      let kind: string | undefined;

      if (ts.isInterfaceDeclaration(node)) {
        name = node.name.text;
        kind = "interface";
      } else if (ts.isTypeAliasDeclaration(node)) {
        name = node.name.text;
        kind = "type";
      } else if (ts.isEnumDeclaration(node)) {
        name = node.name.text;
        kind = "enum";
      } else if (ts.isFunctionDeclaration(node) && node.name) {
        name = node.name.text;
        kind = "function";
      } else if (ts.isClassDeclaration(node) && node.name) {
        name = node.name.text;
        kind = "class";
      }

      if (!name || !kind) return;

      const deps = collectDeps(
        node as ts.Declaration,
        checker,
        projectPaths
      );
      const line =
        sf.getLineAndCharacterOfPosition(node.getStart()).line + 1;
      results.push({
        name,
        kind,
        file: relFile,
        line,
        dependencies: Array.from(deps).sort(),
        transitiveDependencies: [],
        cyclicWith: [],
      });
    });
  }

  computeTransitiveDeps(results);
  detectCycles(results);

  results.sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line);
  return results;
}

function collectDeps(
  decl: ts.Declaration,
  checker: ts.TypeChecker,
  projectPaths: Set<string>
): Set<string> {
  const deps = new Set<string>();
  const roots: ts.Node[] = [];

  if (ts.isInterfaceDeclaration(decl)) {
    if (decl.heritageClauses) roots.push(...decl.heritageClauses);
    if (decl.typeParameters) {
      decl.typeParameters.forEach((tp) => {
        if (tp.constraint) roots.push(tp.constraint);
      });
    }
    roots.push(...decl.members);
  } else if (ts.isTypeAliasDeclaration(decl)) {
    roots.push(decl.type);
    if (decl.typeParameters) {
      decl.typeParameters.forEach((tp) => {
        if (tp.constraint) roots.push(tp.constraint);
      });
    }
  } else if (ts.isFunctionDeclaration(decl)) {
    decl.parameters.forEach((p) => {
      if (p.type) roots.push(p.type);
    });
    if (decl.type) roots.push(decl.type);
    if (decl.typeParameters) {
      decl.typeParameters.forEach((tp) => {
        if (tp.constraint) roots.push(tp.constraint);
      });
    }
  } else if (ts.isClassDeclaration(decl)) {
    if (decl.heritageClauses) roots.push(...decl.heritageClauses);
    if (decl.typeParameters) {
      decl.typeParameters.forEach((tp) => {
        if (tp.constraint) roots.push(tp.constraint);
      });
    }
    for (const m of decl.members) {
      if (ts.isPropertyDeclaration(m) && m.type) {
        roots.push(m.type);
      } else if (ts.isMethodDeclaration(m)) {
        m.parameters.forEach((p) => {
          if (p.type) roots.push(p.type);
        });
        if (m.type) roots.push(m.type);
        if (m.typeParameters) {
          m.typeParameters.forEach((tp) => {
            if (tp.constraint) roots.push(tp.constraint);
          });
        }
      }
    }
  }

  for (const root of roots) {
    walkTypeNodes(root, checker, projectPaths, deps);
  }
  return deps;
}

function resolveAndAddSymbol(
  sym: ts.Symbol | undefined,
  checker: ts.TypeChecker,
  projectPaths: Set<string>,
  deps: Set<string>
): void {
  if (!sym) return;
  let resolved = sym;
  if (resolved.flags & ts.SymbolFlags.Alias) {
    resolved = checker.getAliasedSymbol(resolved);
  }
  if (
    !(resolved.flags & ts.SymbolFlags.TypeParameter) &&
    isInProject(resolved, projectPaths)
  ) {
    deps.add(resolved.getName());
  }
}

function walkTypeNodes(
  node: ts.Node,
  checker: ts.TypeChecker,
  projectPaths: Set<string>,
  deps: Set<string>
): void {
  if (ts.isTypeReferenceNode(node)) {
    resolveAndAddSymbol(
      checker.getSymbolAtLocation(node.typeName),
      checker,
      projectPaths,
      deps
    );
  } else if (ts.isExpressionWithTypeArguments(node)) {
    resolveAndAddSymbol(
      checker.getSymbolAtLocation(node.expression),
      checker,
      projectPaths,
      deps
    );
  }

  ts.forEachChild(node, (child) => {
    if (ts.isBlock(child)) return;
    walkTypeNodes(child, checker, projectPaths, deps);
  });
}

function isInProject(sym: ts.Symbol, projectPaths: Set<string>): boolean {
  const decls = sym.getDeclarations();
  if (!decls) return false;
  return decls.some((d) =>
    projectPaths.has(path.resolve(d.getSourceFile().fileName))
  );
}

function computeTransitiveDeps(results: SymbolInfo[]): void {
  const depMap = new Map<string, string[]>();
  for (const r of results) {
    depMap.set(r.name, r.dependencies);
  }

  for (const r of results) {
    const visited = new Set<string>();
    visited.add(r.name);
    const reachable = new Set<string>();
    const stack = [...r.dependencies];

    while (stack.length > 0) {
      const current = stack.pop()!;
      if (visited.has(current)) continue;
      visited.add(current);
      reachable.add(current);
      const subDeps = depMap.get(current);
      if (subDeps) {
        for (const d of subDeps) {
          if (!visited.has(d)) {
            stack.push(d);
          }
        }
      }
    }

    r.transitiveDependencies = Array.from(reachable).sort();
  }
}

function detectCycles(results: SymbolInfo[]): void {
  const depMap = new Map<string, string[]>();
  for (const r of results) {
    depMap.set(r.name, r.dependencies);
  }

  const allNames = results.map((r) => r.name);
  let index = 0;
  const stack: string[] = [];
  const onStack = new Set<string>();
  const indices = new Map<string, number>();
  const lowlinks = new Map<string, number>();
  const sccs: string[][] = [];

  function strongconnect(v: string): void {
    indices.set(v, index);
    lowlinks.set(v, index);
    index++;
    stack.push(v);
    onStack.add(v);

    const deps = depMap.get(v) || [];
    for (const w of deps) {
      if (!indices.has(w)) {
        if (!depMap.has(w)) continue;
        strongconnect(w);
        lowlinks.set(v, Math.min(lowlinks.get(v)!, lowlinks.get(w)!));
      } else if (onStack.has(w)) {
        lowlinks.set(v, Math.min(lowlinks.get(v)!, indices.get(w)!));
      }
    }

    if (lowlinks.get(v) === indices.get(v)) {
      const scc: string[] = [];
      let w: string;
      do {
        w = stack.pop()!;
        onStack.delete(w);
        scc.push(w);
      } while (w !== v);
      if (scc.length > 1) {
        sccs.push(scc);
      }
    }
  }

  for (const name of allNames) {
    if (!indices.has(name)) {
      strongconnect(name);
    }
  }

  const sccMap = new Map<string, string[]>();
  for (const scc of sccs) {
    for (const name of scc) {
      sccMap.set(
        name,
        scc.filter((n) => n !== name).sort()
      );
    }
  }

  for (const r of results) {
    r.cyclicWith = sccMap.get(r.name) || [];
  }
}

const arg = process.argv[2];
if (!arg) {
  console.error("Usage: node analyzer.js <tsconfig.json>");
  process.exit(1);
}
console.log(JSON.stringify(analyze(arg), null, 2));
