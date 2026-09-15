"""Search execution module."""

from engine.tokenizer import tokenize


class Searcher:
    """Executes queries against the inverted index using BM25 scoring."""

    def __init__(self, index, scorer, field_boosts):
        self.index = index
        self.scorer = scorer
        self.field_boosts = field_boosts

    def search(self, query_text, top_k=10):
        """Search for documents matching the query text.

        Returns a list of (doc_id, score, title) tuples sorted by score descending.
        """
        query_tokens = tokenize(query_text)
        if not query_tokens:
            return []

        doc_scores = {}

        for field, boost in self.field_boosts.items():
            for term in query_tokens:
                matching_docs = self.index.get_doc_ids_for_term(field, term)
                df = self.index.get_df(field, term)

                for doc_id in matching_docs:
                    tf = self.index.get_tf(field, term, doc_id)
                    dl = self.index.get_dl(field, doc_id)
                    avgdl = self.index.get_avgdl(field)

                    term_field_score = self.scorer.score(tf, df, dl, avgdl) * boost

                    if doc_id not in doc_scores:
                        doc_scores[doc_id] = []
                    doc_scores[doc_id].append(term_field_score)

        # Aggregate per-document scores
        results = []
        for doc_id, scores in doc_scores.items():
            total_score = max(scores)
            title = self.index.titles.get(doc_id, "")
            results.append((doc_id, total_score, title))

        results.sort(key=lambda x: -x[1])
        return results[:top_k]
