package main

func itoa(n int) string {
	if n < 10 {
		return char(n + '0')
	}
	return itoa(n / 10) + itoa(n % 10)
}

func main() {
	i := 1
	fact := 1
	for i <= 12 {
		fact = fact * i
		print(itoa(fact) + "\n")
		i = i + 1
	}
}
