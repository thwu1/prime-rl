# netdaemon ABI Version Policy

## SOVERSION Rules

The project SOVERSION equals the major version number of the release.
A SOVERSION bump is required when any of the following occur:

1. A struct that is part of the public API changes layout (fields
   added, removed, reordered, or resized)
2. A public function signature changes (parameters added/removed,
   return type changed)
3. A public symbol is removed from the library

A SOVERSION bump is NOT required for:
- Adding new public symbols (backward-compatible extension)
- Changing internal implementation without affecting the ABI
- Bug fixes that don't alter the binary interface

## v2 to v3 Changes

The v2 public API defined `nd_config_t` with a field named `max_conn`
(type `int`). Review the v3 header (`src/core/ndcore.h`) to determine
whether the struct layout has changed and whether a SOVERSION bump is
warranted under the rules above.

## Symbol Export Policy

Shared libraries MUST use GNU ld version scripts to export only
symbols declared in their public header files. Internal helper
functions, even if non-static, must not appear in the dynamic symbol
table. This prevents consumers from depending on unstable internal
interfaces.

Version scripts should be named `lib<name>.map` and placed alongside
the library source in `src/<component>/`.
