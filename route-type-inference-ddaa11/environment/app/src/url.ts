
export type Pattern = readonly [string, string, RegExp | true] | '*'

export const splitPath = (path: string): string[] => {
  const paths = path.split('/')
  if (paths[0] === '') {
    paths.shift()
  }
  return paths
}

export const splitRoutingPath = (routePath: string): string[] => {
  const { groups, path } = extractGroupsFromPath(routePath)
  const paths = splitPath(path)
  return replaceGroupMarks(paths, groups)
}

const extractGroupsFromPath = (path: string): { groups: [string, string][]; path: string } => {
  const groups: [string, string][] = []
  path = path.replace(/\{[^}]+\}/g, (match, index) => {
    const mark = `@${index}`
    groups.push([mark, match])
    return mark
  })
  return { groups, path }
}

const replaceGroupMarks = (paths: string[], groups: [string, string][]): string[] => {
  for (let i = groups.length - 1; i >= 0; i--) {
    const [mark] = groups[i]
    for (let j = paths.length - 1; j >= 0; j--) {
      if (paths[j].includes(mark)) {
        paths[j] = paths[j].replace(mark, groups[i][1])
        break
      }
    }
  }
  return paths
}

export const getPattern = (label: string, next?: string): Pattern | null => {
  if (label === '*') {
    return '*'
  }
  const match = label.match(/^\:([^\{\}]+)(?:\{(.+)\})?$/)
  if (match) {
    if (match[2]) {
      return next && next[0] !== ':' && next[0] !== '*'
        ? [label, match[1], new RegExp(`^${match[2]}(?=/${next})`)]
        : [label, match[1], new RegExp(`^${match[2]}$`)]
    } else {
      return [label, match[1], true]
    }
  }
  return null
}

export const mergePath = (base: string, sub: string): string => {
  return `${base?.[0] === '/' ? '' : '/'}${base}${
    sub === '/' ? '' : `/${sub?.[0] === '/' ? sub.slice(1) : sub}`
  }`
}

export const checkOptionalParameter = (path: string): string[] | null => {
  if (!path.endsWith('?') || !path.includes(':')) {
    return null
  }

  const segments = path.split('/')
  const lastSegment = segments[segments.length - 1]

  if (!lastSegment.startsWith(':')) {
    return null
  }

  const basePath = segments.slice(0, -1).join('/')
  const paramName = lastSegment.replace('?', '')

  return [basePath, `${basePath}/${paramName}`]
}
