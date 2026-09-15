import * as ts from "typescript";
import * as path from "path";
import * as fs from "fs";


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

  // Read tsconfig manually
  const configText = fs.readFileSync(absPath, "utf-8");
  const rawConfig = JSON.parse(configText);
  const rootDir = rawConfig.compilerOptions?.rootDir || ".";
  const srcDir = path.join(baseDir, rootDir);

  const fileNames = collectTsFiles(srcDir);
  const program = ts.createProgram(fileNames, {
    target: ts.ScriptTarget.ES2020,
    module: ts.ModuleKind.CommonJS,
    strict: true,
  });
  const checker = program.getTypeChecker();

  const projectPaths = new Set(fileNames.map((f) => path.resolve(f)));
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

      if (ts.isInterfaceDeclaration(node)) {
        const deps = getInterfaceDeps(node, checker, projectPaths);
        const line =
          sf.getLineAndCharacterOfPosition(node.getStart()).line + 1;
        results.push({
          name: node.name.text,
          kind: "interface",
          file: relFile,
          line,
          dependencies: deps,
          transitiveDependencies: [],
          cyclicWith: [],
        });
      } else if (ts.isClassDeclaration(node) && node.name) {
        const deps = getClassDeps(node, checker, projectPaths);
        const line =
          sf.getLineAndCharacterOfPosition(node.getStart()).line + 1;
        results.push({
          name: node.name.text,
          kind: "class",
          file: relFile,
          line,
          dependencies: deps,
          transitiveDependencies: [],
          cyclicWith: [],
        });
      }
    });
  }

  computeTransitiveDeps(results);
  detectCycles(results);

  return results;
}

function collectTsFiles(dir: string): string[] {
  const out: string[] = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...collectTsFiles(full));
    else if (ent.name.endsWith(".ts") && !ent.name.endsWith(".d.ts"))
      out.push(full);
  }
  return out;
}

function getInterfaceDeps(
  node: ts.InterfaceDeclaration,
  checker: ts.TypeChecker,
  projectPaths: Set<string>
): string[] {
  const deps = new Set<string>();

  // Heritage clauses (extends)
  if (node.heritageClauses) {
    for (const clause of node.heritageClauses) {
      for (const t of clause.types) {
        const sym = checker.getSymbolAtLocation(t.expression);
        if (sym && isInProject(sym, projectPaths)) {
          deps.add(sym.getName());
        }
      }
    }
  }

  // Member property types
  for (const member of node.members) {
    if (ts.isPropertySignature(member) && member.type) {
      addTypeRef(member.type, checker, projectPaths, deps);
    }
  }

  return Array.from(deps);
}

function getClassDeps(
  node: ts.ClassDeclaration,
  checker: ts.TypeChecker,
  projectPaths: Set<string>
): string[] {
  const deps = new Set<string>();

  if (node.heritageClauses) {
    for (const clause of node.heritageClauses) {
      for (const t of clause.types) {
        const sym = checker.getSymbolAtLocation(t.expression);
        if (sym && isInProject(sym, projectPaths)) {
          deps.add(sym.getName());
        }
      }
    }
  }

  return Array.from(deps);
}

function addTypeRef(
  typeNode: ts.TypeNode,
  checker: ts.TypeChecker,
  projectPaths: Set<string>,
  deps: Set<string>
): void {
  if (ts.isTypeReferenceNode(typeNode)) {
    const sym = checker.getSymbolAtLocation(typeNode.typeName);
    if (sym && isInProject(sym, projectPaths)) {
      deps.add(sym.getName());
    }
  }
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
    const transitive = new Set<string>();
    const stack = [...r.dependencies];

    while (stack.length > 0) {
      const current = stack.pop()!;
      if (visited.has(current)) continue;
      visited.add(current);
      transitive.add(current);
      const subDeps = depMap.get(current);
      if (subDeps) {
        for (const d of subDeps) {
          stack.push(d);
        }
      }
    }

    r.transitiveDependencies = Array.from(transitive).sort();
  }
}

function detectCycles(results: SymbolInfo[]): void {
  const depMap = new Map<string, Set<string>>();
  for (const r of results) {
    depMap.set(r.name, new Set(r.dependencies));
  }

  for (const r of results) {
    const partners: string[] = [];
    for (const dep of r.dependencies) {
      const depDeps = depMap.get(dep);
      if (depDeps && depDeps.has(r.name)) {
        partners.push(dep);
      }
    }
    r.cyclicWith = partners.sort();
  }
}

// Entry point
const arg = process.argv[2];
if (!arg) {
  console.error("Usage: node analyzer.js <tsconfig.json>");
  process.exit(1);
}
console.log(JSON.stringify(analyze(arg), null, 2));
