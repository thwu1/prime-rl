(letrec ((fact (lambda (n)
  (let ((z (= n 0)))
    (if z
      1
      (let ((n1 (- n 1)))
        (let ((r (fact n1)))
          (* n r))))))))
  (fact 10))
