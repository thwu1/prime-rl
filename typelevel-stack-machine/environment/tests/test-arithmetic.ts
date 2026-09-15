
import type { Expect, Equal } from 'type-testing';
import type { Add, Subtract, Multiply, IsZero } from '../src/arithmetic';

// Addition
type test_add_0_0 = Expect<Equal<Add<0, 0>, 0>>;
type test_add_1_2 = Expect<Equal<Add<1, 2>, 3>>;
type test_add_5_7 = Expect<Equal<Add<5, 7>, 12>>;
type test_add_10_3 = Expect<Equal<Add<10, 3>, 13>>;

// Subtraction (clamped to 0 on underflow)
type test_sub_5_3 = Expect<Equal<Subtract<5, 3>, 2>>;
type test_sub_3_3 = Expect<Equal<Subtract<3, 3>, 0>>;
type test_sub_2_5 = Expect<Equal<Subtract<2, 5>, 0>>;
type test_sub_10_4 = Expect<Equal<Subtract<10, 4>, 6>>;

// Multiplication
type test_mul_3_4 = Expect<Equal<Multiply<3, 4>, 12>>;
type test_mul_0_5 = Expect<Equal<Multiply<0, 5>, 0>>;
type test_mul_5_0 = Expect<Equal<Multiply<5, 0>, 0>>;
type test_mul_6_7 = Expect<Equal<Multiply<6, 7>, 42>>;
type test_mul_1_9 = Expect<Equal<Multiply<1, 9>, 9>>;

// IsZero
type test_is_zero_0 = Expect<Equal<IsZero<0>, true>>;
type test_is_zero_1 = Expect<Equal<IsZero<1>, false>>;
type test_is_zero_5 = Expect<Equal<IsZero<5>, false>>;
