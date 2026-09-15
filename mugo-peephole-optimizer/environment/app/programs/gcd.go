package main

func itoa(n int) string {
	if n < 10 {
		return char(n + '0')
	}
	return itoa(n / 10) + itoa(n % 10)
}

func gcd(a int, b int) int {
	for b != 0 {
		t := b
		b = a % b
		a = t
	}
	return a
}

func main() {
	print(itoa(gcd(48, 18)) + "\n")
	print(itoa(gcd(100, 75)) + "\n")
	print(itoa(gcd(270, 192)) + "\n")
	print(itoa(gcd(17, 13)) + "\n")
	print(itoa(gcd(462, 1071)) + "\n")
}
