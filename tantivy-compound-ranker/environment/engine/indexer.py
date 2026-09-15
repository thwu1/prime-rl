"""Inverted index builder for the search engine."""

from engine.tokenizer import tokenize


class InvertedIndex:
    """Builds and stores per-field inverted index data structures."""

    def __init__(self):
        self.num_docs = 0
        self.titles = {}
        self.field_tf = {}
        self.field_dl = {}
        self.field_avgdl = {}
        self.field_df = {}

    def build(self, corpus, fields):
        """Index all documents across the specified fields."""
        self.num_docs = len(corpus)
        self.titles = {doc["id"]: doc["title"] for doc in corpus}

        # Accumulate document frequencies across all fields
        global_term_docs = {}

        for field in fields:
            self.field_tf[field] = {}
            self.field_dl[field] = {}

            for doc in corpus:
                doc_id = doc["id"]
                tokens = tokenize(doc.get(field, ""))
                self.field_dl[field][doc_id] = len(tokens)

                tf_counts = {}
                for token in tokens:
                    tf_counts[token] = tf_counts.get(token, 0) + 1

                for term, count in tf_counts.items():
                    if term not in self.field_tf[field]:
                        self.field_tf[field][term] = {}
                    self.field_tf[field][term][doc_id] = count

                    # Track which documents contain each term globally
                    if term not in global_term_docs:
                        global_term_docs[term] = set()
                    global_term_docs[term].add(doc_id)

            total_len = sum(self.field_dl[field].values())
            self.field_avgdl[field] = total_len / self.num_docs if self.num_docs > 0 else 1.0

        # Use global document frequency counts for all fields
        for field in fields:
            self.field_df[field] = {}
            for term in self.field_tf[field]:
                self.field_df[field][term] = len(global_term_docs.get(term, set()))

    def get_tf(self, field, term, doc_id):
        """Get term frequency for a term in a field of a document."""
        return self.field_tf.get(field, {}).get(term, {}).get(doc_id, 0)

    def get_df(self, field, term):
        """Get document frequency for a term in a field."""
        return self.field_df.get(field, {}).get(term, 0)

    def get_dl(self, field, doc_id):
        """Get document length for a field of a document."""
        return self.field_dl.get(field, {}).get(doc_id, 0)

    def get_avgdl(self, field):
        """Get average document length for a field."""
        return self.field_avgdl.get(field, 1.0)

    def get_doc_ids_for_term(self, field, term):
        """Get all document IDs containing a term in a field."""
        return set(self.field_tf.get(field, {}).get(term, {}).keys())
