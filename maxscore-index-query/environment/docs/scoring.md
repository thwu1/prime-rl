# Relevance Scoring

This deployment uses BM25 with the following formulation:

    score(t, d) = IDF(t) * (f(t,d) * (k1 + 1)) / (f(t,d) + k1 * (1 - b + b * dl / avgdl))

Where:
- IDF(t) = ln((N + 1) / (df(t) + 0.5))
- f(t,d) = raw term frequency in document d
- df(t) = number of documents containing term t
- dl = document length (from .sizes file)
- avgdl = average document length across collection
- N = total number of documents
- k1, b = tuning parameters from the metadata store
- ln = natural logarithm
