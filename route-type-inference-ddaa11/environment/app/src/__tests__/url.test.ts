
import { describe, it, expect } from 'vitest'
import {
  splitPath,
  splitRoutingPath,
  getPattern,
  mergePath,
  checkOptionalParameter,
} from '../url'

describe('splitPath', () => {
  it('splits root', () => {
    expect(splitPath('/')).toStrictEqual([''])
  })

  it('splits simple path', () => {
    expect(splitPath('/hello')).toStrictEqual(['hello'])
  })

  it('splits multiple segments', () => {
    expect(splitPath('/a/b/c')).toStrictEqual(['a', 'b', 'c'])
  })
})

describe('splitRoutingPath', () => {
  it('splits root', () => {
    expect(splitRoutingPath('/')).toStrictEqual([''])
  })

  it('splits simple path', () => {
    expect(splitRoutingPath('/hello')).toStrictEqual(['hello'])
  })

  it('handles wildcard', () => {
    expect(splitRoutingPath('*')).toStrictEqual(['*'])
  })

  it('handles wildcard segments', () => {
    expect(splitRoutingPath('/wildcard-abc/*/wildcard-efg')).toStrictEqual([
      'wildcard-abc',
      '*',
      'wildcard-efg',
    ])
  })

  it('handles named params', () => {
    expect(splitRoutingPath('/map/:location/events')).toStrictEqual([
      'map',
      ':location',
      'events',
    ])
  })

  it('handles regex pattern with slashes', () => {
    expect(splitRoutingPath('/js/:location{[a-z/]+.js}')).toStrictEqual([
      'js',
      ':location{[a-z/]+.js}',
    ])
  })

  it('handles nested braces in regex', () => {
    expect(splitRoutingPath('/users/:name{[0-9a-zA-Z_-]{3,10}}')).toStrictEqual([
      'users',
      ':name{[0-9a-zA-Z_-]{3,10}}',
    ])
  })

  it('handles multiple regex params', () => {
    expect(
      splitRoutingPath('/users/:dept{\\d+}/:@name{[0-9a-zA-Z_-]{3,10}}')
    ).toStrictEqual(['users', ':dept{\\d+}', ':@name{[0-9a-zA-Z_-]{3,10}}'])
  })
})

describe('getPattern', () => {
  it('returns null for static segment', () => {
    expect(getPattern('id')).toBeNull()
  })

  it('returns null for static with next', () => {
    expect(getPattern('id', 'next')).toBeNull()
  })

  it('handles default named param', () => {
    expect(getPattern(':id')).toEqual([':id', 'id', true])
  })

  it('handles default param with next', () => {
    expect(getPattern(':id', 'next')).toEqual([':id', 'id', true])
  })

  it('handles regex param', () => {
    expect(getPattern(':id{[0-9]+}')).toEqual([':id{[0-9]+}', 'id', /^[0-9]+$/])
  })

  it('handles wildcard', () => {
    expect(getPattern('*')).toBe('*')
  })

  it('handles regex param with static next segment', () => {
    const result = getPattern(':id{[0-9]+}', 'posts')
    expect(result).toEqual([':id{[0-9]+}', 'id', /^[0-9]+$/])
  })

  it('handles regex param with param next segment', () => {
    const result = getPattern(':id{[0-9]+}', ':name')
    expect(result).toEqual([':id{[0-9]+}', 'id', /^[0-9]+$/])
  })
})

describe('mergePath', () => {
  it('base + root preserves base', () => {
    expect(mergePath('/book', '/')).toBe('/book')
  })

  it('base/ + root preserves trailing slash', () => {
    expect(mergePath('/book/', '/')).toBe('/book/')
  })

  it('basic merge', () => {
    expect(mergePath('/book', '/hey')).toBe('/book/hey')
  })

  it('base/ + /sub removes duplicate slash', () => {
    expect(mergePath('/book/', '/hey')).toBe('/book/hey')
  })

  it('preserves sub trailing slash', () => {
    expect(mergePath('/book', '/hey/')).toBe('/book/hey/')
  })

  it('base/ + sub/ removes duplicate slash', () => {
    expect(mergePath('/book/', '/hey/')).toBe('/book/hey/')
  })

  it('variadic: 3 args', () => {
    expect(mergePath('/book', 'hey', 'say')).toBe('/book/hey/say')
  })

  it('variadic: with slashes', () => {
    expect(mergePath('/book', '/hey/', '/say/')).toBe('/book/hey/say/')
  })

  it('variadic: trailing root preserves slash', () => {
    expect(mergePath('/book', '/hey/', '/say/', '/')).toBe('/book/hey/say/')
  })

  it('variadic: trailing root no trailing slash', () => {
    expect(mergePath('/book', '/hey', '/say', '/')).toBe('/book/hey/say')
  })

  it('variadic: root chain', () => {
    expect(mergePath('/', '/book', '/hey', '/say', '/')).toBe('/book/hey/say')
  })

  it('adds leading slash when missing', () => {
    expect(mergePath('book', '/')).toBe('/book')
  })

  it('no leading slash + trailing slash', () => {
    expect(mergePath('book/', '/')).toBe('/book/')
  })

  it('no leading slash + sub', () => {
    expect(mergePath('book', '/hey')).toBe('/book/hey')
  })

  it('no leading slash either', () => {
    expect(mergePath('book', 'hey')).toBe('/book/hey')
  })

  it('no leading slash + sub/', () => {
    expect(mergePath('book', 'hey/')).toBe('/book/hey/')
  })

  it('root + sub (no leading slash)', () => {
    expect(mergePath('/', 'book')).toBe('/book')
  })

  it('root + /sub', () => {
    expect(mergePath('/', '/book')).toBe('/book')
  })

  it('root + root', () => {
    expect(mergePath('/', '/')).toBe('/')
  })
})

describe('checkOptionalParameter', () => {
  it('single optional param', () => {
    expect(checkOptionalParameter('/api/animals/:type?')).toEqual([
      '/api/animals',
      '/api/animals/:type',
    ])
  })

  it('returns null: no colon', () => {
    expect(checkOptionalParameter('/api/animals/type?')).toBeNull()
  })

  it('returns null: no question mark', () => {
    expect(checkOptionalParameter('/api/animals/:type')).toBeNull()
  })

  it('returns null: no params at all', () => {
    expect(checkOptionalParameter('/api/animals')).toBeNull()
  })

  it('returns null: optional not at end', () => {
    expect(checkOptionalParameter('/api/:animals?/type')).toBeNull()
  })

  it('returns null: trailing slash after optional', () => {
    expect(checkOptionalParameter('/api/animals/:type?/')).toBeNull()
  })

  it('root optional param', () => {
    expect(checkOptionalParameter('/:optional?')).toEqual(['/', '/:optional'])
  })

  it('multiple consecutive optional params', () => {
    expect(checkOptionalParameter('/v1/leaderboard/:version?/:platform?')).toEqual([
      '/v1/leaderboard',
      '/v1/leaderboard/:version',
      '/v1/leaderboard/:version/:platform',
    ])
  })

  it('mixed required and optional params', () => {
    expect(checkOptionalParameter('/api/:version/animal/:type?')).toEqual([
      '/api/:version/animal',
      '/api/:version/animal/:type',
    ])
  })

  it('three consecutive optional params', () => {
    expect(checkOptionalParameter('/base/:a?/:b?/:c?')).toEqual([
      '/base',
      '/base/:a',
      '/base/:a/:b',
      '/base/:a/:b/:c',
    ])
  })
})
