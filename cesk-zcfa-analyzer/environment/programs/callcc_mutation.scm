(let ((counter 0))
  (let ((saved #f))
    (let ((_ (call/cc (lambda (k)
      (set! saved k)))))
      (let ((_ (set! counter (+ counter 1))))
        (let ((done (= counter 3)))
          (if done
            counter
            (saved #f)))))))
