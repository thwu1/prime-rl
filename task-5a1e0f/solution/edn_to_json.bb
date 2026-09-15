#!/usr/bin/env bb
;; Convert Jepsen EDN history files to JSON for downstream processing.

(require '[cheshire.core :as json])
(require '[clojure.edn :as edn])
(require '[clojure.java.io :as io])

(let [input-dir (or (first *command-line-args*) "/app/histories")
      output-dir (or (second *command-line-args*) "/tmp/json_histories")
      in-dir (io/file input-dir)
      out-dir (io/file output-dir)]
  (.mkdirs out-dir)
  (doseq [f (sort-by #(.getName %) (.listFiles in-dir))
          :when (and (.isFile f) (.endsWith (.getName f) ".edn"))]
    (let [content (slurp f)
          data (edn/read-string content)
          base-name (subs (.getName f) 0 (- (count (.getName f)) 4))
          out-file (io/file out-dir (str base-name ".json"))]
      (spit out-file (json/generate-string data {:pretty true})))))
