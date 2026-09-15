package main

func fib(n int) int {
	if n <= 1 {
		return n
	}
	return fib(n - 1) + fib(n - 2)
}

func itoa(n int) string {
	if n < 10 {
		return char(n + '0')
	}
	return itoa(n / 10) + itoa(n % 10)
}

func main() {
	i := 0
	for i < 10 {
		print(itoa(fib(i)) + "\n")
		i = i + 1
	}
}
