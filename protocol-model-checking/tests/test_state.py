"""
Reference model checker and verification tests for the dual-channel
pilot flying protocol (synchronous and asynchronous variants).

"""
import json
import pytest
from collections import deque
from itertools import product

# ======================================================================
# Reference implementation: Synchronous protocol
# Faithful translation of PVS Side_LLR + Bus_LLR + Pilot_Flying_System
# ======================================================================

def _s_side_init(primary):
    """Side_LLR[Primary_Side].Initial_State → (pilot_flying, pre_ts, pre_ospf)"""
    return (primary, True, not primary)

def _s_side_ns(sd, ts, ospf):
    """Side_LLR next_state"""
    pf, pt, po = sd
    rt = (not pt) and ts
    ro = (not po) and ospf
    if pf and ro:
        npf = False
    elif (not pf) and rt:
        npf = True
    else:
        npf = pf
    return (npf, ts, ospf)

def _s_pf(sd):
    return sd[0]

def _s_init():
    """Pilot_Flying_System.Initial_State"""
    return (
        _s_side_init(True),   # Left (primary)
        True,                 # LR_Bus init = True
        _s_side_init(False),  # Right (non-primary)
        False,                # RL_Bus init = False
        True,                 # pre_TS
    )

def _s_ns(st, ts):
    """Pilot_Flying_System.next_state"""
    ls, lr, rs, rl, pts = st
    c1 = _s_pf(ls)
    nlr = c1       # bus next_state = input, output = state
    c2 = nlr       # bus output
    nrs = _s_side_ns(rs, ts, c2)
    c3 = _s_pf(rs)
    nrl = c3
    c4 = nrl
    nls = _s_side_ns(ls, ts, c4)
    return (nls, nlr, nrs, nrl, ts)

def _s_lpf(st): return _s_pf(st[0])
def _s_rpf(st): return _s_pf(st[2])
def _s_pressed(ts, st): return (not st[4]) and ts
def _s_switching(st):
    return (_s_lpf(st) and not st[1]) or (_s_rpf(st) and not st[3])

def _s_bfs():
    init = _s_init()
    vis = {init}
    q = deque([init])
    while q:
        s = q.popleft()
        for ts in (True, False):
            ns = _s_ns(s, ts)
            if ns not in vis:
                vis.add(ns)
                q.append(ns)
    return vis

def _s_check(states):
    r = {}
    init = _s_init()
    r['R1'] = all(_s_lpf(s) or _s_rpf(s) for s in states)
    r['R2'] = all(_s_switching(s) or (_s_lpf(s) != _s_rpf(s)) for s in states)

    r3a = r3b = r5a = r5b = True
    for s in states:
        for ts in (True, False):
            ns = _s_ns(s, ts)
            if (not _s_lpf(s)) and _s_pressed(ts, s):
                if not _s_lpf(ns):
                    r3a = False
            if (not _s_rpf(s)) and _s_pressed(ts, s):
                if not _s_rpf(ns):
                    r3b = False
            if (not _s_switching(s)) and (not _s_pressed(ts, s)):
                if _s_lpf(ns) != _s_lpf(s):
                    r5a = False
                if _s_rpf(ns) != _s_rpf(s):
                    r5b = False
    r['R3a'] = r3a
    r['R3b'] = r3b
    r['R4'] = _s_lpf(init)
    r['R5a'] = r5a
    r['R5b'] = r5b

    # Reachable_States_Valid
    vsv = True
    for s in states:
        ls, lr, rs, rl, pts = s
        if ls[1] != bool(pts) or rs[1] != bool(pts):
            vsv = False
        if rs[2] != bool(lr):
            vsv = False
        if ls[2] != bool(rl):
            vsv = False
        if not (_s_lpf(s) or _s_rpf(s)):
            vsv = False
        if _s_pf(ls) == _s_pf(rs):
            if bool(lr) == bool(rl):
                vsv = False
    r['Reachable_States_Valid'] = vsv

    # Switching_Transient
    swt = True
    for s in states:
        if _s_switching(s):
            for ts in (True, False):
                if _s_switching(_s_ns(s, ts)):
                    swt = False
    r['Switching_Transient'] = swt

    return r


# ======================================================================
# Reference implementation: Asynchronous protocol
# Faithful translation of PVS Side_LLR (4-state) + Bus_LLR + System
# ======================================================================

_C, _I, _L, _W = 0, 1, 2, 3  # Confirmed, Inhibited, Listening, Waiting

def _a_side_init(primary):
    """Side_LLR[Primary_Side].Initial_State → (st, pre_ts, (msg_pfs, msg_ack))"""
    st = _C if primary else _L
    return (st, True, (not primary, True))

def _a_side_ns(sd, clk, ts, m):
    """Side_LLR next_state with clock gating"""
    if not clk:
        return sd
    st, pt, pm = sd
    ro = (not pm[0]) and m[0]      # rise_ospf
    rt = (not pt) and ts            # rise_ts
    fa = pm[1] and (not m[1])       # fall_ack
    if st == _C and ro:
        nst = _I
    elif st == _I and m[1]:
        nst = _L
    elif st == _L and rt:
        nst = _W
    elif st == _W and fa:
        nst = _C
    else:
        nst = st
    return (nst, ts, m)

def _a_side_out(sd):
    """Side_LLR output → (pfs, ack)"""
    st = sd[0]
    return (st == _C or st == _W, st == _C or st == _L)

def _a_init():
    return (
        _a_side_init(True),    # Left
        (True, True),          # LR_Bus = Msg(True, True)
        _a_side_init(False),   # Right
        (False, True),         # RL_Bus = Msg(False, True)
        True,                  # pre_TS
    )

def _a_ns(st, c1, c2, c3, c4, ts):
    """Pilot_Flying_System.next_state (async)"""
    ls, lr, rs, rl, pts = st
    o1 = _a_side_out(ls)
    nlr = o1 if c2 else lr
    o2 = nlr
    nrs = _a_side_ns(rs, c3, ts, o2)
    o3 = _a_side_out(rs)
    nrl = o3 if c4 else rl
    o4 = nrl
    nls = _a_side_ns(ls, c1, ts, o4)
    return (nls, nlr, nrs, nrl, ts)

def _a_lpf(st): return _a_side_out(st[0])[0]
def _a_rpf(st): return _a_side_out(st[2])[0]
def _a_pressed(ts, st): return (not st[4]) and ts
def _a_switching(st):
    return (_a_lpf(st) and not st[1][0]) or (_a_rpf(st) and not st[3][0])

def _a_bfs():
    init = _a_init()
    vis = {init}
    q = deque([init])
    inp = list(product((True, False), repeat=5))
    while q:
        s = q.popleft()
        for c1, c2, c3, c4, ts in inp:
            ns = _a_ns(s, c1, c2, c3, c4, ts)
            if ns not in vis:
                vis.add(ns)
                q.append(ns)
    return vis

def _a_check(states):
    r = {}
    inp = list(product((True, False), repeat=5))
    init = _a_init()

    r['R1'] = all(_a_lpf(s) or _a_rpf(s) for s in states)
    r['R2'] = all(_a_switching(s) or (_a_lpf(s) != _a_rpf(s)) for s in states)

    r3a = r3b = r5a = r5b = True
    for s in states:
        if not (r3a or r3b or r5a or r5b):
            break
        for c1, c2, c3, c4, ts in inp:
            ns = _a_ns(s, c1, c2, c3, c4, ts)
            if r3a and (not _a_lpf(s)) and _a_pressed(ts, s):
                if not _a_lpf(ns):
                    r3a = False
            if r3b and (not _a_rpf(s)) and _a_pressed(ts, s):
                if not _a_rpf(ns):
                    r3b = False
            if (r5a or r5b) and (not _a_switching(s)) and (not _a_pressed(ts, s)):
                if r5a and _a_lpf(ns) != _a_lpf(s):
                    r5a = False
                if r5b and _a_rpf(ns) != _a_rpf(s):
                    r5b = False
    r['R3a'] = r3a
    r['R3b'] = r3b
    r['R4'] = _a_lpf(init)
    r['R5a'] = r5a
    r['R5b'] = r5b
    return r


# ======================================================================
# Fixtures
# ======================================================================

@pytest.fixture(scope="module")
def sync_ref():
    states = _s_bfs()
    return len(states), _s_check(states)

@pytest.fixture(scope="module")
def async_ref():
    states = _a_bfs()
    return len(states), _a_check(states)

@pytest.fixture(scope="module")
def results():
    with open('/app/results.json') as f:
        return json.load(f)


# ======================================================================
# Tests: Results structure
# ======================================================================

class TestStructure:
    def test_json_loads(self, results):
        assert isinstance(results, dict)

    def test_has_synchronous(self, results):
        assert 'synchronous' in results
        s = results['synchronous']
        assert 'reachable_state_count' in s
        assert 'requirements' in s
        assert isinstance(s['reachable_state_count'], int)

    def test_has_asynchronous(self, results):
        assert 'asynchronous' in results
        a = results['asynchronous']
        assert 'reachable_state_count' in a
        assert 'requirements' in a
        assert isinstance(a['reachable_state_count'], int)

    def test_sync_has_all_requirements(self, results):
        req = results['synchronous']['requirements']
        for key in ['R1', 'R2', 'R3a', 'R3b', 'R4', 'R5a', 'R5b',
                     'Reachable_States_Valid', 'Switching_Transient']:
            assert key in req, f"Missing sync requirement: {key}"

    def test_async_has_all_requirements(self, results):
        req = results['asynchronous']['requirements']
        for key in ['R1', 'R2', 'R3a', 'R3b', 'R4', 'R5a', 'R5b']:
            assert key in req, f"Missing async requirement: {key}"


# ======================================================================
# Tests: Synchronous protocol
# ======================================================================

class TestSynchronous:
    def test_reachable_state_count(self, results, sync_ref):
        expected = sync_ref[0]
        actual = results['synchronous']['reachable_state_count']
        assert actual == expected, (
            f"Sync reachable states: expected {expected}, got {actual}"
        )

    def test_R1(self, results, sync_ref):
        assert results['synchronous']['requirements']['R1'] == sync_ref[1]['R1']

    def test_R2(self, results, sync_ref):
        assert results['synchronous']['requirements']['R2'] == sync_ref[1]['R2']

    def test_R3a(self, results, sync_ref):
        assert results['synchronous']['requirements']['R3a'] == sync_ref[1]['R3a']

    def test_R3b(self, results, sync_ref):
        assert results['synchronous']['requirements']['R3b'] == sync_ref[1]['R3b']

    def test_R4(self, results, sync_ref):
        assert results['synchronous']['requirements']['R4'] == sync_ref[1]['R4']

    def test_R5a(self, results, sync_ref):
        assert results['synchronous']['requirements']['R5a'] == sync_ref[1]['R5a']

    def test_R5b(self, results, sync_ref):
        assert results['synchronous']['requirements']['R5b'] == sync_ref[1]['R5b']

    def test_Reachable_States_Valid(self, results, sync_ref):
        assert results['synchronous']['requirements']['Reachable_States_Valid'] == \
               sync_ref[1]['Reachable_States_Valid']

    def test_Switching_Transient(self, results, sync_ref):
        assert results['synchronous']['requirements']['Switching_Transient'] == \
               sync_ref[1]['Switching_Transient']


# ======================================================================
# Tests: Asynchronous protocol
# ======================================================================

class TestAsynchronous:
    def test_reachable_state_count(self, results, async_ref):
        expected = async_ref[0]
        actual = results['asynchronous']['reachable_state_count']
        assert actual == expected, (
            f"Async reachable states: expected {expected}, got {actual}"
        )

    def test_R1(self, results, async_ref):
        assert results['asynchronous']['requirements']['R1'] == async_ref[1]['R1']

    def test_R2(self, results, async_ref):
        assert results['asynchronous']['requirements']['R2'] == async_ref[1]['R2']

    def test_R3a(self, results, async_ref):
        assert results['asynchronous']['requirements']['R3a'] == async_ref[1]['R3a']

    def test_R3b(self, results, async_ref):
        assert results['asynchronous']['requirements']['R3b'] == async_ref[1]['R3b']

    def test_R4(self, results, async_ref):
        assert results['asynchronous']['requirements']['R4'] == async_ref[1]['R4']

    def test_R5a(self, results, async_ref):
        assert results['asynchronous']['requirements']['R5a'] == async_ref[1]['R5a']

    def test_R5b(self, results, async_ref):
        assert results['asynchronous']['requirements']['R5b'] == async_ref[1]['R5b']


# ======================================================================
# Tests: Sanity checks on reference values
# ======================================================================

class TestReferenceSanity:
    """Verify the reference implementation against known properties."""

    def test_sync_r4_trivially_true(self, sync_ref):
        """R4 is trivially true: the initial state has left as primary."""
        assert sync_ref[1]['R4'] is True

    def test_sync_all_requirements_hold(self, sync_ref):
        """NASA report proves all sync requirements hold."""
        for key in ['R1', 'R2', 'R3a', 'R3b', 'R4', 'R5a', 'R5b',
                     'Reachable_States_Valid', 'Switching_Transient']:
            assert sync_ref[1][key] is True, f"Sync {key} should hold"

    def test_async_r4_true(self, async_ref):
        assert async_ref[1]['R4'] is True

    def test_async_r1_true(self, async_ref):
        """R1 (liveness) should hold for async protocol."""
        assert async_ref[1]['R1'] is True

    def test_sync_reachable_reasonable_size(self, sync_ref):
        """Sync has 2^9=512 possible states; reachable should be much less."""
        assert 2 < sync_ref[0] < 512

    def test_async_larger_than_sync(self, sync_ref, async_ref):
        """Async state space is strictly larger due to richer state types."""
        assert async_ref[0] > sync_ref[0]
