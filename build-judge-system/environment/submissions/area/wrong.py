n = int(input())
pts = []
for _ in range(n):
    x, y = map(float, input().split())
    pts.append((x, y))
perimeter = 0
for i in range(n):
    j = (i + 1) % n
    perimeter += ((pts[j][0] - pts[i][0])**2 + (pts[j][1] - pts[i][1])**2) ** 0.5
print(f"{perimeter:.6f}")
