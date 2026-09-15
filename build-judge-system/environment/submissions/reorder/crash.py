n = int(input())
a = list(map(int, input().split()))
result = [a[i + 1] for i in range(n)]
print(' '.join(map(str, result)))
