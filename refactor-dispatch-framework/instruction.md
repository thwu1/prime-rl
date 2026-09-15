The C codebase at `/app/` implements a command dispatch framework with several architectural defects that must be fixed simultaneously.

All handler functions (`handle_query`, `handle_insert`, `handle_update`, `handle_delete`, `handle_batch`) and the `handler_func_t` typedef return `void`, making error propagation impossible. `dispatch_pipeline()` cannot stop on failure because it has no way to distinguish success from error. Refactor all handler functions, `handler_func_t`, `dispatch_command()`, and `dispatch_pipeline()` to return `int` (0 for success, negative for error). Each handler must return its existing internal error code (currently assigned to `ctx->last_error`) as the function's return value. After refactoring, the pipeline must short-circuit on the first non-zero return from a handler.

`dispatch_command()` and `dispatch_pipeline()` contain a duplicated handler execution pattern (allocation mode save/restore, timing with `clock_gettime`, stats recording). Consolidate this into a single static helper function.

The `CMD_MEMORY_MODE` enum is a misnomer — it describes allocation strategy. Rename it to `CMD_ALLOC_STRATEGY` with values `CMD_ALLOC_NONE`, `CMD_ALLOC_STACK`, `CMD_ALLOC_HEAP`, `CMD_ALLOC_POOL`. Rename `cmd_memory_mode_name()` to `cmd_alloc_strategy_name()` and `cmd_memory_mode_from_name()` to `cmd_alloc_strategy_from_name()`. Rename the `mem_mode` field in `dispatch_ctx_t` to `alloc_strategy`. Update all references across the entire codebase — no occurrence of `CMD_MEMORY_MODE`, `mem_mode`, or the old function names may remain.

The statistics tracking code (`stats_init`, `stats_cleanup`, `stats_record_*`, `stats_get_*`, `stats_report`, and the static `g_stats` struct) is embedded in `dispatch.c`. Extract it into `stats.c` / `stats.h`. No stats implementation code or data should remain in `dispatch.c`.

`handlers.h` and `dispatch.h` have a circular `#include` dependency. Break this by removing `#include "dispatch.h"` from `handlers.h` and using a forward declaration of `struct dispatch_ctx` instead. `handlers.h` must compile independently without `dispatch.h`.

Add `__attribute__((warn_unused_result))` to the declarations of `dispatch_command()` and `dispatch_pipeline()` in `dispatch.h`.

Update the `Makefile` to compile and link the new `stats.c` module. Update `main.c` to use the new API (capture return values, use renamed enum and fields). All existing constants — including `FRAMEWORK_MAGIC` and handler-specific error codes — must be preserved. All code must compile cleanly with `-Wall -Wextra`.