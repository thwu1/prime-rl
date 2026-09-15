def factorial(n:int) -> int:
    if n <= 1:
        return 1
    else:
        return n * factorial(n - 1)

def fib(n:int) -> int:
    if n <= 1:
        return n
    else:
        return fib(n - 1) + fib(n - 2)

def is_even(n:int) -> bool:
    if n == 0:
        return True
    else:
        return is_odd(n - 1)

def is_odd(n:int) -> bool:
    if n == 0:
        return False
    else:
        return is_even(n - 1)

print(factorial(5))
print(factorial(1))
print(fib(10))
print(is_even(4))
print(is_odd(7))
