# Common sub-expression elimination test
# Repeated computations with unchanged operands
FUNC compute(a, b):
  entry:
    t1 = a + b
    t2 = a * b
    t3 = t1 + t2
    t4 = a + b
    t5 = a * b
    t6 = t4 + t5
    t7 = t3 + t6
    t8 = a + b
    t9 = t8 * 2
    t10 = t1 * 2
    t11 = t9 + t10
    PRINT t7
    PRINT t11
    t12 = a + b
    t13 = t12 + t3
    PRINT t13
    RETURN t7
END

FUNC main():
  entry:
    r = CALL compute(3, 4)
    PRINT r
    RETURN 0
END
