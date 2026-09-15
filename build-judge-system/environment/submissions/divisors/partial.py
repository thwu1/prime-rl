n = int(input())
divisors = []
for i in range(1, min(n + 1, 51)):
    if n % i == 0:
        divisors.append(i)
for d in divisors:
    print(d)
