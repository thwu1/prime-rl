
import { mergePath, checkOptionalParameter, splitRoutingPath, getPattern, type Pattern } from './url'

type HandlerFn = (ctx: { req: { param: Record<string, string> } }) => string

interface StoredRoute {
  method: string
  path: string
  segments: string[]
  patterns: (Pattern | null)[]
  handler: HandlerFn
}

export class PatternRouter {
  private basePath: string
  private routes: StoredRoute[] = []

  constructor(basePath: string = '') {
    this.basePath = basePath
  }

  on(method: string, path: string, handler: HandlerFn): this {
    const fullPath = this.basePath ? mergePath(this.basePath, path) : path
    const expanded = checkOptionalParameter(fullPath)
    const paths = expanded ?? [fullPath]

    for (const p of paths) {
      const segments = splitRoutingPath(p)
      const patterns: (Pattern | null)[] = []
      for (let i = 0; i < segments.length; i++) {
        patterns.push(getPattern(segments[i], segments[i + 1]))
      }
      this.routes.push({ method, path: p, segments, patterns, handler })
    }
    return this
  }

  match(method: string, requestPath: string): { handler: HandlerFn; params: Record<string, string> } | null {
    const reqParts = requestPath.split('/').filter(s => s !== '')

    for (const route of this.routes) {
      if (route.method !== method && route.method !== 'ALL') continue

      const routeParts = route.segments.filter(s => s !== '')

      if (routeParts.length !== reqParts.length) continue

      const params: Record<string, string> = {}
      let matched = true

      for (let i = 0; i < routeParts.length; i++) {
        const pat = route.patterns[i]

        if (pat === '*') {
          params['*'] = reqParts[i]
          continue
        }

        if (pat === null) {
          if (routeParts[i] !== reqParts[i]) {
            matched = false
            break
          }
          continue
        }

        const [, paramName, constraint] = pat as [string, string, RegExp | true]

        if (constraint === true) {
          params[paramName] = reqParts[i]
        } else {
          if (!(constraint as RegExp).test(reqParts[i])) {
            matched = false
            break
          }
          params[paramName] = reqParts[i]
        }
      }

      if (matched) {
        return { handler: route.handler, params }
      }
    }
    return null
  }
}
