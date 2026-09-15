(letrec ((is-even (lambda (n)
                   (let ((z (= n 0)))
                     (if z
                       #t
                       (let ((n1 (- n 1)))
                         (is-odd n1))))))
         (is-odd (lambda (m)
                   (let ((z2 (= m 0)))
                     (if z2
                       #f
                       (let ((m1 (- m 1)))
                         (is-even m1)))))))
  (is-even 10))
