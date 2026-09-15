"""
MS MARCO Passage Ranking Evaluation Script
Computes MRR@10 for passage ranking submissions.

Based on the official MS MARCO evaluation methodology.
Supports tab-separated run files in the format: qid\tpid\trank
Reference files use TREC qrels format: qid\t0\tpid\trel
"""
import sys
from collections import Counter

MaxMRRRank = 9


def load_reference_from_stream(f):
    """Load reference relevant passages from stream.
    Args:
        f (stream): stream to load.
    Returns:
        dict: mapping from query_id (int) to relevant passages (list of ints).
    """
    qids_to_relevant_passageids = {}
    for l in f:
        try:
            l = l.strip().split('\t')
            qid = int(l[0])
            if int(l[3]) == 1:
                if qid not in qids_to_relevant_passageids:
                    qids_to_relevant_passageids[qid] = []
                qids_to_relevant_passageids[qid].append(int(l[2]))
        except:
            raise IOError('"%s" is not valid format' % l)
    return qids_to_relevant_passageids


def load_reference(path_to_reference):
    """Load reference relevant passages from file."""
    with open(path_to_reference, 'r') as f:
        qids_to_relevant_passageids = load_reference_from_stream(f)
    return qids_to_relevant_passageids


def load_candidate_from_stream(f):
    """Load candidate data from a stream.
    Args:
        f (stream): stream to load.
    Returns:
        dict: mapping from query_id (int) to a list of 1000 passage ids (int)
              ranked by relevance.
    """
    qid_to_ranked_candidate_passages = {}
    for l in f:
        try:
            l = l.strip().split('\t')
            qid = int(l[0])
            pid = int(l[1])
            rank = int(l[2])
            if qid not in qid_to_ranked_candidate_passages:
                tmp = [0] * 1000
                qid_to_ranked_candidate_passages[qid] = tmp
            qid_to_ranked_candidate_passages[qid][rank] = pid
        except:
            raise IOError('"%s" is not valid format' % l)
    return qid_to_ranked_candidate_passages


def load_candidate(path_to_candidate):
    """Load candidate data from a file."""
    with open(path_to_candidate, 'r') as f:
        qid_to_ranked_candidate_passages = load_candidate_from_stream(f)
    return qid_to_ranked_candidate_passages


def quality_checks_qids(qids_to_relevant_passageids, qids_to_ranked_candidate_passages):
    """Perform quality checks on the dictionaries."""
    message = ''
    allowed = True
    for qid in qids_to_ranked_candidate_passages:
        duplicate_pids = set(
            [item for item, count in
             Counter(qids_to_ranked_candidate_passages[qid]).items()
             if count > 1]
        )
        if len(duplicate_pids - set([0])) > 0:
            message = "Cannot rank a passage multiple times for a single query. QID={qid}, PID={pid}".format(
                qid=qid, pid=list(duplicate_pids)[0])
            allowed = False
    return allowed, message


def compute_metrics(qids_to_relevant_passageids, qids_to_ranked_candidate_passages):
    """Compute MRR metric.
    Args:
        qids_to_relevant_passageids (dict): query-passage relevance mapping.
        qids_to_ranked_candidate_passages (dict): query-passage candidate ranking.
    Returns:
        dict: dictionary of metrics {'MRR @10': <MRR Score>}
    """
    all_scores = {}
    MRR = 0
    ranking = []
    for qid in qids_to_ranked_candidate_passages:
        if qid in qids_to_relevant_passageids:
            ranking.append(0)
            target_pid = qids_to_relevant_passageids[qid]
            candidate_pid = qids_to_ranked_candidate_passages[qid]
            for i in range(0, MaxMRRRank):
                if candidate_pid[i] in target_pid:
                    MRR += 1.0 / (i + 1)
                    ranking.pop()
                    ranking.append(i + 1)
                    break
    if len(ranking) == 0:
        raise IOError("No matching QIDs found. Are you sure you are scoring the evaluation set?")
    MRR = MRR / len(qids_to_ranked_candidate_passages)
    all_scores['MRR @10'] = MRR
    all_scores['QueriesRanked'] = len(qids_to_ranked_candidate_passages)
    return all_scores


def compute_metrics_from_files(path_to_reference, path_to_candidate, perform_checks=True):
    """Compute MRR metric from files."""
    qids_to_relevant_passageids = load_reference(path_to_reference)
    qids_to_ranked_candidate_passages = load_candidate(path_to_candidate)
    if perform_checks:
        allowed, message = quality_checks_qids(
            qids_to_relevant_passageids, qids_to_ranked_candidate_passages)
        if message != '':
            print(message)
    return compute_metrics(qids_to_relevant_passageids, qids_to_ranked_candidate_passages)


def main():
    """Command line:
    python msmarco_eval.py <path_to_reference> <path_to_candidate>
    """
    if len(sys.argv) != 3:
        print("Usage: python msmarco_eval.py <path_to_reference> <path_to_candidate>")
        sys.exit(1)
    path_to_reference = sys.argv[1]
    path_to_candidate = sys.argv[2]
    metrics = compute_metrics_from_files(path_to_reference, path_to_candidate)
    print('#####################')
    for metric in sorted(metrics):
        print('{}: {}'.format(metric, metrics[metric]))
    print('#####################')


if __name__ == '__main__':
    main()
