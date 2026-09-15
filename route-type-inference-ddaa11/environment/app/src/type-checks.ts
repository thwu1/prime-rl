
// Type-level assertions — each line must compile under tsc --noEmit.
// If any type is incorrectly implemented, tsc will report a compile error.

import type {
  Expect,
  Equal,
  ParamKeys,
  ParamKeyToRecord,
  MergePath,
  AddParam,
  ExtractAllParams,
} from './types'

// ===== ParamKeys: single parameter =====
type PK1 = Expect<Equal<ParamKeys<'/users/:id'>, 'id'>>

// ===== ParamKeys: multiple parameters across segments =====
type PK2 = Expect<Equal<ParamKeys<'/users/:id/posts/:postId'>, 'id' | 'postId'>>

// ===== ParamKeys: parameter with regex constraint =====
type PK3 = Expect<Equal<ParamKeys<'/users/:id{[0-9]+}'>, 'id'>>

// ===== ParamKeys: optional parameter (no constraint) =====
type PK4 = Expect<Equal<ParamKeys<'/api/:version?'>, 'version?'>>

// ===== ParamKeys: optional parameter WITH regex constraint =====
type PK5 = Expect<Equal<ParamKeys<'/api/:version{[0-9]+}?'>, 'version?'>>

// ===== ParamKeys: static path yields never =====
type PK6 = Expect<Equal<ParamKeys<'/users/list'>, never>>

// ===== ParamKeys: wildcard yields never =====
type PK7 = Expect<Equal<ParamKeys<'/users/*'>, never>>

// ===== ParamKeys: mixed params and static segments =====
type PK8 = Expect<Equal<ParamKeys<'/api/:version/users/:id/profile'>, 'version' | 'id'>>

// ===== ParamKeys: three parameters =====
type PK9 = Expect<Equal<ParamKeys<'/a/:x/b/:y/c/:z'>, 'x' | 'y' | 'z'>>

// ===== ParamKeys: multiple params with regex constraints =====
type PK10 = Expect<Equal<ParamKeys<'/posts/:id{[0-9]+}/comments/:cid{[a-z]+}'>, 'id' | 'cid'>>

// ===== ParamKeys: required + optional in same path =====
type PK11 = Expect<Equal<ParamKeys<'/api/:version/items/:itemId?'>, 'version' | 'itemId?'>>

// ===== ParamKeys: deep nested with regex + optional combo =====
type PK12 = Expect<Equal<ParamKeys<'/a/:x/b/:y{\\d+}/c/:z?'>, 'x' | 'y' | 'z?'>>

// ===== ParamKeys: multiple regex-constrained with trailing optional =====
type PK13 = Expect<Equal<ParamKeys<'/:a{[a-z]+}/:b{[0-9]+}?'>, 'a' | 'b?'>>

// ===== ParamKeyToRecord: required parameter =====
type PKR1 = Expect<Equal<ParamKeyToRecord<'id'>, { id: string }>>

// ===== ParamKeyToRecord: optional parameter =====
type PKR2 = Expect<Equal<ParamKeyToRecord<'version?'>, Record<'version', string | undefined>>>

// ===== ParamKeyToRecord: another required parameter =====
type PKR3 = Expect<Equal<ParamKeyToRecord<'userId'>, { userId: string }>>

// ===== MergePath: basic merge =====
type MP1 = Expect<Equal<MergePath<'/api', '/book'>, '/api/book'>>

// ===== MergePath: trailing slash on base =====
type MP2 = Expect<Equal<MergePath<'/api/', '/book'>, '/api/book'>>

// ===== MergePath: base with trailing slash + root =====
type MP3 = Expect<Equal<MergePath<'/api/', '/'>, '/api/'>>

// ===== MergePath: base without trailing slash + root =====
type MP4 = Expect<Equal<MergePath<'/api', '/'>, '/api'>>

// ===== MergePath: root + empty =====
type MP5 = Expect<Equal<MergePath<'/', ''>, '/'>>

// ===== MergePath: empty + root =====
type MP6 = Expect<Equal<MergePath<'', '/'>, '/'>>

// ===== MergePath: root + root =====
type MP7 = Expect<Equal<MergePath<'/', '/'>, '/'>>

// ===== MergePath: empty + empty =====
type MP8 = Expect<Equal<MergePath<'', ''>, '/'>>

// ===== MergePath: root + deep sub-path =====
type MP9 = Expect<Equal<MergePath<'/', '/api/v1'>, '/api/v1'>>

// ===== MergePath: trailing slashes normalized on both sides =====
type MP10 = Expect<Equal<MergePath<'/api/', '/v1/'>, '/api/v1/'>>

// ===== AddParam: static path — no param added =====
type AP1 = Expect<Equal<AddParam<{}, '/users'>, {}>>

// ===== AddParam: single param added =====
type AP2 = Expect<Equal<
  AddParam<{}, '/users/:id'>,
  {} & { param: { id: string } }
>>

// ===== AddParam: existing param preserved =====
type AP3 = Expect<Equal<
  AddParam<{ param: { existingId: string } }, '/users/:id'>,
  { param: { existingId: string } }
>>

// ===== AddParam: multiple params produce intersection =====
type AP4 = Expect<Equal<
  AddParam<{}, '/users/:id/posts/:postId'>,
  {} & { param: { id: string } & { postId: string } }
>>

// ===== AddParam: optional param =====
type AP5 = Expect<Equal<
  AddParam<{}, '/api/:version?'>,
  {} & { param: Record<'version', string | undefined> }
>>

// ===== AddParam: regex-constrained param =====
type AP6 = Expect<Equal<
  AddParam<{}, '/posts/:id{[0-9]+}'>,
  {} & { param: { id: string } }
>>

// ===== ExtractAllParams: single required param =====
type EAP1 = Expect<Equal<ExtractAllParams<'/users/:id'>, { id: string }>>

// ===== ExtractAllParams: static path yields empty object =====
type EAP2 = Expect<Equal<ExtractAllParams<'/users/list'>, {}>>

// ===== ExtractAllParams: multiple params produce intersection =====
type EAP3 = Expect<Equal<ExtractAllParams<'/users/:id/posts/:postId'>, { id: string } & { postId: string }>>

// ===== ExtractAllParams: optional param =====
type EAP4 = Expect<Equal<ExtractAllParams<'/api/:version?'>, Record<'version', string | undefined>>>

// ===== ExtractAllParams: regex-constrained + optional combo =====
type EAP5 = Expect<Equal<
  ExtractAllParams<'/api/:ver{[0-9]+}/:name?'>,
  { ver: string } & Record<'name', string | undefined>
>>
