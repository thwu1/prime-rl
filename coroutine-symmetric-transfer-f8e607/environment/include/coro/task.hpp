#pragma once

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
        void await_suspend(std::coroutine_handle<Promise> h) noexcept {
            h.promise().continuation_.resume();
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
        return std::get<1>(result_);
    }

    T&& result() && {
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

        void await_suspend(std::coroutine_handle<> continuation) noexcept {
            coro_.promise().set_continuation(continuation);
            coro_.resume();
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
