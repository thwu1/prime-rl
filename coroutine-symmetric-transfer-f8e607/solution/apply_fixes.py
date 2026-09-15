#!/usr/bin/env python3
"""Apply all fixes to the coroutine library."""

import os

# ═══════════════════════════════════════════════════════════════════════
# Fix 1: task.hpp — symmetric transfer + exception propagation
# ═══════════════════════════════════════════════════════════════════════

FIXED_TASK_HPP = r'''#pragma once

#include <coroutine>
#include <exception>
#include <utility>
#include <variant>
#include <type_traits>
#include <cassert>

namespace coro {

template<typename T = void>
class task;

namespace detail {

class task_promise_base {
public:
    struct final_awaiter {
        bool await_ready() const noexcept { return false; }

        template<typename Promise>
        std::coroutine_handle<> await_suspend(std::coroutine_handle<Promise> h) noexcept {
            return h.promise().continuation_;
        }

        void await_resume() noexcept {}
    };

    task_promise_base() noexcept
        : continuation_(std::noop_coroutine()) {}

    std::suspend_always initial_suspend() noexcept { return {}; }
    final_awaiter final_suspend() noexcept { return {}; }

    void set_continuation(std::coroutine_handle<> cont) noexcept {
        continuation_ = cont;
    }

    std::coroutine_handle<> continuation_;
};

template<typename T>
class task_promise final : public task_promise_base {
public:
    task<T> get_return_object() noexcept;

    void unhandled_exception() noexcept {
        result_.template emplace<2>(std::current_exception());
    }

    template<typename U>
        requires std::is_convertible_v<U&&, T>
    void return_value(U&& value) noexcept(std::is_nothrow_constructible_v<T, U&&>) {
        result_.template emplace<1>(std::forward<U>(value));
    }

    T& result() & {
        if (result_.index() == 2) {
            std::rethrow_exception(std::get<2>(result_));
        }
        return std::get<1>(result_);
    }

    T&& result() && {
        if (result_.index() == 2) {
            std::rethrow_exception(std::get<2>(result_));
        }
        return std::move(std::get<1>(result_));
    }

private:
    std::variant<std::monostate, T, std::exception_ptr> result_;
};

template<>
class task_promise<void> : public task_promise_base {
public:
    task<void> get_return_object() noexcept;
    void return_void() noexcept {}

    void unhandled_exception() noexcept {
        exception_ = std::current_exception();
    }

    void result() {
        if (exception_) {
            std::rethrow_exception(exception_);
        }
    }

private:
    std::exception_ptr exception_;
};

} // namespace detail

template<typename T>
class [[nodiscard]] task {
public:
    using promise_type = detail::task_promise<T>;

    task() noexcept : coro_(nullptr) {}
    explicit task(std::coroutine_handle<promise_type> h) noexcept : coro_(h) {}

    task(task&& o) noexcept : coro_(std::exchange(o.coro_, nullptr)) {}
    task& operator=(task&& o) noexcept {
        if (this != &o) {
            if (coro_) coro_.destroy();
            coro_ = std::exchange(o.coro_, nullptr);
        }
        return *this;
    }

    ~task() { if (coro_) coro_.destroy(); }

    task(const task&) = delete;
    task& operator=(const task&) = delete;

    struct awaiter {
        std::coroutine_handle<promise_type> coro_;

        bool await_ready() const noexcept {
            return !coro_ || coro_.done();
        }

        std::coroutine_handle<> await_suspend(std::coroutine_handle<> continuation) noexcept {
            coro_.promise().set_continuation(continuation);
            return coro_;
        }

        decltype(auto) await_resume() {
            return coro_.promise().result();
        }
    };

    awaiter operator co_await() const& noexcept { return awaiter{coro_}; }
    awaiter operator co_await() && noexcept { return awaiter{coro_}; }

    std::coroutine_handle<promise_type> handle() const noexcept { return coro_; }

private:
    std::coroutine_handle<promise_type> coro_;
};

namespace detail {

template<typename T>
task<T> task_promise<T>::get_return_object() noexcept {
    return task<T>{std::coroutine_handle<task_promise<T>>::from_promise(*this)};
}

inline task<void> task_promise<void>::get_return_object() noexcept {
    return task<void>{std::coroutine_handle<task_promise<void>>::from_promise(*this)};
}

} // namespace detail
} // namespace coro
'''

# ═══════════════════════════════════════════════════════════════════════
# Fix 2: generator.hpp — begin() resume + operator++ exception check
# ═══════════════════════════════════════════════════════════════════════

FIXED_GENERATOR_HPP = r'''#pragma once

#include <coroutine>
#include <exception>
#include <utility>
#include <type_traits>
#include <iterator>
#include <cassert>

namespace coro {

template<typename T>
class generator;

namespace detail {

template<typename T>
class generator_promise {
public:
    using value_type = std::remove_reference_t<T>;
    using reference = std::conditional_t<std::is_reference_v<T>, T, T&>;
    using pointer = value_type*;

    generator_promise() = default;

    generator<T> get_return_object() noexcept;

    std::suspend_always initial_suspend() noexcept { return {}; }
    std::suspend_always final_suspend() noexcept { return {}; }

    std::suspend_always yield_value(std::remove_reference_t<T>& value) noexcept {
        m_value = std::addressof(value);
        return {};
    }

    std::suspend_always yield_value(std::remove_reference_t<T>&& value) noexcept {
        m_value = std::addressof(value);
        return {};
    }

    void unhandled_exception() {
        m_exception = std::current_exception();
    }

    void return_void() {}

    reference value() const noexcept {
        return static_cast<reference>(*m_value);
    }

    void rethrow_if_exception() {
        if (m_exception) {
            std::rethrow_exception(m_exception);
        }
    }

    template<typename U>
    std::suspend_never await_transform(U&&) = delete;

private:
    pointer m_value;
    std::exception_ptr m_exception;
};

struct generator_sentinel {};

template<typename T>
class generator_iterator {
    using handle_type = std::coroutine_handle<generator_promise<T>>;

public:
    using iterator_category = std::input_iterator_tag;
    using difference_type = std::ptrdiff_t;
    using value_type = typename generator_promise<T>::value_type;
    using reference = typename generator_promise<T>::reference;
    using pointer = typename generator_promise<T>::pointer;

    generator_iterator() noexcept : m_coroutine(nullptr) {}

    explicit generator_iterator(handle_type coroutine) noexcept
        : m_coroutine(coroutine) {}

    friend bool operator==(const generator_iterator& it, generator_sentinel) noexcept {
        return !it.m_coroutine || it.m_coroutine.done();
    }

    friend bool operator!=(const generator_iterator& it, generator_sentinel s) noexcept {
        return !(it == s);
    }

    generator_iterator& operator++() {
        m_coroutine.resume();
        if (m_coroutine.done()) {
            m_coroutine.promise().rethrow_if_exception();
        }
        return *this;
    }

    void operator++(int) { (void)operator++(); }

    reference operator*() const noexcept {
        return m_coroutine.promise().value();
    }

    pointer operator->() const noexcept {
        return std::addressof(operator*());
    }

private:
    handle_type m_coroutine;
};

} // namespace detail

template<typename T>
class [[nodiscard]] generator {
public:
    using promise_type = detail::generator_promise<T>;
    using iterator = detail::generator_iterator<T>;

    generator() noexcept : m_coroutine(nullptr) {}

    generator(generator&& other) noexcept
        : m_coroutine(other.m_coroutine) {
        other.m_coroutine = nullptr;
    }

    generator(const generator&) = delete;
    generator& operator=(const generator&) = delete;

    ~generator() {
        if (m_coroutine) m_coroutine.destroy();
    }

    generator& operator=(generator&& other) noexcept {
        if (this != &other) {
            if (m_coroutine) m_coroutine.destroy();
            m_coroutine = other.m_coroutine;
            other.m_coroutine = nullptr;
        }
        return *this;
    }

    iterator begin() {
        if (m_coroutine) {
            m_coroutine.resume();
            if (m_coroutine.done()) {
                m_coroutine.promise().rethrow_if_exception();
            }
        }
        return iterator{m_coroutine};
    }

    detail::generator_sentinel end() noexcept {
        return {};
    }

private:
    friend class detail::generator_promise<T>;

    explicit generator(std::coroutine_handle<promise_type> coroutine) noexcept
        : m_coroutine(coroutine) {}

    std::coroutine_handle<promise_type> m_coroutine;
};

namespace detail {

template<typename T>
generator<T> generator_promise<T>::get_return_object() noexcept {
    return generator<T>{std::coroutine_handle<generator_promise<T>>::from_promise(*this)};
}

} // namespace detail
} // namespace coro
'''

# ═══════════════════════════════════════════════════════════════════════
# Fix 3: sync_wait.hpp — complete implementation
# ═══════════════════════════════════════════════════════════════════════

FIXED_SYNC_WAIT_HPP = r'''#pragma once

#include "task.hpp"
#include <coroutine>
#include <utility>

namespace coro {

template<typename T>
T sync_wait(task<T> t) {
    auto h = t.handle();
    h.resume();
    return std::move(h.promise()).result();
}

inline void sync_wait(task<void> t) {
    auto h = t.handle();
    h.resume();
    h.promise().result();
}

} // namespace coro
'''

# ═══════════════════════════════════════════════════════════════════════
# Fix 4: when_all.hpp — complete implementation
# ═══════════════════════════════════════════════════════════════════════

FIXED_WHEN_ALL_HPP = r'''#pragma once

#include "task.hpp"
#include <tuple>
#include <utility>

namespace coro {

template<typename... Ts>
task<std::tuple<Ts...>> when_all(task<Ts>... tasks) {
    // Brace-init guarantees left-to-right evaluation of each co_await.
    co_return std::tuple<Ts...>{co_await std::move(tasks)...};
}

} // namespace coro
'''


def main():
    files = {
        "/app/include/coro/task.hpp": FIXED_TASK_HPP,
        "/app/include/coro/generator.hpp": FIXED_GENERATOR_HPP,
        "/app/include/coro/sync_wait.hpp": FIXED_SYNC_WAIT_HPP,
        "/app/include/coro/when_all.hpp": FIXED_WHEN_ALL_HPP,
    }

    for path, content in files.items():
        with open(path, "w") as f:
            f.write(content)
        print(f"Fixed {path}")


if __name__ == "__main__":
    main()
