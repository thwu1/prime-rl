CREATE TABLE polynomials (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    degree INTEGER NOT NULL,
    coefficients TEXT NOT NULL,
    eval_point REAL NOT NULL,
    description TEXT
);

INSERT INTO polynomials VALUES (1, 'well_conditioned', 3, '[1.0, 1.0, 1.0, 1.0]', 0.5, 'Simple well-conditioned polynomial 1+x+x^2+x^3');
INSERT INTO polynomials VALUES (2, 'near_root_quartic', 4, '[1.0, -4.0, 6.0, -4.0, 1.0]', 1.0001, 'Quartic polynomial evaluated near double root');
INSERT INTO polynomials VALUES (3, 'wilkinson_8', 8, '[40320.0, -109584.0, 118124.0, -67284.0, 22449.0, -4536.0, 546.0, -36.0, 1.0]', 8.000001, 'Degree-8 Wilkinson-type polynomial near root');
INSERT INTO polynomials VALUES (4, 'chebyshev_t6', 6, '[-1.0, 0.0, 18.0, 0.0, -48.0, 0.0, 32.0]', 0.7, 'Chebyshev polynomial of degree 6');
INSERT INTO polynomials VALUES (5, 'near_root_cubic', 3, '[-6.0, 11.0, -6.0, 1.0]', 3.00001, 'Cubic polynomial evaluated near root x=3');
