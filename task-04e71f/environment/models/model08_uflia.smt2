(model
  (define-fun x () Int 5)
  (define-fun y () Int 5)
  (define-fun f ((a Int)) Int (ite (= a 5) 10 0))
)
