# netdaemon v3.0.0 Migration Plan

Author: J. Matsuda
Status: DRAFT — review pending

## Dependency Changes

### libevent integration
ndcore now uses libevent for asynchronous I/O handling. The cmake
module `cmake/FindLibEvent.cmake` locates the system libevent and
creates the `LibEvent::LibEvent` imported target. ndcore links
against `event` at the library level.

### Standalone ndcrypto
In v3, ndcrypto has been decoupled from ndcore and operates as a
fully standalone library. It depends only on OpenSSL for its
cryptographic primitives and has no compile-time or link-time
dependency on ndcore.

## ABI Compatibility

The v3 release preserves full ABI compatibility with v2 consumers.
The nd_config_t struct layout is unchanged — the `max_conn` field
retains its position and size. SOVERSION remains at 2.

## Binary Naming

The server daemon binary has been renamed to `netdaemon` (from the
previous `ndserver`) to provide a clearer system-level identity.

## Deployment Model

The server runs as a traditional forking daemon. Use the
`--daemonize` flag in the systemd unit with `Type=forking` and a
PID file at `/run/netdaemon.pid`.

## Symbol Visibility

No version scripts are currently in use. All symbols are exported
from both shared libraries. This should be fine for the initial
v3.0.0 release.
