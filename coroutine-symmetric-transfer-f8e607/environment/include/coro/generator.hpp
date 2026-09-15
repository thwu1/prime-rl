#pragma once

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
