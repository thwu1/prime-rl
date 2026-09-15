# Dead code elimination test
# Many computed values are never used on any path to output
FUNC main():
  entry:
    x = 5
    y = 10
    z = x + y
    dead1 = x * 100
    dead2 = dead1 + y
    dead3 = dead2 * dead1
    used1 = z + 1
    dead4 = used1 * 99
    dead5 = dead4 + dead3
    PRINT used1
    w = x - y
    dead6 = w * w
    dead7 = dead6 + 42
    PRINT w
    dead8 = 999
    dead9 = dead8 + dead7
    dead10 = dead9 * 2
    result = used1 + w
    PRINT result
    RETURN 0
END
