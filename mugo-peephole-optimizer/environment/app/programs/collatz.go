package main

func itoa(n int) string {
	if n < 10 {
		return char(n + '0')
	}
	return itoa(n / 10) + itoa(n % 10)
}

func collatz(n int) int {
	steps := 0
	for n != 1 {
		if n % 2 == 0 {
			n = n / 2
		} else {
			n = n * 3 + 1
		}
		steps = steps + 1
	}
	return steps
}

func main() {
	i := 1
	for i <= 20 {
		print(itoa(collatz(i)) + "\n")
		i = i + 1
	}
}
