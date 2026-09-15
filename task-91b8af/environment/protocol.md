# Pest Control Protocol Specification

## Overview

A pest control coordination system manages animal populations across multiple sites. The system has three components:

1. **Site visitors** (clients) — connect to your server over TCP, reporting observed animal populations at each site.
2. **Your coordination server** — accepts site visitor connections, connects to the Authority Server to manage policies.
3. **Authority Server** — a central service (TCP `127.0.0.1:20547`) that maintains target population ranges and population control policies for each site.

Your server receives `SiteVisit` messages from clients, compares observed populations against the authority's target ranges, and creates or deletes policies on the authority accordingly.

## Data Types

The protocol uses a **binary data format** with the following primitive types:

### `u32`

An unsigned 32-bit integer in network byte-order (big endian).

    Type | Hex data    | Value
    -------------------------------
    u32  | 00 00 00 20 |         32
    u32  | 00 00 12 45 |       4677
    u32  | a6 a9 b5 67 | 2796139879

### `str`

A string in **length-prefixed** format: a `u32` containing the string's length, followed by that many bytes of ASCII character codes.

It is an error for the string's specified length to go beyond the length of the containing message.

    Type | Hex data                            | Value
    -------------------------------------------------------
    str  | 00 00 00 00                         | ""
    str  | 00 00 00 03 66 6f 6f                | "foo"
    str  | 00 00 00 08 45 6C 62 65 72 65 74 68 | "Elbereth"

### Arrays

Arrays are represented with a `u32` defining the **number of elements**, followed by that many elements concatenated together.

Example type: `[{species: str, count: u32}, ...]`

    Hexadecimal:            Decoded:
    00 00 00 02             (length 2) [
                              {
    00 00 00 03 72 61 74        species: (length 3) "rat",
    00 00 00 0a                 count: 10,
                              },
                              {
    00 00 00 03 64 6f 67        species: (length 3) "dog",
    00 00 00 0f                 count: 15
                              },
                            ]

## Checksum

The bytes in each message must **sum to 0** (modulo 256). This is achieved by setting the checksum byte (the last byte of the message) to the appropriate value.

For example, if the bytes of a message (excluding the checksum byte) sum to 254, then the checksum byte must be `0x02`.

It is an error to send a message with an incorrect checksum.

## Concepts

### Sites

A *site* is a physical location identified by a unique `u32` site ID.

### Species

A *species* is a type of animal identified by a `str`. Species names are **opaque string data** — "long-tailed rat" and "common long-tailed rat" are two different species.

### Policies

A *policy* advises the authority to either *conserve* or *cull* a particular species at a particular site. Each policy at a given site is identified by a unique `u32` policy ID. Policy IDs are only applicable **within a given site** and are never reused after deletion.

## Message Format

Each message consists of:

1. **Type** — a single byte indicating the message type
2. **Length** — a `u32` containing the message's **total length** in bytes (including type, length, content, and checksum)
3. **Content** — message-specific fields
4. **Checksum** — a single byte ensuring all message bytes sum to 0 (mod 256)

Responses must always come **in the same order** as the corresponding requests.

It is an error for the content to exceed or fall short of the message's specified length.

## Message Types

### `0x50`: Hello

Fields:

 - `protocol: str` (must be "`pestcontrol`")
 - `version: u32` (must be `1`)

This message must be sent by each side as the **first message of every session**. It is an error to send any other values for protocol or version. It is an error for the first message to be of a type other than Hello.

    Hexadecimal:    Decoded:
    50              Hello{
    00 00 00 19       (length 25)
    00 00 00 0b       protocol: (length 11)
    70 65 73 74        "pest
    63 6f 6e 74         cont
    72 6f 6c            rol"
    00 00 00 01       version: 1
    ce                (checksum 0xce)
                    }

### `0x51`: Error

Fields:

 - `message: str`

Sent when an error condition is detected. The sender may optionally close the connection.

    Hexadecimal:    Decoded:
    51              Error{
    00 00 00 0d       (length 13)
    00 00 00 03       message: (length 3)
    62 61 64           "bad",
    78                (checksum 0x78)
                    }

### `0x52`: OK

No fields. Sent by the Authority Server as acknowledgment of a valid `DeletePolicy` message.

    Hexadecimal:    Decoded:
    52              OK{
    00 00 00 06       (length 6)
    a8                (checksum 0xa8)
                    }

### `0x53`: DialAuthority

Fields:

 - `site: u32`

Sent by your server to the Authority Server to connect to a particular site's authority. This must be the second message you send (after Hello). The Authority Server responds with `TargetPopulations`.

Once dialed, the connection remains bound to that authority until closed. To reach a different authority, open a new connection.

    Hexadecimal:    Decoded:
    53              DialAuthority{
    00 00 00 0a       (length 10)
    00 00 30 39       site: 12345,
    3a                (checksum 0x3a)
                    }

### `0x54`: TargetPopulations

Fields:

 - `site: u32`
 - `populations: [{species: str, min: u32, max: u32}, ...]`

Sent by the Authority Server in response to `DialAuthority`. Contains the target population range for each controlled species at the site. The target populations for a site are static and may be cached indefinitely.

    Hexadecimal:    Decoded:
    54              TargetPopulations{
    00 00 00 2c       (length 44)
    00 00 30 39       site: 12345,
    00 00 00 02       populations: (length 2) [
                        {
    00 00 00 03           species: (length 3)
    64 6f 67                "dog",
    00 00 00 01           min: 1,
    00 00 00 03           max: 3,
                        },
                        {
    00 00 00 03           species: (length 3)
    72 61 74                "rat",
    00 00 00 00           min: 0,
    00 00 00 0a           max: 10,
                        },
                      ],
    80                (checksum 0x80)
                    }

### `0x55`: CreatePolicy

Fields:

 - `species: str`
 - `action: byte` (`0x90` = cull, `0xa0` = conserve; anything else is an error)

Sent by your server to the Authority Server to create a new policy. The Authority Server responds with `PolicyResult`.

    Hexadecimal:    Decoded:
    55              CreatePolicy{
    00 00 00 0e       (length 14)
    00 00 00 03       species: (length 3)
    64 6f 67            "dog",
    a0                action: conserve,
    c0                (checksum 0xc0)
                    }

### `0x56`: DeletePolicy

Fields:

 - `policy: u32`

Sent by your server to the Authority Server to delete an existing policy by its ID. It is an error to delete a non-existent policy. The Authority Server responds with `OK`.

    Hexadecimal:    Decoded:
    56              DeletePolicy{
    00 00 00 0a       (length 10)
    00 00 00 7b       policy: 123,
    25                (checksum 0x25)
                    }

### `0x57`: PolicyResult

Fields:

 - `policy: u32`

Sent by the Authority Server in response to `CreatePolicy`, containing the assigned policy ID.

    Hexadecimal:    Decoded:
    57              PolicyResult{
    00 00 00 0a       (length 10)
    00 00 00 7b       policy: 123,
    24                (checksum 0x24)
                    }

### `0x58`: SiteVisit

Fields:

 - `site: u32`
 - `populations: [{species: str, count: u32}, ...]`

Sent by a site visitor client to your server reporting the observed population at a site. It is an error for the populations to contain multiple **conflicting** counts for the same species (but non-conflicting duplicates are allowed).

Your server must not send any response to valid `SiteVisit` messages.

    Hexadecimal:    Decoded:
    58              SiteVisit{
    00 00 00 24       (length 36)
    00 00 30 39       site: 12345,
    00 00 00 02       populations: (length 2) [
                        {
    00 00 00 03           species: (length 3)
    64 6f 67                "dog",
    00 00 00 01           count: 1,
                        },
                        {
    00 00 00 03           species: (length 3)
    72 61 74                "rat",
    00 00 00 05            count: 5,
                        },
                      ],
    8c                (checksum 0x8c)
                    }

## Policy Rules

When you receive a `SiteVisit`, connect to the Authority Server (if not already connected for that site) and use `DialAuthority` to obtain the `TargetPopulations`.

For each controlled species, determine whether the observed count `c` is:
- **Within range**: `min <= c <= max` — no policy needed
- **Too low**: `c < min` — a **conserve** policy is needed
- **Too high**: `c > max` — a **cull** policy is needed

Where a species is **not present** in the `SiteVisit`, it means there were **zero animals observed**. Where a species is observed but **not present** in the `TargetPopulations`, the authority does not control that species — advise **no policy**.

Send `CreatePolicy` and `DeletePolicy` messages to make the policies match the desired state based on the **most recent site visit**. You must track which policies exist (by policy ID) to adjust them correctly.

The settled policy state **may not contain more than one policy for any given species**, even if they are duplicates. Transient incorrect states during active reconciliation are acceptable.

## Example: Site Visitor Session

"`-->`" = messages from your server to client; "`<--`" = messages from client to your server.

    <-- Hello{protocol:"pestcontrol", version:1}
    --> Hello{protocol:"pestcontrol", version:1}
    <-- SiteVisit{site:12345, populations:[{species:"long-tailed rat", count:20}]}

## Example: Authority Server Session

"`-->`" = messages from Authority Server to your server; "`<--`" = messages from your server to Authority Server.

    <-- Hello{protocol:"pestcontrol", version:1}
    --> Hello{protocol:"pestcontrol", version:1}
    <-- DialAuthority{site:12345}
    --> TargetPopulations{site:12345, populations:[{species:"long-tailed rat", min:0, max:10}]}
    <-- CreatePolicy{species:"long-tailed rat", action:cull}
    --> PolicyResult{policy:123}

(20 long-tailed rats observed, target range [0,10], so a cull policy is created.)

## Other Requirements

- Accept site visitor connections over TCP
- One client can submit site visits for multiple sites
- Multiple clients can submit site visits for the same site
- Handle concurrent connections gracefully
