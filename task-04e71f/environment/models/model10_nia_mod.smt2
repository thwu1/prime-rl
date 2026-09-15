(model
  (define-fun a () Int 12)
  (define-fun b () Int 5)
  (refine-fun mod ((x Int) (y Int)) Int
    (ite (= y 0) 0 (mod x y)))
)
