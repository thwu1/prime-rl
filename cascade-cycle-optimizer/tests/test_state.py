
import json
import subprocess
import pytest
from CoolProp.CoolProp import PropsSI


# ---------------------------------------------------------------------------
# Independent reference implementation
# ---------------------------------------------------------------------------

def _ref_single_cycle(fluid, T_evap, T_cond, eta_isen, superheat, subcool):
    P_evap = PropsSI('P', 'T', T_evap, 'Q', 1, fluid)
    P_cond = PropsSI('P', 'T', T_cond, 'Q', 0, fluid)

    T1 = T_evap + superheat
    H1 = PropsSI('H', 'T', T1, 'P', P_evap, fluid)
    S1 = PropsSI('S', 'T', T1, 'P', P_evap, fluid)

    H2s = PropsSI('H', 'P', P_cond, 'S', S1, fluid)
    H2 = H1 + (H2s - H1) / eta_isen
    T2 = PropsSI('T', 'P', P_cond, 'H', H2, fluid)
    S2 = PropsSI('S', 'P', P_cond, 'H', H2, fluid)

    T3 = T_cond - subcool
    H3 = PropsSI('H', 'T', T3, 'P|liquid', P_cond, fluid)
    S3 = PropsSI('S', 'T', T3, 'P|liquid', P_cond, fluid)

    H4 = H3
    T4 = PropsSI('T', 'P', P_evap, 'H', H4, fluid)
    S4 = PropsSI('S', 'P', P_evap, 'H', H4, fluid)

    q_evap = H1 - H4
    w_comp = H2 - H1
    q_cond = H2 - H3

    return {
        'COP': q_evap / w_comp,
        'w_comp': w_comp,
        'q_evap': q_evap,
        'q_cond': q_cond,
        'T_discharge_K': T2,
        'pressure_ratio': P_cond / P_evap,
        'states': [
            {'T': T1, 'P': P_evap, 'H': H1, 'S': S1},
            {'T': T2, 'P': P_cond, 'H': H2, 'S': S2},
            {'T': T3, 'P': P_cond, 'H': H3, 'S': S3},
            {'T': T4, 'P': P_evap, 'H': H4, 'S': S4},
        ],
    }


def _ref_analyze(plant):
    stages = plant['stages']
    hxs = plant['cascade_heat_exchangers']
    ct = plant['cascade_temperatures_K']

    st = {}
    for s in stages:
        st[s['id']] = [
            s['evaporator'].get('saturation_temperature_K'),
            s['condenser'].get('saturation_temperature_K'),
        ]
    for i, hx in enumerate(hxs):
        dT = hx['approach_temperature_K']
        st[hx['hot_stage']][1] = ct[i] + dT / 2.0
        st[hx['cold_stage']][0] = ct[i] - dT / 2.0

    sr = {}
    for s in stages:
        sid = s['id']
        sr[sid] = _ref_single_cycle(
            s['refrigerant'], st[sid][0], st[sid][1],
            s['compressor']['isentropic_efficiency'],
            s['evaporator']['superheat_K'],
            s['condenser']['subcool_K'],
        )

    Q_cool = plant['cooling_capacity_W']
    mf = {stages[0]['id']: Q_cool / sr[stages[0]['id']]['q_evap']}
    duties = []
    for hx in hxs:
        Q = mf[hx['hot_stage']] * sr[hx['hot_stage']]['q_cond']
        duties.append(Q)
        mf[hx['cold_stage']] = Q / sr[hx['cold_stage']]['q_evap']

    for sid, m in mf.items():
        sr[sid]['mass_flow_kg_s'] = m

    W = sum(mf[s['id']] * sr[s['id']]['w_comp'] for s in stages)

    return {
        'system_COP': Q_cool / W,
        'total_power_W': W,
        'stages': sr,
        'cascade_hx_duties_W': duties,
    }


def _ref_diagnose(plant, measured):
    stages = plant['stages']
    hxs = plant['cascade_heat_exchangers']
    ct = plant['cascade_temperatures_K']

    st = {}
    for s in stages:
        st[s['id']] = [
            s['evaporator'].get('saturation_temperature_K'),
            s['condenser'].get('saturation_temperature_K'),
        ]
    for i, hx in enumerate(hxs):
        dT = hx['approach_temperature_K']
        st[hx['hot_stage']][1] = ct[i] + dT / 2.0
        st[hx['cold_stage']][0] = ct[i] - dT / 2.0

    actual = {}
    devs = {}
    for s in stages:
        sid = s['id']
        fluid = s['refrigerant']
        P_evap = PropsSI('P', 'T', st[sid][0], 'Q', 1, fluid)
        P_cond = PropsSI('P', 'T', st[sid][1], 'Q', 0, fluid)
        T1 = st[sid][0] + s['evaporator']['superheat_K']
        H1 = PropsSI('H', 'T', T1, 'P', P_evap, fluid)
        S1 = PropsSI('S', 'T', T1, 'P', P_evap, fluid)
        H2s = PropsSI('H', 'P', P_cond, 'S', S1, fluid)
        T_m = measured['measured_discharge_temperatures_K'][sid]
        H2a = PropsSI('H', 'T', T_m, 'P', P_cond, fluid)
        eta = (H2s - H1) / (H2a - H1)
        actual[sid] = eta
        devs[sid] = eta - s['compressor']['isentropic_efficiency']

    return {'actual_efficiencies': actual, 'efficiency_deviations': devs}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(args):
    proc = subprocess.run(
        ['python3', '/app/cascade.py'] + args,
        capture_output=True, text=True, cwd='/app',
        timeout=300,
    )
    assert proc.returncode == 0, f"Command failed with stderr:\n{proc.stderr}"
    return json.loads(proc.stdout)


def _load(path):
    with open(path) as f:
        return json.load(f)


REL_TOL = 1e-4   # 0.01 %


def _rel(a, b):
    return abs(a - b) / max(abs(b), 1e-30)


# ===================================================================
# Plant A — 2-stage R23 / R134a
# ===================================================================

class TestAnalyzePlantA:
    @classmethod
    def setup_class(cls):
        cls.r = _run(['analyze', '/app/plants/plant_a.json'])
        cls.ref = _ref_analyze(_load('/app/plants/plant_a.json'))

    def test_system_cop(self):
        assert _rel(self.r['system_COP'], self.ref['system_COP']) < REL_TOL

    def test_total_power(self):
        assert _rel(self.r['total_power_W'], self.ref['total_power_W']) < REL_TOL

    def test_lt_cop(self):
        assert _rel(self.r['stages']['LT']['COP'], self.ref['stages']['LT']['COP']) < REL_TOL

    def test_ht_cop(self):
        assert _rel(self.r['stages']['HT']['COP'], self.ref['stages']['HT']['COP']) < REL_TOL

    def test_lt_w_comp(self):
        assert _rel(self.r['stages']['LT']['w_comp'], self.ref['stages']['LT']['w_comp']) < REL_TOL

    def test_ht_w_comp(self):
        assert _rel(self.r['stages']['HT']['w_comp'], self.ref['stages']['HT']['w_comp']) < REL_TOL

    def test_lt_mass_flow(self):
        assert _rel(self.r['stages']['LT']['mass_flow_kg_s'],
                     self.ref['stages']['LT']['mass_flow_kg_s']) < REL_TOL

    def test_ht_mass_flow(self):
        assert _rel(self.r['stages']['HT']['mass_flow_kg_s'],
                     self.ref['stages']['HT']['mass_flow_kg_s']) < REL_TOL

    def test_lt_discharge_temp(self):
        assert abs(self.r['stages']['LT']['T_discharge_K']
                    - self.ref['stages']['LT']['T_discharge_K']) < 0.1

    def test_ht_discharge_temp(self):
        assert abs(self.r['stages']['HT']['T_discharge_K']
                    - self.ref['stages']['HT']['T_discharge_K']) < 0.1

    def test_lt_pressure_ratio(self):
        assert _rel(self.r['stages']['LT']['pressure_ratio'],
                     self.ref['stages']['LT']['pressure_ratio']) < REL_TOL

    def test_lt_energy_balance(self):
        lt = self.r['stages']['LT']
        assert _rel(lt['q_cond'], lt['q_evap'] + lt['w_comp']) < 1e-6

    def test_ht_energy_balance(self):
        ht = self.r['stages']['HT']
        assert _rel(ht['q_cond'], ht['q_evap'] + ht['w_comp']) < 1e-6

    def test_cascade_hx_balance(self):
        lt = self.r['stages']['LT']
        ht = self.r['stages']['HT']
        Q_cond_lt = lt['mass_flow_kg_s'] * lt['q_cond']
        Q_evap_ht = ht['mass_flow_kg_s'] * ht['q_evap']
        assert _rel(Q_cond_lt, Q_evap_ht) < REL_TOL

    def test_cascade_hx_duty(self):
        assert len(self.r['cascade_hx_duties_W']) == 1
        assert _rel(self.r['cascade_hx_duties_W'][0],
                     self.ref['cascade_hx_duties_W'][0]) < REL_TOL

    def test_cop_formula(self):
        expected = 15000.0 / self.r['total_power_W']
        assert abs(self.r['system_COP'] - expected) < 1e-6

    def test_lt_state_enthalpies(self):
        for i in range(4):
            assert _rel(self.r['stages']['LT']['states'][i]['H'],
                        self.ref['stages']['LT']['states'][i]['H']) < REL_TOL

    def test_ht_state_enthalpies(self):
        for i in range(4):
            assert _rel(self.r['stages']['HT']['states'][i]['H'],
                        self.ref['stages']['HT']['states'][i]['H']) < REL_TOL

    def test_state_count_and_keys(self):
        for sid in ['LT', 'HT']:
            assert len(self.r['stages'][sid]['states']) == 4
            for st in self.r['stages'][sid]['states']:
                for k in ('T', 'P', 'H', 'S'):
                    assert k in st


# ===================================================================
# Plant B — 3-stage Ethane / R23 / Ammonia
# ===================================================================

class TestAnalyzePlantB:
    @classmethod
    def setup_class(cls):
        cls.r = _run(['analyze', '/app/plants/plant_b.json'])
        cls.ref = _ref_analyze(_load('/app/plants/plant_b.json'))

    def test_system_cop(self):
        assert _rel(self.r['system_COP'], self.ref['system_COP']) < REL_TOL

    def test_total_power(self):
        assert _rel(self.r['total_power_W'], self.ref['total_power_W']) < REL_TOL

    def test_three_stages_present(self):
        for sid in ['LT', 'MT', 'HT']:
            assert sid in self.r['stages']

    def test_lt_cop(self):
        assert _rel(self.r['stages']['LT']['COP'],
                     self.ref['stages']['LT']['COP']) < REL_TOL

    def test_mt_cop(self):
        assert _rel(self.r['stages']['MT']['COP'],
                     self.ref['stages']['MT']['COP']) < REL_TOL

    def test_ht_cop(self):
        assert _rel(self.r['stages']['HT']['COP'],
                     self.ref['stages']['HT']['COP']) < REL_TOL

    def test_mass_flows(self):
        for sid in ['LT', 'MT', 'HT']:
            assert _rel(self.r['stages'][sid]['mass_flow_kg_s'],
                        self.ref['stages'][sid]['mass_flow_kg_s']) < REL_TOL

    def test_two_cascade_duties(self):
        assert len(self.r['cascade_hx_duties_W']) == 2
        for i in range(2):
            assert _rel(self.r['cascade_hx_duties_W'][i],
                        self.ref['cascade_hx_duties_W'][i]) < REL_TOL

    def test_energy_balance_all(self):
        for sid in ['LT', 'MT', 'HT']:
            s = self.r['stages'][sid]
            assert _rel(s['q_cond'], s['q_evap'] + s['w_comp']) < 1e-6

    def test_hx1_balance(self):
        lt = self.r['stages']['LT']
        mt = self.r['stages']['MT']
        Q_lt = lt['mass_flow_kg_s'] * lt['q_cond']
        Q_mt = mt['mass_flow_kg_s'] * mt['q_evap']
        assert _rel(Q_lt, Q_mt) < REL_TOL

    def test_hx2_balance(self):
        mt = self.r['stages']['MT']
        ht = self.r['stages']['HT']
        Q_mt = mt['mass_flow_kg_s'] * mt['q_cond']
        Q_ht = ht['mass_flow_kg_s'] * ht['q_evap']
        assert _rel(Q_mt, Q_ht) < REL_TOL

    def test_w_total_consistency(self):
        W = sum(
            self.r['stages'][sid]['mass_flow_kg_s'] * self.r['stages'][sid]['w_comp']
            for sid in ['LT', 'MT', 'HT']
        )
        assert _rel(self.r['total_power_W'], W) < 1e-6

    def test_state_enthalpies(self):
        for sid in ['LT', 'MT', 'HT']:
            for i in range(4):
                assert _rel(
                    self.r['stages'][sid]['states'][i]['H'],
                    self.ref['stages'][sid]['states'][i]['H'],
                ) < REL_TOL


# ===================================================================
# Plant C — 2-stage R23 / R410A (near-critical HT condenser)
# ===================================================================

class TestAnalyzePlantC:
    @classmethod
    def setup_class(cls):
        cls.r = _run(['analyze', '/app/plants/plant_c.json'])
        cls.ref = _ref_analyze(_load('/app/plants/plant_c.json'))

    def test_system_cop(self):
        assert _rel(self.r['system_COP'], self.ref['system_COP']) < REL_TOL

    def test_total_power(self):
        assert _rel(self.r['total_power_W'], self.ref['total_power_W']) < REL_TOL

    def test_ht_cop(self):
        assert _rel(self.r['stages']['HT']['COP'],
                     self.ref['stages']['HT']['COP']) < REL_TOL

    def test_lt_cop(self):
        assert _rel(self.r['stages']['LT']['COP'],
                     self.ref['stages']['LT']['COP']) < REL_TOL

    def test_ht_pressure_ratio(self):
        assert _rel(self.r['stages']['HT']['pressure_ratio'],
                     self.ref['stages']['HT']['pressure_ratio']) < REL_TOL

    def test_ht_state_enthalpies(self):
        for i in range(4):
            assert _rel(
                self.r['stages']['HT']['states'][i]['H'],
                self.ref['stages']['HT']['states'][i]['H'],
            ) < REL_TOL

    def test_lt_state_enthalpies(self):
        for i in range(4):
            assert _rel(
                self.r['stages']['LT']['states'][i]['H'],
                self.ref['stages']['LT']['states'][i]['H'],
            ) < REL_TOL

    def test_energy_balance(self):
        for sid in ['LT', 'HT']:
            s = self.r['stages'][sid]
            assert _rel(s['q_cond'], s['q_evap'] + s['w_comp']) < 1e-6

    def test_near_critical_condenser_outlet(self):
        ht = self.r['stages']['HT']
        T3 = ht['states'][2]['T']
        assert abs(T3 - (333.15 - 5.0)) < 0.1

    def test_cascade_hx_balance(self):
        lt = self.r['stages']['LT']
        ht = self.r['stages']['HT']
        Q_lt = lt['mass_flow_kg_s'] * lt['q_cond']
        Q_ht = ht['mass_flow_kg_s'] * ht['q_evap']
        assert _rel(Q_lt, Q_ht) < REL_TOL

    def test_mass_flows(self):
        for sid in ['LT', 'HT']:
            assert _rel(self.r['stages'][sid]['mass_flow_kg_s'],
                        self.ref['stages'][sid]['mass_flow_kg_s']) < REL_TOL


# ===================================================================
# Optimize Plant B — 3-stage, 2 cascade temperatures
# ===================================================================

class TestOptimizePlantB:
    @classmethod
    def setup_class(cls):
        cls.r = _run(['optimize', '/app/plants/plant_b.json'])

    def test_has_keys(self):
        assert 'optimal_cascade_temperatures_K' in self.r
        assert 'maximum_COP' in self.r
        assert 'system' in self.r

    def test_two_temps(self):
        assert len(self.r['optimal_cascade_temperatures_K']) == 2

    def test_temps_ordered(self):
        t = self.r['optimal_cascade_temperatures_K']
        assert t[0] < t[1]

    def test_cop_matches_system(self):
        assert abs(self.r['maximum_COP'] - self.r['system']['system_COP']) < 1e-6

    def test_cop_positive(self):
        assert self.r['maximum_COP'] > 0

    def test_feasible_range(self):
        t = self.r['optimal_cascade_temperatures_K']
        assert t[0] > 183.15 + 10
        assert t[1] < 308.15 - 10
        assert t[0] < t[1]

    def test_optimality_coarse(self):
        """COP at optimum >= COP at coarsely perturbed points."""
        plant = _load('/app/plants/plant_b.json')
        T_opt = self.r['optimal_cascade_temperatures_K']
        cop_max = self.r['maximum_COP']
        for d1 in [-8, -4, 0, 4, 8]:
            for d2 in [-8, -4, 0, 4, 8]:
                if d1 == 0 and d2 == 0:
                    continue
                T_test = [T_opt[0] + d1, T_opt[1] + d2]
                if T_test[0] >= T_test[1] - 10:
                    continue
                try:
                    p = dict(plant)
                    p['cascade_temperatures_K'] = T_test
                    ref = _ref_analyze(p)
                    cop_perturbed = ref['system_COP']
                except Exception:
                    continue
                assert cop_max >= cop_perturbed - 1e-3, (
                    f"COP at T={T_test} ({cop_perturbed:.6f}) > "
                    f"max ({cop_max:.6f})"
                )

    def test_optimality_fine(self):
        """COP at optimum >= COP at finely perturbed points."""
        plant = _load('/app/plants/plant_b.json')
        T_opt = self.r['optimal_cascade_temperatures_K']
        cop_max = self.r['maximum_COP']
        for d1 in [-1.0, -0.5, 0, 0.5, 1.0]:
            for d2 in [-1.0, -0.5, 0, 0.5, 1.0]:
                if d1 == 0 and d2 == 0:
                    continue
                T_test = [T_opt[0] + d1, T_opt[1] + d2]
                if T_test[0] >= T_test[1] - 10:
                    continue
                try:
                    p = dict(plant)
                    p['cascade_temperatures_K'] = T_test
                    ref = _ref_analyze(p)
                    cop_perturbed = ref['system_COP']
                except Exception:
                    continue
                assert cop_max >= cop_perturbed - 1e-3

    def test_system_energy_balance(self):
        """Energy balance holds at the optimized operating point."""
        sys = self.r['system']
        for sid in ['LT', 'MT', 'HT']:
            s = sys['stages'][sid]
            assert _rel(s['q_cond'], s['q_evap'] + s['w_comp']) < 1e-6


# ===================================================================
# Diagnose Plant A — back-calculate degraded compressor efficiencies
# ===================================================================

class TestDiagnosePlantA:
    @classmethod
    def setup_class(cls):
        cls.r = _run(['diagnose', '/app/plants/plant_a.json',
                       '/app/commissioning/plant_a_field.json'])
        cls.ref = _ref_diagnose(
            _load('/app/plants/plant_a.json'),
            _load('/app/commissioning/plant_a_field.json'),
        )

    def test_has_keys(self):
        assert 'actual_efficiencies' in self.r
        assert 'efficiency_deviations' in self.r

    def test_lt_efficiency(self):
        assert _rel(self.r['actual_efficiencies']['LT'],
                     self.ref['actual_efficiencies']['LT']) < REL_TOL

    def test_ht_efficiency(self):
        assert _rel(self.r['actual_efficiencies']['HT'],
                     self.ref['actual_efficiencies']['HT']) < REL_TOL

    def test_lt_deviation(self):
        assert abs(self.r['efficiency_deviations']['LT']
                    - self.ref['efficiency_deviations']['LT']) < 1e-4

    def test_ht_deviation(self):
        assert abs(self.r['efficiency_deviations']['HT']
                    - self.ref['efficiency_deviations']['HT']) < 1e-4

    def test_efficiencies_degraded(self):
        plant = _load('/app/plants/plant_a.json')
        for s in plant['stages']:
            assert self.r['actual_efficiencies'][s['id']] < \
                   s['compressor']['isentropic_efficiency']

    def test_efficiencies_valid_range(self):
        for sid in self.r['actual_efficiencies']:
            eta = self.r['actual_efficiencies'][sid]
            assert 0.1 < eta < 1.0, f"Stage {sid} efficiency {eta} out of range"

    def test_both_stages_present(self):
        assert 'LT' in self.r['actual_efficiencies']
        assert 'HT' in self.r['actual_efficiencies']
        assert 'LT' in self.r['efficiency_deviations']
        assert 'HT' in self.r['efficiency_deviations']
