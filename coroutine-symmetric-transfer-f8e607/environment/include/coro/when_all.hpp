#pragma once

#include "task.hpp"
#include <tuple>

namespace coro {

// Awaits all provided tasks and returns their results collected into a tuple.
// If any task throws an exception, it propagates to the awaiting coroutine.
// Tasks are evaluated in order.
template<typename... Ts>
task<std::tuple<Ts...>> when_all(task<Ts>... tasks);

} // namespace coro
