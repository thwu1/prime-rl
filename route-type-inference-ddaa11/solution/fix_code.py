#!/usr/bin/env python3

"""
Applies targeted fixes to types.ts, url.ts, and router.ts by replacing
broken implementations with correct ones via string substitution.
"""


def fix_types():
    """Fix all 6 type-level bugs in types.ts."""
    with open("/app/src/types.ts", "r") as f:
        content = f.read()

    # Bug 1: ParamKey — missing optional-with-regex handling.
    content = content.replace(
        "type ParamKey<Component> = Component extends `:${infer NameWithPattern}`\n"
        "  ? NameWithPattern extends `${infer Name}{${infer _Rest}`\n"
        "    ? Name\n"
        "    : NameWithPattern\n"
        "  : never",

        "type ParamKey<Component> = Component extends `:${infer NameWithPattern}`\n"
        "  ? NameWithPattern extends `${infer Name}{${infer Rest}`\n"
        "    ? Rest extends `${infer _Pattern}?`\n"
        "      ? `${Name}?`\n"
        "      : Name\n"
        "    : NameWithPattern\n"
        "  : never",
    )

    # Bug 2: ParamKeys — missing recursive union with ParamKeys<Rest>.
    content = content.replace(
        "export type ParamKeys<Path> = Path extends `${infer Component}/${infer Rest}`\n"
        "  ? ParamKey<Component>\n"
        "  : ParamKey<Path>",

        "export type ParamKeys<Path> = Path extends `${infer Component}/${infer Rest}`\n"
        "  ? ParamKey<Component> | ParamKeys<Rest>\n"
        "  : ParamKey<Path>",
    )

    # Bug 3: ParamKeyToRecord — missing optional parameter handling.
    content = content.replace(
        "export type ParamKeyToRecord<T extends string> = { [K in T]: string }",

        "export type ParamKeyToRecord<T extends string> = T extends `${infer R}?`\n"
        "  ? Record<R, string | undefined>\n"
        "  : { [K in T]: string }",
    )

    # Bug 4: MergePath — missing A extends '/' case and Q extends '' guard.
    content = content.replace(
        "export type MergePath<A extends string, B extends string> = B extends ''\n"
        "  ? MergePath<A, '/'>\n"
        "  : A extends ''\n"
        "    ? B\n"
        "    : A extends `${infer P}/`\n"
        "      ? B extends `/${infer Q}`\n"
        "        ? `${P}/${Q}`\n"
        "        : `${P}/${B}`\n"
        "      : B extends `/${infer Q}`\n"
        "        ? `${A}/${Q}`\n"
        "        : `${A}/${B}`",

        "export type MergePath<A extends string, B extends string> = B extends ''\n"
        "  ? MergePath<A, '/'>\n"
        "  : A extends ''\n"
        "    ? B\n"
        "    : A extends '/'\n"
        "      ? B\n"
        "      : A extends `${infer P}/`\n"
        "        ? B extends `/${infer Q}`\n"
        "          ? `${P}/${Q}`\n"
        "          : `${P}/${B}`\n"
        "        : B extends `/${infer Q}`\n"
        "          ? Q extends ''\n"
        "            ? A\n"
        "            : `${A}/${Q}`\n"
        "          : `${A}/${B}`",
    )

    # Bug 5: AddParam — missing ParamKeys<P> extends never check.
    content = content.replace(
        "export type AddParam<I, P extends string> =\n"
        "  I extends { param: infer _ }\n"
        "    ? I\n"
        "    : I & { param: UnionToIntersection<ParamKeyToRecord<ParamKeys<P>>> }",

        "export type AddParam<I, P extends string> =\n"
        "  ParamKeys<P> extends never\n"
        "    ? I\n"
        "    : I extends { param: infer _ }\n"
        "      ? I\n"
        "      : I & { param: UnionToIntersection<ParamKeyToRecord<ParamKeys<P>>> }",
    )

    # Bug 6: ExtractAllParams — missing ParamKeys extends never check.
    content = content.replace(
        "export type ExtractAllParams<Path extends string> =\n"
        "  UnionToIntersection<ParamKeyToRecord<ParamKeys<Path>>>",

        "export type ExtractAllParams<Path extends string> =\n"
        "  ParamKeys<Path> extends never\n"
        "    ? {}\n"
        "    : UnionToIntersection<ParamKeyToRecord<ParamKeys<Path>>>",
    )

    with open("/app/src/types.ts", "w") as f:
        f.write(content)
    print("Fixed types.ts: 6 type-level bugs patched")


def fix_url():
    """Fix all 3 runtime bugs in url.ts."""
    with open("/app/src/url.ts", "r") as f:
        content = f.read()

    # Bug 7: getPattern — uses lookahead regex when next is a static segment,
    # but the router matches segment-by-segment so lookahead never matches.
    # Fix: always use $ anchor regardless of next segment.
    content = content.replace(
        "    if (match[2]) {\n"
        "      return next && next[0] !== ':' && next[0] !== '*'\n"
        "        ? [label, match[1], new RegExp(`^${match[2]}(?=/${next})`)]\n"
        "        : [label, match[1], new RegExp(`^${match[2]}$`)]\n"
        "    }",

        "    if (match[2]) {\n"
        "      return [label, match[1], new RegExp(`^${match[2]}$`)]\n"
        "    }",
    )

    # Bug 8: mergePath — not variadic and missing slash-dedup at join.
    content = content.replace(
        "export const mergePath = (base: string, sub: string): string => {\n"
        "  return `${base?.[0] === '/' ? '' : '/'}${base}${\n"
        "    sub === '/' ? '' : `/${sub?.[0] === '/' ? sub.slice(1) : sub}`\n"
        "  }`\n"
        "}",

        "export const mergePath: (...paths: string[]) => string = (\n"
        "  base: string | undefined,\n"
        "  sub: string | undefined,\n"
        "  ...rest: string[]\n"
        "): string => {\n"
        "  if (rest.length) {\n"
        "    sub = mergePath(sub as string, ...rest)\n"
        "  }\n"
        "  return `${base?.[0] === '/' ? '' : '/'}${base}${\n"
        "    sub === '/' ? '' : `${base?.at(-1) === '/' ? '' : '/'}${sub?.[0] === '/' ? sub.slice(1) : sub}`\n"
        "  }`\n"
        "}",
    )

    # Bug 9: checkOptionalParameter — only handles single trailing optional.
    content = content.replace(
        "export const checkOptionalParameter = (path: string): string[] | null => {\n"
        "  if (!path.endsWith('?') || !path.includes(':')) {\n"
        "    return null\n"
        "  }\n"
        "\n"
        "  const segments = path.split('/')\n"
        "  const lastSegment = segments[segments.length - 1]\n"
        "\n"
        "  if (!lastSegment.startsWith(':')) {\n"
        "    return null\n"
        "  }\n"
        "\n"
        "  const basePath = segments.slice(0, -1).join('/')\n"
        "  const paramName = lastSegment.replace('?', '')\n"
        "\n"
        "  return [basePath, `${basePath}/${paramName}`]\n"
        "}",

        "export const checkOptionalParameter = (path: string): string[] | null => {\n"
        "  if (path.charCodeAt(path.length - 1) !== 63 || !path.includes(':')) {\n"
        "    return null\n"
        "  }\n"
        "\n"
        "  const segments = path.split('/')\n"
        "  const results: string[] = []\n"
        "  let basePath = ''\n"
        "\n"
        "  segments.forEach((segment) => {\n"
        "    if (segment !== '' && !/\\:/.test(segment)) {\n"
        "      basePath += '/' + segment\n"
        "    } else if (/\\:/.test(segment)) {\n"
        "      if (/\\?/.test(segment)) {\n"
        "        if (results.length === 0 && basePath === '') {\n"
        "          results.push('/')\n"
        "        } else {\n"
        "          results.push(basePath)\n"
        "        }\n"
        "        const optionalSegment = segment.replace('?', '')\n"
        "        basePath += '/' + optionalSegment\n"
        "        results.push(basePath)\n"
        "      } else {\n"
        "        basePath += '/' + segment\n"
        "      }\n"
        "    }\n"
        "  })\n"
        "\n"
        "  return results.filter((v, i, a) => a.indexOf(v) === i)\n"
        "}",
    )

    with open("/app/src/url.ts", "w") as f:
        f.write(content)
    print("Fixed url.ts: 3 runtime bugs patched")


def fix_router():
    """Fix the 2 wildcard-matching bugs in router.ts."""
    with open("/app/src/router.ts", "r") as f:
        content = f.read()

    # Bug 10: Wildcard length check — strict equality prevents multi-segment
    # wildcard matching. Need to allow variable-length request paths when
    # the route ends with a wildcard.
    content = content.replace(
        "      if (routeParts.length !== reqParts.length) continue",

        "      const hasWild = routeParts.length > 0 && routeParts[routeParts.length - 1] === '*'\n"
        "      if (hasWild ? reqParts.length < routeParts.length - 1 : routeParts.length !== reqParts.length) continue",
    )

    # Bug 11: Wildcard capture — only captures single segment instead of
    # joining all remaining segments with '/'.
    content = content.replace(
        "        if (pat === '*') {\n"
        "          params['*'] = reqParts[i]\n"
        "          continue\n"
        "        }",

        "        if (pat === '*') {\n"
        "          params['*'] = reqParts.slice(i).join('/')\n"
        "          break\n"
        "        }",
    )

    with open("/app/src/router.ts", "w") as f:
        f.write(content)
    print("Fixed router.ts: 2 wildcard bugs patched")


if __name__ == "__main__":
    fix_types()
    fix_url()
    fix_router()
    print("All fixes applied successfully")
