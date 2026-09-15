#pragma once

#include "task.hpp"

namespace coro {

// Drives the given task to completion on the current thread and returns the result.
// Must correctly propagate exceptions thrown by the task.
template<typename T>
T sync_wait(task<T> t);

// Overload for void-returning tasks.
void sync_wait(task<void> t);

} // namespace coro
