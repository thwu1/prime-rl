#!/usr/bin/env python3
"""
HMM Sequence Decoder.
"""
import math


class HMM:
    def __init__(self):
        self.states = []
        self.alphabet = []
        self.start_prob = {}
        self.trans_prob = {}
        self.emit_prob = {}

    @staticmethod
    def from_file(filepath):
        h = HMM()
        with open(filepath) as f:
            lines = [l.strip() for l in f if l.strip()]

        i = 0
        while i < len(lines):
            line = lines[i]
            if line == 'Alphabet':
                n = int(lines[i + 1])
                h.alphabet = lines[i + 2].split()
                i += 3
            elif line == 'States':
                n = int(lines[i + 1])
                h.states = lines[i + 2].split()
                i += 3
            elif line == 'StartProbability':
                vals = lines[i + 1].split()
                for si, s in enumerate(h.states):
                    h.start_prob[s] = float(vals[si])
                i += 2
            elif line == 'TransitionProbability':
                for si, s_from in enumerate(h.states):
                    vals = lines[i + 1 + si].split()
                    for sj, s_to in enumerate(h.states):
                        h.trans_prob[(s_from, s_to)] = float(vals[sj])
                i += 1 + len(h.states)
            elif line == 'EmissionProbability':
                for si, s in enumerate(h.states):
                    vals = lines[i + 1 + si].split()
                    for ai, a in enumerate(h.alphabet):
                        h.emit_prob[(s, a)] = float(vals[ai])
                i += 1 + len(h.states)
            else:
                i += 1
        return h


def decode(hmm, observations):
    obs = [str(o) for o in observations]
    n = len(obs)
    states = hmm.states

    vit = [{} for _ in range(n)]
    bp = [{} for _ in range(n)]

    for s in states:
        vit[0][s] = hmm.start_prob[s] * hmm.emit_prob[(s, obs[0])]
        bp[0][s] = None

    for t in range(1, n):
        for s in states:
            best_prob = -1
            best_prev = None
            for s_prev in states:
                p = vit[t - 1][s_prev] * hmm.trans_prob[(s_prev, s)]
                if p > best_prob:
                    best_prob = p
                    best_prev = s_prev
            vit[t][s] = best_prob * hmm.emit_prob[(s, obs[t])]
            bp[t][s] = best_prev

    best_final_prob = -1
    best_final_state = None
    for s in states:
        if vit[n - 1][s] > best_final_prob:
            best_final_prob = vit[n - 1][s]
            best_final_state = s

    path = [None] * n
    path[n - 1] = best_final_state
    for t in range(n - 2, -1, -1):
        path[t] = bp[t + 1][path[t + 1]]

    return path, best_final_prob


def decode_log(hmm, observations):
    obs = [str(o) for o in observations]
    n = len(obs)
    states = hmm.states

    vit = [{} for _ in range(n)]
    bp = [{} for _ in range(n)]

    for s in states:
        sp = hmm.start_prob[s]
        ep = hmm.emit_prob[(s, obs[0])]
        vit[0][s] = (math.log(sp) if sp > 0 else float('-inf')) + \
                     (math.log(ep) if ep > 0 else float('-inf'))
        bp[0][s] = None

    for t in range(1, n):
        for s in states:
            best_log_prob = float('-inf')
            best_prev = None
            for s_prev in states:
                tp = hmm.trans_prob[(s_prev, s)]
                log_tp = math.log(tp) if tp > 0 else float('-inf')
                p = vit[t - 1][s_prev] + log_tp
                if p > best_log_prob:
                    best_log_prob = p
                    best_prev = s_prev
            ep = hmm.emit_prob[(s, obs[t])]
            log_ep = math.log(ep) if ep > 0 else float('-inf')
            vit[t][s] = best_log_prob + log_ep
            bp[t][s] = best_prev

    best_final_log = float('-inf')
    best_final_state = None
    for s in states:
        if vit[n - 1][s] > best_final_log:
            best_final_log = vit[n - 1][s]
            best_final_state = s

    path = [None] * n
    path[n - 1] = best_final_state
    for t in range(n - 2, -1, -1):
        path[t] = bp[t + 1][path[t + 1]]

    return path, best_final_log
