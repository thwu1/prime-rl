
import json
import os
import pytest
import jsonschema

RESULTS_DIR = '/app/results'
QUERIES_PATH = '/app/queries.json'
SCHEMA_PATH = '/app/schema.json'
CONFIGS = ['workstation', 'server', 'router']

# ==================== Expected Values ====================

EXPECTED = {
    'workstation': {
        'tables': [{'name': 'filter', 'family': 'inet'}],
        'base_chains': {
            'input': {
                'table': 'filter', 'family': 'inet',
                'hook': 'input', 'priority': 0, 'policy': 'drop',
            },
            'forward': {
                'table': 'filter', 'family': 'inet',
                'hook': 'forward', 'priority': 0, 'policy': 'drop',
            },
            'output': {
                'table': 'filter', 'family': 'inet',
                'hook': 'output', 'priority': 0, 'policy': 'accept',
            },
        },
        'named_sets': {
            'LANv4': {
                'table': 'filter', 'family': 'inet',
                'type': 'ipv4_addr', 'flags': ['interval'],
                'elements': ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'],
            },
        },
        'jump_graph': {'input': ['lan_input']},
        'open_tcp_ports': [22],
        'open_udp_ports': [],
        'allows_loopback': True,
        'allows_icmp': True,
        'uses_connection_tracking': True,
        'has_rate_limiting': False,
        'rate_limited_ports': {},
        'has_nat': False,
        'has_masquerade': False,
        'anomalies': {
            'unreachable_chains': ['unused_filter'],
            'shadowed_rules': [],
        },
    },
    'server': {
        'tables': [{'name': 'filter', 'family': 'inet'}],
        'base_chains': {
            'input': {
                'table': 'filter', 'family': 'inet',
                'hook': 'input', 'priority': 0, 'policy': 'drop',
            },
            'forward': {
                'table': 'filter', 'family': 'inet',
                'hook': 'forward', 'priority': 0, 'policy': 'drop',
            },
            'output': {
                'table': 'filter', 'family': 'inet',
                'hook': 'output', 'priority': 0, 'policy': 'accept',
            },
        },
        'named_sets': {
            'blocked_ips': {
                'table': 'filter', 'family': 'inet',
                'type': 'ipv4_addr', 'flags': ['interval'],
                'elements': ['203.0.113.0/24', '198.51.100.0/24'],
            },
            'allowed_ssh': {
                'table': 'filter', 'family': 'inet',
                'type': 'ipv4_addr', 'flags': ['interval'],
                'elements': ['10.0.0.0/8', '172.16.0.0/12'],
            },
        },
        'jump_graph': {'input': ['rate_limit_ssh']},
        'open_tcp_ports': [53, 80, 443, 8080],
        'open_udp_ports': [53],
        'allows_loopback': True,
        'allows_icmp': True,
        'uses_connection_tracking': True,
        'has_rate_limiting': True,
        'rate_limited_ports': {'tcp': {'22': '5/minute'}},
        'has_nat': False,
        'has_masquerade': False,
        'anomalies': {
            'unreachable_chains': ['deprecated_logging'],
            'shadowed_rules': [
                {'table': 'filter', 'chain': 'input', 'position': 14},
            ],
        },
    },
    'router': {
        'tables': [
            {'name': 'filter', 'family': 'inet'},
            {'name': 'nat', 'family': 'inet'},
        ],
        'base_chains': {
            'input': {
                'table': 'filter', 'family': 'inet',
                'hook': 'input', 'priority': 0, 'policy': 'drop',
            },
            'forward': {
                'table': 'filter', 'family': 'inet',
                'hook': 'forward', 'priority': 0, 'policy': 'drop',
            },
            'output': {
                'table': 'filter', 'family': 'inet',
                'hook': 'output', 'priority': 0, 'policy': 'accept',
            },
            'prerouting': {
                'table': 'nat', 'family': 'inet',
                'hook': 'prerouting', 'priority': -100, 'policy': 'accept',
            },
            'postrouting': {
                'table': 'nat', 'family': 'inet',
                'hook': 'postrouting', 'priority': 100, 'policy': 'accept',
            },
        },
        'named_sets': {},
        'jump_graph': {'input': ['input_lan', 'input_wan']},
        'open_tcp_ports': [22, 53, 80, 443],
        'open_udp_ports': [53, 67],
        'allows_loopback': True,
        'allows_icmp': True,
        'uses_connection_tracking': True,
        'has_rate_limiting': True,
        'rate_limited_ports': {'tcp': {'22': '3/minute'}},
        'has_nat': True,
        'has_masquerade': True,
        'anomalies': {
            'unreachable_chains': [],
            'shadowed_rules': [
                {'table': 'filter', 'chain': 'input_wan', 'position': 5},
            ],
        },
    },
}


# ==================== Helpers ====================

def load_result(config_name):
    path = os.path.join(RESULTS_DIR, f'{config_name}.json')
    assert os.path.exists(path), f"Result file not found: {path}"
    with open(path) as f:
        return json.load(f)


def load_queries():
    with open(QUERIES_PATH) as f:
        return json.load(f)


def load_schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


# ==================== Schema Conformance ====================

class TestSchemaConformance:
    @pytest.mark.parametrize("config", CONFIGS)
    def test_output_conforms_to_schema(self, config):
        result = load_result(config)
        schema = load_schema()
        jsonschema.validate(instance=result, schema=schema)


# ==================== Structural Tests ====================

class TestTables:
    @pytest.mark.parametrize("config", CONFIGS)
    def test_tables(self, config):
        result = load_result(config)
        expected = EXPECTED[config]['tables']
        actual = sorted(result['tables'], key=lambda t: t['name'])
        expected_sorted = sorted(expected, key=lambda t: t['name'])
        assert actual == expected_sorted, (
            f"{config}: tables mismatch.\n"
            f"  Expected: {expected_sorted}\n"
            f"  Got:      {actual}"
        )


class TestBaseChains:
    @pytest.mark.parametrize("config", CONFIGS)
    def test_base_chains_exist(self, config):
        result = load_result(config)
        expected_names = set(EXPECTED[config]['base_chains'].keys())
        actual_names = set(result['base_chains'].keys())
        assert actual_names == expected_names, (
            f"{config}: base chain names mismatch.\n"
            f"  Expected: {expected_names}\n"
            f"  Got:      {actual_names}"
        )

    @pytest.mark.parametrize("config", CONFIGS)
    def test_base_chain_properties(self, config):
        result = load_result(config)
        for chain_name, expected_props in EXPECTED[config]['base_chains'].items():
            actual = result['base_chains'][chain_name]
            assert actual['hook'] == expected_props['hook'], (
                f"{config}/{chain_name}: hook mismatch"
            )
            assert actual['priority'] == expected_props['priority'], (
                f"{config}/{chain_name}: priority mismatch. "
                f"Expected {expected_props['priority']}, got {actual['priority']}"
            )
            assert actual['policy'] == expected_props['policy'], (
                f"{config}/{chain_name}: policy mismatch"
            )


class TestNamedSets:
    @pytest.mark.parametrize("config", CONFIGS)
    def test_named_sets(self, config):
        result = load_result(config)
        expected = EXPECTED[config]['named_sets']
        assert set(result['named_sets'].keys()) == set(expected.keys()), (
            f"{config}: named set names mismatch.\n"
            f"  Expected: {set(expected.keys())}\n"
            f"  Got:      {set(result['named_sets'].keys())}"
        )
        for set_name, expected_set in expected.items():
            actual_set = result['named_sets'][set_name]
            assert actual_set['type'] == expected_set['type'], (
                f"{config}/{set_name}: type mismatch"
            )
            assert sorted(actual_set['flags']) == sorted(expected_set['flags']), (
                f"{config}/{set_name}: flags mismatch"
            )
            assert sorted(actual_set['elements']) == sorted(expected_set['elements']), (
                f"{config}/{set_name}: elements mismatch"
            )


class TestJumpGraph:
    @pytest.mark.parametrize("config", CONFIGS)
    def test_jump_graph(self, config):
        result = load_result(config)
        expected = EXPECTED[config]['jump_graph']
        assert result['jump_graph'] == expected, (
            f"{config}: jump graph mismatch.\n"
            f"  Expected: {expected}\n"
            f"  Got:      {result['jump_graph']}"
        )


# ==================== Security Analysis Tests ====================

class TestOpenPorts:
    @pytest.mark.parametrize("config", CONFIGS)
    def test_open_tcp_ports(self, config):
        result = load_result(config)
        expected = EXPECTED[config]['open_tcp_ports']
        assert sorted(result['open_tcp_ports']) == sorted(expected), (
            f"{config}: open TCP ports mismatch.\n"
            f"  Expected: {expected}\n"
            f"  Got:      {result['open_tcp_ports']}"
        )

    @pytest.mark.parametrize("config", CONFIGS)
    def test_open_udp_ports(self, config):
        result = load_result(config)
        expected = EXPECTED[config]['open_udp_ports']
        assert sorted(result['open_udp_ports']) == sorted(expected), (
            f"{config}: open UDP ports mismatch.\n"
            f"  Expected: {expected}\n"
            f"  Got:      {result['open_udp_ports']}"
        )


class TestSecurityFlags:
    @pytest.mark.parametrize("config", CONFIGS)
    def test_allows_loopback(self, config):
        result = load_result(config)
        assert result['allows_loopback'] == EXPECTED[config]['allows_loopback']

    @pytest.mark.parametrize("config", CONFIGS)
    def test_allows_icmp(self, config):
        result = load_result(config)
        assert result['allows_icmp'] == EXPECTED[config]['allows_icmp']

    @pytest.mark.parametrize("config", CONFIGS)
    def test_uses_connection_tracking(self, config):
        result = load_result(config)
        assert result['uses_connection_tracking'] == \
            EXPECTED[config]['uses_connection_tracking']

    @pytest.mark.parametrize("config", CONFIGS)
    def test_has_rate_limiting(self, config):
        result = load_result(config)
        assert result['has_rate_limiting'] == \
            EXPECTED[config]['has_rate_limiting']

    @pytest.mark.parametrize("config", CONFIGS)
    def test_has_nat(self, config):
        result = load_result(config)
        assert result['has_nat'] == EXPECTED[config]['has_nat']

    @pytest.mark.parametrize("config", CONFIGS)
    def test_has_masquerade(self, config):
        result = load_result(config)
        assert result['has_masquerade'] == EXPECTED[config]['has_masquerade']


class TestRateLimitedPorts:
    @pytest.mark.parametrize("config", CONFIGS)
    def test_rate_limited_ports(self, config):
        result = load_result(config)
        expected = EXPECTED[config]['rate_limited_ports']
        assert result['rate_limited_ports'] == expected, (
            f"{config}: rate limited ports mismatch.\n"
            f"  Expected: {expected}\n"
            f"  Got:      {result['rate_limited_ports']}"
        )


# ==================== Packet Verdict Tests ====================

class TestPacketVerdicts:
    @pytest.fixture(autouse=True, scope='class')
    def _queries(self):
        TestPacketVerdicts._queries_data = load_queries()

    @pytest.mark.parametrize("config", CONFIGS)
    def test_all_packet_verdicts(self, config):
        result = load_result(config)
        packet_tests = self._queries_data['packet_tests'][config]
        verdicts = result.get('packet_verdicts', {})

        failures = []
        for test in packet_tests:
            test_id = test['id']
            expected = test['expected_verdict']
            actual = verdicts.get(test_id)
            if actual != expected:
                failures.append(
                    f"  {test_id} ({test['description']}): "
                    f"expected={expected}, got={actual}"
                )

        assert not failures, (
            f"{config}: packet verdict failures:\n" + "\n".join(failures)
        )

    @pytest.mark.parametrize("config", CONFIGS)
    def test_packet_verdict_count(self, config):
        result = load_result(config)
        packet_tests = self._queries_data['packet_tests'][config]
        verdicts = result.get('packet_verdicts', {})
        assert len(verdicts) == len(packet_tests), (
            f"{config}: expected {len(packet_tests)} packet verdicts, "
            f"got {len(verdicts)}"
        )


# ==================== Anomaly Detection Tests ====================

class TestAnomalies:
    @pytest.mark.parametrize("config", CONFIGS)
    def test_unreachable_chains(self, config):
        result = load_result(config)
        expected = EXPECTED[config]['anomalies']['unreachable_chains']
        actual = result.get('anomalies', {}).get('unreachable_chains', [])
        assert sorted(actual) == sorted(expected), (
            f"{config}: unreachable chains mismatch.\n"
            f"  Expected: {sorted(expected)}\n"
            f"  Got:      {sorted(actual)}"
        )

    @pytest.mark.parametrize("config", CONFIGS)
    def test_shadowed_rules(self, config):
        result = load_result(config)
        expected = EXPECTED[config]['anomalies']['shadowed_rules']
        actual = result.get('anomalies', {}).get('shadowed_rules', [])
        sort_key = lambda x: (x['table'], x['chain'], x['position'])
        assert sorted(actual, key=sort_key) == sorted(expected, key=sort_key), (
            f"{config}: shadowed rules mismatch.\n"
            f"  Expected: {sorted(expected, key=sort_key)}\n"
            f"  Got:      {sorted(actual, key=sort_key)}"
        )
