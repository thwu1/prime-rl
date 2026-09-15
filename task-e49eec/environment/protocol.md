# Pest Control Binary Protocol Specification

## Overview

The Pest Control system manages animal populations across numbered sites. Three roles participate:

- **Site visitors** (clients): connect to your server and report observed animal populations via `SiteVisit` messages.
- **Your server**: receives site visit reports, connects to the Authority Server to learn target population ranges, and creates/deletes population control policies accordingly.
- **Authority Server**: maintains target population ranges and policies for each site. Runs at `localhost:20547`.

## Data types

### `u32`

Unsigned 32-bit integer in network byte order (big endian).

    Type | Hex bytes       | Value
    ----------------------------------------
    u32  | 00 00 00 20     | 32
    u32  | 00 00 12 45     | 4677
    u32  | a6 a9 b5 67     | 2796139879

### `str`

Length-prefixed ASCII string: a `u32` containing the byte length, followed by that many bytes of ASCII character data.

    Type | Hex bytes                            | Value
    --------------------------------------------------------
    str  | 00 00 00 00                          | ""
    str  | 00 00 00 03 66 6f 6f                 | "foo"
    str  | 00 00 00 08 45 6C 62 65 72 65 74 68  | "Elbereth"

It is an error for the string's declared length to exceed the containing message boundary.

### Arrays

Arrays are represented as a `u32` element count followed by that many concatenated elements.

Example type: `[{species: str, count: u32}, ...]`

Example encoding of `[{species:"rat",count:10}, {species:"dog",count:15}]`:

    00 00 00 02             (2 elements)
    00 00 00 03 72 61 74    species: "rat"
    00 00 00 0a             count: 10
    00 00 00 03 64 6f 67    species: "dog"
    00 00 00 0f             count: 15

## Message framing

Every message has this structure:

    [type: 1 byte] [length: u32] [content: variable] [checksum: 1 byte]

- **type**: a single byte identifying the message type.
- **length**: a `u32` giving the total message size in bytes (including the type byte, length field, content, and checksum byte).
- **content**: the message-specific fields.
- **checksum**: a single byte chosen so that all bytes of the entire message sum to 0 (modulo 256).

### Checksum computation

Sum all bytes of the message (type + length + content). The checksum byte is `(256 - (sum % 256)) % 256`.

It is an error to send a message with an incorrect checksum. It is an error for the content to be shorter or longer than implied by the length field.

## Message types

### `0x50`: Hello

Fields:
- `protocol: str` (must be `"pestcontrol"`)
- `version: u32` (must be `1`)

Both sides must send Hello as the **first message** of every connection. The client sends Hello first; the server responds with Hello. It is an error for the first message to be any other type, or for `protocol`/`version` to have wrong values.

Example (25 bytes):

    50                      Hello {
    00 00 00 19               length: 25
    00 00 00 0b               protocol: (11 bytes)
    70 65 73 74 63 6f 6e        "pestcon
    74 72 6f 6c                  trol"
    00 00 00 01               version: 1
    ce                        checksum: 0xce
                            }

### `0x51`: Error

Fields:
- `message: str`

Sent when a protocol error is detected. The sender may optionally close the connection after sending.

Example (13 bytes):

    51                      Error {
    00 00 00 0d               length: 13
    00 00 00 03               message: "bad"
    62 61 64
    78                        checksum: 0x78
                            }

### `0x52`: OK

No fields. Sent by the Authority Server to acknowledge a successful `DeletePolicy`.

Example (6 bytes):

    52                      OK {
    00 00 00 06               length: 6
    a8                        checksum: 0xa8
                            }

### `0x53`: DialAuthority

Fields:
- `site: u32`

Sent by your server to the Authority Server as the **second message** (after Hello) to connect to the authority for a specific site. The Authority Server responds with `TargetPopulations`. Each connection to the Authority Server is bound to one site; to manage a different site, open a new connection.

Example (10 bytes):

    53                      DialAuthority {
    00 00 00 0a               length: 10
    00 00 30 39               site: 12345
    3a                        checksum: 0x3a
                            }

### `0x54`: TargetPopulations

Fields:
- `site: u32`
- `populations: [{species: str, min: u32, max: u32}, ...]`

Sent by the Authority Server in response to `DialAuthority`. Contains the target population ranges for each controlled species at the given site. Target populations for a site are static and may be cached indefinitely.

Example (44 bytes):

    54                      TargetPopulations {
    00 00 00 2c               length: 44
    00 00 30 39               site: 12345
    00 00 00 02               populations: (2 entries) [
                                {
    00 00 00 03 64 6f 67          species: "dog"
    00 00 00 01                   min: 1
    00 00 00 03                   max: 3
                                },
                                {
    00 00 00 03 72 61 74          species: "rat"
    00 00 00 00                   min: 0
    00 00 00 0a                   max: 10
                                },
                              ]
    80                        checksum: 0x80
                            }

### `0x55`: CreatePolicy

Fields:
- `species: str`
- `action: byte` (`0x90` = cull, `0xa0` = conserve; anything else is an error)

Sent by your server to the Authority to create a new policy. The Authority responds with `PolicyResult`.

Example (14 bytes):

    55                      CreatePolicy {
    00 00 00 0e               length: 14
    00 00 00 03 64 6f 67      species: "dog"
    a0                        action: conserve
    c0                        checksum: 0xc0
                            }

### `0x56`: DeletePolicy

Fields:
- `policy: u32`

Sent by your server to the Authority to delete an existing policy. The `policy` field must be a policy ID previously returned in a `PolicyResult` for the current site. The Authority responds with `OK`. It is an error to delete a non-existent policy.

Example (10 bytes):

    56                      DeletePolicy {
    00 00 00 0a               length: 10
    00 00 00 7b               policy: 123
    25                        checksum: 0x25
                            }

### `0x57`: PolicyResult

Fields:
- `policy: u32`

Sent by the Authority in response to a valid `CreatePolicy`. Contains the assigned policy ID.

Example (10 bytes):

    57                      PolicyResult {
    00 00 00 0a               length: 10
    00 00 00 7b               policy: 123
    24                        checksum: 0x24
                            }

### `0x58`: SiteVisit

Fields:
- `site: u32`
- `populations: [{species: str, count: u32}, ...]`

Sent by a client to your server reporting observed populations at a site. Your server must **not** send any response to valid `SiteVisit` messages.

It is an error for the `populations` array to contain multiple **conflicting** counts for the same species (different count values). Non-conflicting duplicates (same species, same count) are allowed.

Example (36 bytes):

    58                      SiteVisit {
    00 00 00 24               length: 36
    00 00 30 39               site: 12345
    00 00 00 02               populations: (2 entries) [
                                {
    00 00 00 03 64 6f 67          species: "dog"
    00 00 00 01                   count: 1
                                },
                                {
    00 00 00 03 72 61 74          species: "rat"
    00 00 00 05                   count: 5
                                },
                              ]
    8c                        checksum: 0x8c
                            }

## Policy rules

When your server receives a `SiteVisit`, it must:

1. **Connect to the authority** for the specified site (if not already connected). Send `Hello`, receive `Hello`, send `DialAuthority`, receive `TargetPopulations`.

2. **Determine the desired policy** for each species in the target populations:
   - If the observed count `c < min`: the species needs a **conserve** policy.
   - If `c > max`: the species needs a **cull** policy.
   - If `min <= c <= max`: the species needs **no policy**.
   - Species **not mentioned** in the `SiteVisit` have an observed count of **zero**.
   - Species **observed** but **not in the target populations** are uncontrolled — no policy action.

3. **Reconcile** the current policies (tracked by your server via `PolicyResult` IDs) with the desired state by sending `CreatePolicy` and `DeletePolicy` messages.

4. The policies may be transiently incorrect while reconciliation is in progress, but must **settle to the correct state** matching the **most recent `SiteVisit`**. The settled state **may not contain more than one policy per species**.

## Session examples

### Client connecting to your server

    Client -> Server: Hello
    Server -> Client: Hello
    Client -> Server: SiteVisit{site:12345, populations:[{species:"long-tailed rat", count:20}]}

### Your server connecting to the Authority Server

    Your Server -> Authority: Hello
    Authority -> Your Server: Hello
    Your Server -> Authority: DialAuthority{site:12345}
    Authority -> Your Server: TargetPopulations{site:12345, populations:[{species:"long-tailed rat", min:0, max:10}]}
    Your Server -> Authority: CreatePolicy{species:"long-tailed rat", action:cull}
    Authority -> Your Server: PolicyResult{policy:1}

## Additional requirements

- One client may submit site visits for multiple sites.
- Multiple clients may submit visits for the same site concurrently. Your server must handle ordering consistently.
- Policy IDs are site-scoped; different sites may reuse the same numeric ID for different policies.
- Target populations for a given site are static. You may cache them.
