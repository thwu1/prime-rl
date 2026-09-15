"""
Multi-annotator adjudication module for clinical evidence labels.

Resolves disagreements between multiple annotators using majority vote
to produce a single gold-standard set of evidence labels per case.
"""


def adjudicate_annotations(cases, threshold=2):
    """
    Adjudicate multi-annotator evidence relevance labels using majority vote.

    For each sentence in each case:
    1. Count annotators who labeled it as relevant (essential or supplementary).
    2. If the relevant count meets the threshold, the sentence is deemed relevant.
    3. Among the relevant annotators, if a strict majority labeled it "essential",
       it is classified as essential; otherwise supplementary.

    Args:
        cases: list of case dicts from gold_annotations.json
        threshold: minimum annotator count required for relevance (default 2)

    Returns:
        dict mapping case_id -> {
            "strict_evidence": set of essential sentence IDs,
            "lenient_evidence": set of essential + supplementary IDs,
            "relevance_map": {sent_id: "essential"|"supplementary"|"not-relevant"},
            "valid_sentence_ids": set of all sentence IDs in the note
        }
    """
    gold_map = {}

    for case in cases:
        case_id = case["case_id"]
        sentences = case["note_sentences"]
        annotators = case["annotators"]

        valid_ids = {s["id"] for s in sentences}
        relevance_map = {}
        strict_evidence = set()
        lenient_evidence = set()

        for sent in sentences:
            sid = sent["id"]

            # Collect all annotator labels for this sentence
            labels = []
            for ann_name, ann_data in annotators.items():
                for ann_sent in ann_data:
                    if ann_sent["sentence_id"] == sid:
                        labels.append(ann_sent["relevance"])
                        break

            relevant_count = sum(
                1 for l in labels if l in ("essential", "supplementary")
            )

            if relevant_count > threshold:
                essential_count = sum(1 for l in labels if l == "essential")
                if essential_count > relevant_count / 2:
                    relevance_map[sid] = "essential"
                    strict_evidence.add(sid)
                    lenient_evidence.add(sid)
                else:
                    relevance_map[sid] = "supplementary"
                    lenient_evidence.add(sid)
            else:
                relevance_map[sid] = "not-relevant"

        gold_map[case_id] = {
            "strict_evidence": strict_evidence,
            "lenient_evidence": lenient_evidence,
            "relevance_map": relevance_map,
            "valid_sentence_ids": valid_ids,
        }

    return gold_map
