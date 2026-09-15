
import { describe, it, expect } from 'vitest'
import { PatternRouter } from '../router'

describe('PatternRouter', () => {
  describe('static routes', () => {
    it('matches exact static path', () => {
      const router = new PatternRouter()
      router.on('GET', '/hello', () => 'hello')
      const result = router.match('GET', '/hello')
      expect(result).not.toBeNull()
      expect(result!.params).toEqual({})
    })

    it('returns null for non-matching path', () => {
      const router = new PatternRouter()
      router.on('GET', '/hello', () => 'hello')
      expect(router.match('GET', '/world')).toBeNull()
    })

    it('matches correct HTTP method', () => {
      const router = new PatternRouter()
      router.on('POST', '/submit', () => 'post')
      expect(router.match('GET', '/submit')).toBeNull()
      expect(router.match('POST', '/submit')).not.toBeNull()
    })

    it('ALL method matches any request method', () => {
      const router = new PatternRouter()
      router.on('ALL', '/any', () => 'all')
      expect(router.match('GET', '/any')).not.toBeNull()
      expect(router.match('PUT', '/any')).not.toBeNull()
      expect(router.match('DELETE', '/any')).not.toBeNull()
    })

    it('matches multi-segment static path', () => {
      const router = new PatternRouter()
      router.on('GET', '/api/v1/health', () => 'ok')
      expect(router.match('GET', '/api/v1/health')).not.toBeNull()
      expect(router.match('GET', '/api/v2/health')).toBeNull()
    })
  })

  describe('named parameters', () => {
    it('extracts single named parameter', () => {
      const router = new PatternRouter()
      router.on('GET', '/users/:id', () => 'user')
      const result = router.match('GET', '/users/42')
      expect(result).not.toBeNull()
      expect(result!.params).toEqual({ id: '42' })
    })

    it('extracts multiple named parameters', () => {
      const router = new PatternRouter()
      router.on('GET', '/users/:userId/posts/:postId', () => 'post')
      const result = router.match('GET', '/users/5/posts/99')
      expect(result).not.toBeNull()
      expect(result!.params).toEqual({ userId: '5', postId: '99' })
    })
  })

  describe('regex constrained parameters', () => {
    it('matches when regex constraint is satisfied', () => {
      const router = new PatternRouter()
      router.on('GET', '/items/:id{[0-9]+}', () => 'item')
      const result = router.match('GET', '/items/42')
      expect(result).not.toBeNull()
      expect(result!.params).toEqual({ id: '42' })
    })

    it('rejects when regex constraint is not satisfied', () => {
      const router = new PatternRouter()
      router.on('GET', '/items/:id{[0-9]+}', () => 'item')
      expect(router.match('GET', '/items/abc')).toBeNull()
    })

    it('matches regex param followed by static segment', () => {
      const router = new PatternRouter()
      router.on('GET', '/users/:id{[0-9]+}/posts', () => 'posts')
      const result = router.match('GET', '/users/42/posts')
      expect(result).not.toBeNull()
      expect(result!.params).toEqual({ id: '42' })
    })

    it('rejects regex param followed by static when constraint fails', () => {
      const router = new PatternRouter()
      router.on('GET', '/users/:id{[0-9]+}/posts', () => 'posts')
      expect(router.match('GET', '/users/abc/posts')).toBeNull()
    })
  })

  describe('wildcard routes', () => {
    it('matches wildcard with single trailing segment', () => {
      const router = new PatternRouter()
      router.on('GET', '/files/*', () => 'file')
      const result = router.match('GET', '/files/readme.md')
      expect(result).not.toBeNull()
      expect(result!.params).toEqual({ '*': 'readme.md' })
    })

    it('matches wildcard capturing multiple trailing segments', () => {
      const router = new PatternRouter()
      router.on('GET', '/files/*', () => 'file')
      const result = router.match('GET', '/files/path/to/file.txt')
      expect(result).not.toBeNull()
      expect(result!.params).toEqual({ '*': 'path/to/file.txt' })
    })

    it('matches wildcard at deeper nesting', () => {
      const router = new PatternRouter()
      router.on('GET', '/api/v1/proxy/*', () => 'proxy')
      const result = router.match('GET', '/api/v1/proxy/service/endpoint')
      expect(result).not.toBeNull()
      expect(result!.params).toEqual({ '*': 'service/endpoint' })
    })

    it('matches root wildcard', () => {
      const router = new PatternRouter()
      router.on('GET', '/*', () => 'catch-all')
      const result = router.match('GET', '/any/path/here')
      expect(result).not.toBeNull()
      expect(result!.params).toEqual({ '*': 'any/path/here' })
    })
  })

  describe('optional parameters', () => {
    it('matches with optional param present', () => {
      const router = new PatternRouter()
      router.on('GET', '/api/animals/:type?', () => 'animals')
      const result = router.match('GET', '/api/animals/dog')
      expect(result).not.toBeNull()
      expect(result!.params).toEqual({ type: 'dog' })
    })

    it('matches with optional param absent', () => {
      const router = new PatternRouter()
      router.on('GET', '/api/animals/:type?', () => 'animals')
      const result = router.match('GET', '/api/animals')
      expect(result).not.toBeNull()
      expect(result!.params).toEqual({})
    })

    it('handles multiple consecutive optional params — all present', () => {
      const router = new PatternRouter()
      router.on('GET', '/v1/data/:version?/:format?', () => 'data')
      const result = router.match('GET', '/v1/data/v2/json')
      expect(result).not.toBeNull()
      expect(result!.params).toEqual({ version: 'v2', format: 'json' })
    })

    it('handles multiple consecutive optional params — first only', () => {
      const router = new PatternRouter()
      router.on('GET', '/v1/data/:version?/:format?', () => 'data')
      const result = router.match('GET', '/v1/data/v2')
      expect(result).not.toBeNull()
      expect(result!.params).toEqual({ version: 'v2' })
    })

    it('handles multiple consecutive optional params — none present', () => {
      const router = new PatternRouter()
      router.on('GET', '/v1/data/:version?/:format?', () => 'data')
      const result = router.match('GET', '/v1/data')
      expect(result).not.toBeNull()
      expect(result!.params).toEqual({})
    })
  })

  describe('basePath composition', () => {
    it('prepends basePath to registered routes', () => {
      const router = new PatternRouter('/api/v1')
      router.on('GET', '/users', () => 'users')
      expect(router.match('GET', '/api/v1/users')).not.toBeNull()
      expect(router.match('GET', '/users')).toBeNull()
    })

    it('basePath with trailing slash normalizes paths', () => {
      const router = new PatternRouter('/api/')
      router.on('GET', '/users/:id', () => 'user')
      const result = router.match('GET', '/api/users/42')
      expect(result).not.toBeNull()
      expect(result!.params).toEqual({ id: '42' })
    })

    it('basePath with parameterized sub-path', () => {
      const router = new PatternRouter('/api')
      router.on('GET', '/users/:id', () => 'user')
      const result = router.match('GET', '/api/users/42')
      expect(result).not.toBeNull()
      expect(result!.params).toEqual({ id: '42' })
    })
  })

  describe('chaining', () => {
    it('on() returns router for chaining', () => {
      const router = new PatternRouter()
      const result = router
        .on('GET', '/a', () => 'a')
        .on('POST', '/b', () => 'b')
      expect(result).toBe(router)
    })
  })
})
