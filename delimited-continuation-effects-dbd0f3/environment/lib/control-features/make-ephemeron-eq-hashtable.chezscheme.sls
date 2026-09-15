#!r6rs

;; Copyright (C) Marc Nieper-Wißkirchen (2021).  All Rights Reserved.
;; MIT License

(library (control-features make-ephemeron-eq-hashtable)
  (export make-ephemeron-eq-hashtable)
  (import (only (chezscheme) make-ephemeron-eq-hashtable)))
