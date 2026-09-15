#!/usr/bin/env python3
"""
Fix all bugs in the BIDS expression language evaluator, sidecar inheritance
resolver, and validation rule engine.


This script diagnoses and patches 12 bugs in the expression evaluator,
3 issues in the inheritance resolver (2 bugs + 1 incomplete implementation),
and 4 bugs in the validation rule engine.
"""

import os
import sys


def read_file(path: str) -> str:
    if not os.path.isfile(path):
        parent = os.path.dirname(path)
        if os.path.isdir(parent):
            contents = os.listdir(parent)
            print(f"ERROR: {path} not found. Files in {parent}: {contents}", file=sys.stderr)
        else:
            print(f"ERROR: {path} not found. Parent dir {parent} does not exist.", file=sys.stderr)
        raise FileNotFoundError(f"File not found: {path}")
    with open(path, "r") as f:
        return f.read()


def write_file(path: str, content: str) -> None:
    with open(path, "w") as f:
        f.write(content)


def fix_lexer():
    """Bug 1: The != operator is not tokenized as a two-character token."""
    path = "/app/src/lexer.ts"
    src = read_file(path)

    old = """      if (two === '==') {
        tokens.push({ type: TokenType.EqualEqual, value: '==', position: pos });
        pos += 2;
        continue;
      }
      if (two === '<=') {"""

    new = """      if (two === '==') {
        tokens.push({ type: TokenType.EqualEqual, value: '==', position: pos });
        pos += 2;
        continue;
      }
      if (two === '!=') {
        tokens.push({ type: TokenType.BangEqual, value: '!=', position: pos });
        pos += 2;
        continue;
      }
      if (two === '<=') {"""

    assert old in src, "Could not find lexer == handler block"
    src = src.replace(old, new)
    write_file(path, src)
    print("  [FIXED] Lexer: added != two-character token")


def fix_parser():
    """Bugs 2-4: Parser is missing modulo, 'in' operator, and object literal."""
    path = "/app/src/parser.ts"
    src = read_file(path)

    # Bug 2: Add % to multiplicative operators
    old_mult = """    while (
      this.peek().type === TokenType.Star ||
      this.peek().type === TokenType.Slash
    ) {"""

    new_mult = """    while (
      this.peek().type === TokenType.Star ||
      this.peek().type === TokenType.Slash ||
      this.peek().type === TokenType.Percent
    ) {"""

    assert old_mult in src, "Could not find multiplicative operator block"
    src = src.replace(old_mult, new_mult)
    print("  [FIXED] Parser: added % to multiplicative operators")

    # Bug 3: Add 'in' operator at comparison level
    old_cmp_end = """      left = { type: 'BinaryOp', operator: op, left, right };
    }
    return left;
  }

  private parseAdditive"""

    new_cmp_end = """      left = { type: 'BinaryOp', operator: op, left, right };
    }
    if (this.peek().type === TokenType.In) {
      this.advance();
      const right = this.parseAdditive();
      left = { type: 'InExpression', value: left, collection: right };
    }
    return left;
  }

  private parseAdditive"""

    assert old_cmp_end in src, "Could not find comparison method ending"
    src = src.replace(old_cmp_end, new_cmp_end)
    print("  [FIXED] Parser: added 'in' operator at comparison level")

    # Bug 4: Add object literal {} parsing
    old_default = """      default:
        throw new Error(
          `Unexpected token: ${token.type} (${token.value}) at position ${token.position}`
        );"""

    new_default = """      case TokenType.LeftBrace: {
        this.advance();
        this.expect(TokenType.RightBrace);
        return { type: 'ObjectLiteral' };
      }

      default:
        throw new Error(
          `Unexpected token: ${token.type} (${token.value}) at position ${token.position}`
        );"""

    assert old_default in src, "Could not find parser default case"
    src = src.replace(old_default, new_default)
    print("  [FIXED] Parser: added object literal {} support")

    write_file(path, src)


def fix_evaluator():
    """Bugs 5-8: Evaluator has issues with &&, !null, member access, and indexing."""
    path = "/app/src/evaluator.ts"
    src = read_file(path)

    # Bug 5: && returns false instead of left value
    old_and = """      if (node.operator === '&&') {
        const left = evaluate(node.left, context);
        if (!left) return false;
        return evaluate(node.right, context);
      }"""

    new_and = """      if (node.operator === '&&') {
        const left = evaluate(node.left, context);
        if (!left) return left;
        return evaluate(node.right, context);
      }"""

    assert old_and in src, "Could not find && operator block"
    src = src.replace(old_and, new_and)
    print("  [FIXED] Evaluator: && now returns actual left value (null propagation)")

    # Bug 6: !null returns null instead of true
    old_not = """        case '!':
          if (operand === null) return null;
          return !operand;"""

    new_not = """        case '!':
          return !operand;"""

    assert old_not in src, "Could not find ! operator block"
    src = src.replace(old_not, new_not)
    print("  [FIXED] Evaluator: !null now returns true")

    # Bug 7: Member access on null throws
    old_member = """    case 'MemberAccess': {
      const obj = evaluate(node.object, context);
      if (typeof obj !== 'object' || obj === null) {
        throw new Error(`Cannot access property '${node.property}' of ${obj}`);
      }
      const val = (obj as Record<string, unknown>)[node.property];
      return val === undefined ? null : val;
    }"""

    new_member = """    case 'MemberAccess': {
      const obj = evaluate(node.object, context);
      if (obj === null || obj === undefined) return null;
      if (typeof obj !== 'object') {
        throw new Error(`Cannot access property '${node.property}' of ${obj}`);
      }
      const val = (obj as Record<string, unknown>)[node.property];
      return val === undefined ? null : val;
    }"""

    assert old_member in src, "Could not find MemberAccess block"
    src = src.replace(old_member, new_member)
    print("  [FIXED] Evaluator: member access on null returns null")

    # Bug 8: Index access doesn't handle null/strings
    old_index = """    case 'IndexAccess': {
      const obj = evaluate(node.object, context);
      const idx = evaluate(node.index, context);
      if (!Array.isArray(obj)) {
        throw new Error(`Cannot index into non-array value`);
      }
      return obj[idx as number];
    }"""

    new_index = """    case 'IndexAccess': {
      const obj = evaluate(node.object, context);
      if (obj === null || obj === undefined) return null;
      const idx = evaluate(node.index, context);
      if (Array.isArray(obj)) {
        return obj[idx as number];
      }
      if (typeof obj === 'string') {
        return obj[idx as number];
      }
      throw new Error(`Cannot index into value of type ${typeof obj}`);
    }"""

    assert old_index in src, "Could not find IndexAccess block"
    src = src.replace(old_index, new_index)
    print("  [FIXED] Evaluator: index access handles null and strings")

    write_file(path, src)


def fix_functions():
    """Bugs 9-12: Built-in functions have semantic errors."""
    path = "/app/src/functions.ts"
    src = read_file(path)

    # Bug 9: sorted() auto mode uses String comparison
    old_sorted_auto = """      auto: (a: unknown, b: unknown) => {
        const sa = String(a), sb = String(b);
        if (sa < sb) return -1;
        if (sa > sb) return 1;
        return 0;
      },"""

    new_sorted_auto = """      auto: (a: unknown, b: unknown) => +(a as number > (b as number)) - +(a as number < (b as number)),"""

    assert old_sorted_auto in src, "Could not find sorted auto comparator"
    src = src.replace(old_sorted_auto, new_sorted_auto)
    print("  [FIXED] Functions: sorted() auto mode uses native comparison")

    # Bug 10: intersects() returns empty array instead of false
    old_intersects = """    if (a === null || b === null) return false;
    const arrA = Array.isArray(a) ? a : [a];
    const arrB = Array.isArray(b) ? b : [b];
    const bSet = new Set(arrB);
    return arrA.filter((x: unknown) => bSet.has(x));"""

    new_intersects = """    if (a === null || b === null) return false;
    const arrA = Array.isArray(a) ? a : [a];
    const arrB = Array.isArray(b) ? b : [b];
    if (arrB.length === 0) return false;
    const bSet = new Set(arrB);
    const intersection = arrA.filter((x: unknown) => bSet.has(x));
    return intersection.length === 0 ? false : intersection;"""

    assert old_intersects in src, "Could not find intersects function body"
    src = src.replace(old_intersects, new_intersects)
    print("  [FIXED] Functions: intersects() returns false for empty intersection")

    # Bug 11: allequal() crashes on null
    old_allequal = """  allequal: (a: unknown, b: unknown): boolean => {
    const arrA = a as unknown[];
    const arrB = b as unknown[];
    if (arrA.length !== arrB.length) return false;
    return arrA.every((v: unknown, i: number) => v === arrB[i]);
  },"""

    new_allequal = """  allequal: (a: unknown, b: unknown): boolean => {
    if (a === null || b === null) return false;
    if (!Array.isArray(a) || !Array.isArray(b)) return false;
    if (a.length !== b.length) return false;
    return a.every((v: unknown, i: number) => v === b[i]);
  },"""

    assert old_allequal in src, "Could not find allequal function body"
    src = src.replace(old_allequal, new_allequal)
    print("  [FIXED] Functions: allequal() handles null arguments")

    # Bug 12: match() returns false for null target
    old_match = """  match: (target: unknown, regex: unknown): unknown => {
    if (typeof target !== 'string' || typeof regex !== 'string') return false;
    return new RegExp(regex).test(target);
  },"""

    new_match = """  match: (target: unknown, regex: unknown): unknown => {
    if (target === null) return null;
    if (regex === null) return false;
    if (typeof target !== 'string' || typeof regex !== 'string') return false;
    return new RegExp(regex).test(target);
  },"""

    assert old_match in src, "Could not find match function body"
    src = src.replace(old_match, new_match)
    print("  [FIXED] Functions: match() returns null for null target")

    write_file(path, src)


def fix_inheritance():
    """Bugs 13-15: Inheritance resolver has compound extension bug, entity
    match direction bug, and incomplete path walking."""
    path = "/app/src/inheritance.ts"
    src = read_file(path)

    # Bug 13: parseFilename uses lastIndexOf('.') — gets .gz instead of .nii.gz
    old_parse = """  const dotIdx = name.lastIndexOf('.');
  let extension = '';
  let stem = name;
  if (dotIdx !== -1) {
    extension = name.slice(dotIdx);
    stem = name.slice(0, dotIdx);
  }"""

    new_parse = """  // Handle compound extensions like .nii.gz, .tsv.gz, .surf.gii
  let extension = '';
  let stem = name;
  const compoundExts = ['.nii.gz', '.tsv.gz', '.surf.gii'];
  let matched = false;
  for (const ext of compoundExts) {
    if (name.endsWith(ext)) {
      extension = ext;
      stem = name.slice(0, -ext.length);
      matched = true;
      break;
    }
  }
  if (!matched) {
    const dotIdx = name.lastIndexOf('.');
    if (dotIdx !== -1) {
      extension = name.slice(dotIdx);
      stem = name.slice(0, dotIdx);
    }
  }"""

    assert old_parse in src, "Could not find parseFilename extension block"
    src = src.replace(old_parse, new_parse)
    print("  [FIXED] Inheritance: parseFilename handles compound extensions (.nii.gz)")

    # Bug 14: matchesSidecar iterates over target.entities (wrong direction)
    old_match = """  for (const [key, value] of Object.entries(target.entities)) {
    if (sidecar.entities[key] !== undefined && sidecar.entities[key] !== value) {
      return false;
    }
    if (sidecar.entities[key] === undefined) return false;
  }
  return true;"""

    new_match = """  for (const [key, value] of Object.entries(sidecar.entities)) {
    if (target.entities[key] !== value) {
      return false;
    }
  }
  return true;"""

    assert old_match in src, "Could not find matchesSidecar entity check"
    src = src.replace(old_match, new_match)
    print("  [FIXED] Inheritance: matchesSidecar checks sidecar entities subset of target")

    # Bug 15: resolveInheritance only checks the deepest directory
    old_resolve = """  // Only examines the immediate (deepest) directory for sidecars.
  const lastNode = pathNodes[pathNodes.length - 1];
  const resolved: Record<string, unknown> = {};
  const applied: string[] = [];

  if (lastNode.files) {
    for (const file of lastNode.files) {
      if (matchesSidecar(file.name, target)) {
        Object.assign(resolved, file.metadata);
        const nodePath = dirParts.length > 0 ? '/' + dirParts.join('/') : '';
        applied.push(nodePath + '/' + file.name);
      }
    }
  }

  return {"""

    new_resolve = """  // Walk all directories from root to deepest, collecting and merging sidecars.
  // Closer (deeper) sidecars override more distant (shallower) ones.
  const resolved: Record<string, unknown> = {};
  const applied: string[] = [];

  for (let i = 0; i < pathNodes.length; i++) {
    const node = pathNodes[i];
    const nodePath = i === 0 ? '' : '/' + dirParts.slice(0, i).join('/');
    if (node.files) {
      for (const file of node.files) {
        if (matchesSidecar(file.name, target)) {
          Object.assign(resolved, file.metadata);
          applied.push(nodePath + '/' + file.name);
        }
      }
    }
  }

  return {"""

    assert old_resolve in src, "Could not find resolveInheritance body"
    src = src.replace(old_resolve, new_resolve)
    print("  [FIXED] Inheritance: resolveInheritance walks full ancestor path")

    write_file(path, src)


def fix_rule_engine():
    """Bugs A-D: Rule engine has issues with selector matching, context
    construction, depends_on logic, and pass/fail determination."""
    path = "/app/src/rule_engine.ts"
    src = read_file(path)

    # Bug A: matchSelector ignores entity requirements
    old_selector_end = """  if (selector.extensions && selector.extensions.length > 0) {
    if (!selector.extensions.includes(context.extension)) return false;
  }
  return true;
}"""

    new_selector_end = """  if (selector.extensions && selector.extensions.length > 0) {
    if (!selector.extensions.includes(context.extension)) return false;
  }
  if (selector.entities) {
    for (const [entity, requirement] of Object.entries(selector.entities)) {
      if (requirement === 'required' && !(entity in context.entities)) {
        return false;
      }
    }
  }
  return true;
}"""

    assert old_selector_end in src, "Could not find matchSelector ending"
    src = src.replace(old_selector_end, new_selector_end)
    print("  [FIXED] Rule engine: matchSelector now checks entity requirements")

    # Bug B: buildEvalContext spreads sidecar flat and omits columns
    old_context = """    entities: fileContext.entities,
    ...fileContext.sidecar,
  };"""

    new_context = """    entities: fileContext.entities,
    sidecar: fileContext.sidecar,
    columns: fileContext.columns,
  };"""

    assert old_context in src, "Could not find buildEvalContext body"
    src = src.replace(old_context, new_context)
    print("  [FIXED] Rule engine: context now nests sidecar and includes columns")

    # Bug C: depends_on condition is inverted
    old_depends = """      if (checkResults[check.depends_on]) {"""

    new_depends = """      if (!checkResults[check.depends_on]) {"""

    assert old_depends in src, "Could not find depends_on condition"
    src = src.replace(old_depends, new_depends)
    print("  [FIXED] Rule engine: depends_on now skips when dependency failed")

    # Bug D: passed counts warnings as failures
    old_passed = """  const passed = allIssues.length === 0;"""

    new_passed = """  const passed = allIssues.filter(i => i.level === 'error').length === 0;"""

    assert old_passed in src, "Could not find passed determination"
    src = src.replace(old_passed, new_passed)
    print("  [FIXED] Rule engine: passed now only considers error-level issues")

    write_file(path, src)


def main():
    print("Fixing BIDS expression language evaluator, inheritance resolver, and rule engine...\n")

    print("1. Fixing lexer (src/lexer.ts):")
    fix_lexer()

    print("\n2. Fixing parser (src/parser.ts):")
    fix_parser()

    print("\n3. Fixing evaluator (src/evaluator.ts):")
    fix_evaluator()

    print("\n4. Fixing built-in functions (src/functions.ts):")
    fix_functions()

    print("\n5. Fixing inheritance resolver (src/inheritance.ts):")
    fix_inheritance()

    print("\n6. Fixing rule engine (src/rule_engine.ts):")
    fix_rule_engine()

    print("\nAll 19 issues fixed successfully (12 evaluator + 3 inheritance + 4 rule engine).")


if __name__ == "__main__":
    main()
