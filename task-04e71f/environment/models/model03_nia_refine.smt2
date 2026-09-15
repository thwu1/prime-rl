(model
  (define-fun x () Int 7)
  (define-fun y () Int 2)
  (refine-fun div ((a Int) (b Int)) Int
    (ite (= b 0) 0 (div a b)))
)
