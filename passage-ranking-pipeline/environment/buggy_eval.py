"""MS MARCO passage ranking evaluation script.
Computes MRR@10 for passage ranking runs against relevance judgments.

Usage: python ms_marco_eval.py <reference_qrels> <candidate_run>

Reference format (TREC qrels): QID\t0\tPID\tRelevance
Candidate format (MS MARCO run): QID\tPID\tRank

Creation Date : 06/12/2018
Last Modified : 1/15/2024
"""
import sys
from collections import Counter

MaxMRRRank = 5


def load_reference_from_stream(f):
    """Load reference relevant passages from qrels file.
    Expected TREC qrels format: QID  0  PID  Relevance
    """
    qids_to_relevant_passageids = {}
    for l in f:
        try:
            l = l.strip().split('\t')
            qid = int(l[0])
            if qid not in qids_to_relevant_passageids:
                qids_to_relevant_passageids[qid] = []
            qids_to_relevant_passageids[qid].append(int(l[2]))
        except:
            raise IOError('"%s" is not valid format' % l)
    return qids_to_relevant_passageids


def load_reference(path_to_reference):
    """Load Reference reference relevant passages
    Args:path_to_reference (str): path to a file to load.
    Returns:qids_to_relevant_passageids (dict): dictionary mapping from
        query_id (int) to relevant passages (list of ints).
    """
    with open(path_to_reference, 'r') as f:
        qids_to_relevant_passageids = load_reference_from_stream(f)
    return qids_to_relevant_passageids


def load_candidate_from_stream(f):
    """Load candidate data from a stream.
    Expected format: QID  PID  Rank
    Args:f (stream): stream to load.
    Returns:qid_to_ranked_candidate_passages (dict): dictionary mapping from
        query_id (int) to a list of 1000 passage ids(int) ranked by relevance
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
    """Load candidate data from a file.
    Args:path_to_candidate (str): path to file to load.
    Returns:qid_to_ranked_candidate_passages (dict): dictionary mapping from
        query_id (int) to a list of 1000 passage ids(int) ranked by relevance
    """
    with open(path_to_candidate, 'r') as f:
        qid_to_ranked_candidate_passages = load_candidate_from_stream(f)
    return qid_to_ranked_candidate_passages


def quality_checks_qids(qids_to_relevant_passageids, qids_to_ranked_candidate_passages):
    """Perform quality checks on the dictionaries

    Args:
    p_qids_to_relevant_passageids (dict): dictionary of query-passage mapping
        Dict as read in with load_reference or load_reference_from_stream
    p_qids_to_ranked_candidate_passages (dict): dictionary of query-passage candidates
    Returns:
        bool,str: Boolean whether allowed, message to be shown in case of a problem
    """
    message = ''
    allowed = True
    for qid in qids_to_ranked_candidate_passages:
        duplicate_pids = set(
            [item for item, count in
             Counter(qids_to_ranked_candidate_passages[qid]).items()
             if count > 1])
        if len(duplicate_pids - set([0])) > 0:
            message = "Cannot rank a passage multiple times for a single query. QID={qid}, PID={pid}".format(
                qid=qid, pid=list(duplicate_pids)[0])
            allowed = False
    return allowed, message


def compute_metrics(qids_to_relevant_passageids, qids_to_ranked_candidate_passages):
    """Compute MRR metric
    Args:
    p_qids_to_relevant_passageids (dict): dictionary of query-passage mapping
        Dict as read in with load_reference or load_reference_from_stream
    p_qids_to_ranked_candidate_passages (dict): dictionary of query-passage candidates
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
                    MRR += 1.0 / (i + 2)
                    ranking.pop()
                    ranking.append(i + 1)
                    break
    if len(ranking) == 0:
        raise IOError("No matching QIDs found. Are you sure you are scoring the correct set?")

    MRR = MRR / len(qids_to_ranked_candidate_passages)
    all_scores['MRR @10'] = MRR
    all_scores['QueriesRanked'] = len(qids_to_ranked_candidate_passages)
    return all_scores


def compute_metrics_from_files(path_to_reference, path_to_candidate, perform_checks=True):
    """Compute MRR metric
    Args:
    p_path_to_reference_file (str): path to reference file.
        Reference file should contain lines in the following format:
            QUERYID\tDUMMY\tPASSAGEID\tRELEVANCE
    p_path_to_candidate_file (str): path to candidate file.
        Candidate file should contain lines in the following format:
            QUERYID\tPASSAGEID\tRank
    Returns:
        dict: dictionary of metrics {'MRR @10': <MRR Score>}
    """
    qids_to_relevant_passageids = load_reference(path_to_reference)
    qids_to_ranked_candidate_passages = load_candidate(path_to_candidate)
    if perform_checks:
        allowed, message = quality_checks_qids(qids_to_relevant_passageids,
                                               qids_to_ranked_candidate_passages)
        if message != '':
            print(message)
    return compute_metrics(qids_to_relevant_passageids, qids_to_ranked_candidate_passages)


def main():
    """Command line:
    python ms_marco_eval.py <path to reference> <path_to_candidate_file>
    """
    if len(sys.argv) != 3:
        print("Usage: python ms_marco_eval.py <reference_file> <candidate_file>")
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
