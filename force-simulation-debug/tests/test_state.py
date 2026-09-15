
import subprocess
import json
import math
import pytest
import os


DELTA = 1e-6


def run_scenario(scenario: str) -> any:
    """Run a simulation scenario and return parsed JSON output."""
    result = subprocess.run(
        ['npx', 'ts-node', '/app/src/run.ts', scenario],
        capture_output=True, text=True, cwd='/app', timeout=120
    )
    assert result.returncode == 0, (
        f"Scenario '{scenario}' failed with exit code {result.returncode}.\n"
        f"stderr: {result.stderr[:2000]}"
    )
    return json.loads(result.stdout)


def assert_near(actual: float, expected: float, delta: float = DELTA):
    assert abs(actual - expected) < delta, (
        f"Expected {expected}, got {actual} (diff={abs(actual - expected):.2e})"
    )


def assert_node(actual: dict, expected: dict, delta: float = DELTA):
    assert actual['index'] == expected['index'], (
        f"Index mismatch: {actual['index']} != {expected['index']}"
    )
    assert_near(actual['x'], expected['x'], delta)
    assert_near(actual['y'], expected['y'], delta)
    assert_near(actual['vx'], expected['vx'], delta)
    assert_near(actual['vy'], expected['vy'], delta)


class TestInitialization:
    """Test phyllotaxis node positioning."""

    def test_init_positions(self):
        nodes = run_scenario('init')
        assert len(nodes) == 5
        assert_node(nodes[0], {'index': 0, 'x': 7.0710678118654755, 'y': 0, 'vx': 0, 'vy': 0})
        assert_node(nodes[1], {'index': 1, 'x': -9.03088751750192, 'y': 8.273032735715967, 'vx': 0, 'vy': 0})
        assert_node(nodes[2], {'index': 2, 'x': 1.382322080982364, 'y': -15.75084714116763, 'vx': 0, 'vy': 0})
        assert_node(nodes[3], {'index': 3, 'x': 11.38284879290942, 'y': 14.84691056609962, 'vx': 0, 'vy': 0})
        assert_node(nodes[4], {'index': 4, 'x': -20.88892748977138, 'y': -3.694957148205299, 'vx': 0, 'vy': 0})


class TestNoForce:
    """Test simulation tick with no forces applied."""

    def test_positions_unchanged(self):
        nodes = run_scenario('noforce')
        assert len(nodes) == 3
        # With no forces and zero initial velocity, positions should not change
        assert_node(nodes[0], {'index': 0, 'x': 7.0710678118654755, 'y': 0, 'vx': 0, 'vy': 0})
        assert_node(nodes[1], {'index': 1, 'x': -9.03088751750192, 'y': 8.273032735715967, 'vx': 0, 'vy': 0})
        assert_node(nodes[2], {'index': 2, 'x': 1.382322080982364, 'y': -15.75084714116763, 'vx': 0, 'vy': 0})


class TestCenterForce:
    """Test center force centering behavior."""

    def test_center_positions(self):
        nodes = run_scenario('center')
        assert len(nodes) == 3
        assert_node(nodes[0], {'index': 0, 'x': 7.263567020083503, 'y': 2.492604801817222, 'vx': 0, 'vy': 0})
        assert_node(nodes[1], {'index': 1, 'x': -8.838388309283893, 'y': 10.76563753753319, 'vx': 0, 'vy': 0})
        assert_node(nodes[2], {'index': 2, 'x': 1.57482128920039, 'y': -13.25824233935041, 'vx': 0, 'vy': 0})

    def test_centroid_at_origin(self):
        nodes = run_scenario('center')
        cx = sum(n['x'] for n in nodes) / len(nodes)
        cy = sum(n['y'] for n in nodes) / len(nodes)
        assert_near(cx, 0, 1e-10)
        assert_near(cy, 0, 1e-10)


class TestXForce:
    """Test X-positioning force."""

    def test_xforce_positions(self):
        nodes = run_scenario('xforce')
        assert len(nodes) == 3
        assert_node(nodes[0], {
            'index': 0, 'x': 3.920700089978481, 'y': 0,
            'vx': -0.2334449879233752, 'vy': 0
        })
        assert_node(nodes[1], {
            'index': 1, 'x': -5.007362741316181, 'y': 8.273032735715967,
            'vx': 0.2981466849918966, 'vy': 0
        })
        assert_node(nodes[2], {
            'index': 2, 'x': 0.7664571252155745, 'y': -15.75084714116763,
            'vx': -0.04563612881206548, 'vy': 0
        })


class TestLinkForce:
    """Test link spring constraints."""

    def test_link_positions(self):
        nodes = run_scenario('link')
        assert len(nodes) == 2
        assert_node(nodes[0], {
            'index': 0, 'x': 12.318670337437, 'y': -2.696168669583844,
            'vx': 0.02506700654202986, 'vy': -0.01287919146877715
        })
        assert_node(nodes[1], {
            'index': 1, 'x': -14.27849004307344, 'y': 10.96920140529981,
            'vx': -0.02506700654202986, 'vy': 0.01287919146877715
        })

    def test_link_symmetry(self):
        """Velocities should be equal and opposite for symmetric link."""
        nodes = run_scenario('link')
        assert_near(nodes[0]['vx'], -nodes[1]['vx'])
        assert_near(nodes[0]['vy'], -nodes[1]['vy'])


class TestManyBodyForce:
    """Test Barnes-Hut N-body repulsion."""

    def test_manybody_positions(self):
        nodes = run_scenario('manybody')
        assert len(nodes) == 3
        assert_node(nodes[0], {
            'index': 0, 'x': 16.03119554130782, 'y': 3.829172281545499,
            'vx': 0.6866357066799689, 'vy': 0.285300848392342
        })
        assert_node(nodes[1], {
            'index': 1, 'x': -17.12732616092218, 'y': 15.46193073821839,
            'vx': -0.6073704789717939, 'vy': 0.5137593656812403
        })
        assert_node(nodes[2], {
            'index': 2, 'x': 0.5186329949602733, 'y': -26.76891742521556,
            'vx': -0.0792652277081751, 'vy': -0.7990602140735823
        })

    def test_manybody_repulsion(self):
        """Nodes should be farther apart after repulsive many-body force."""
        nodes = run_scenario('manybody')
        # Check that nodes have moved outward from their initial positions
        init = run_scenario('init')
        for n_after, n_init in zip(nodes[:3], init[:3]):
            d_after = math.sqrt(n_after['x']**2 + n_after['y']**2)
            d_init = math.sqrt(n_init['x']**2 + n_init['y']**2)
            assert d_after > d_init, (
                f"Node {n_after['index']} should move outward: "
                f"dist_after={d_after:.4f}, dist_init={d_init:.4f}"
            )


class TestCollideForce:
    """Test collision detection and resolution."""

    def test_collide_separation(self):
        """All nodes starting at origin should separate after collision force."""
        nodes = run_scenario('collide')
        assert len(nodes) == 10
        radius = 5
        # After collision resolution, no two nodes should significantly overlap
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                dx = nodes[i]['x'] - nodes[j]['x']
                dy = nodes[i]['y'] - nodes[j]['y']
                dist = math.sqrt(dx * dx + dy * dy)
                # Allow 20% tolerance since 50 ticks may not fully resolve
                assert dist > 2 * radius * 0.8, (
                    f"Nodes {i} and {j} overlap: dist={dist:.4f}, "
                    f"min_expected={2 * radius * 0.8:.4f}"
                )

    def test_collide_determinism(self):
        """Collision should produce identical results on repeated runs."""
        nodes1 = run_scenario('collide')
        nodes2 = run_scenario('collide')
        for n1, n2 in zip(nodes1, nodes2):
            assert_node(n1, n2)

    def test_collide_nonzero_displacement(self):
        """Nodes at origin should have moved after collision."""
        nodes = run_scenario('collide')
        for n in nodes:
            dist = math.sqrt(n['x']**2 + n['y']**2)
            assert dist > 1.0, f"Node {n['index']} barely moved: dist={dist}"


class TestCombinedForces:
    """Test simulation with center + manyBody + link forces together."""

    def test_combined_positions(self):
        nodes = run_scenario('combined')
        assert len(nodes) == 5
        assert_node(nodes[0], {
            'index': 0, 'x': 19.31404621742772, 'y': -1.759380660840612,
            'vx': 0.2800985491651357, 'vy': 0.2304260702319419
        })
        assert_node(nodes[1], {
            'index': 1, 'x': -8.905568647248161, 'y': 10.736504403924,
            'vx': 0.09386448407820543, 'vy': 0.0731899808445728
        })
        assert_node(nodes[2], {
            'index': 2, 'x': 2.119360287828454, 'y': -20.65825590007083,
            'vx': 0.001572896181451167, 'vy': 0.03910893969499503
        })
        assert_node(nodes[3], {
            'index': 3, 'x': 7.793841121295525, 'y': 13.57005302123706,
            'vx': -0.1414457415140576, 'vy': 0.1321367290338175
        })
        assert_node(nodes[4], {
            'index': 4, 'x': -20.33649170379408, 'y': -1.221885090106079,
            'vx': -0.2489029124012788, 'vy': 0.1921740543382107
        })

    def test_combined_centroid_near_origin(self):
        """Center force should keep centroid near origin."""
        nodes = run_scenario('combined')
        cx = sum(n['x'] for n in nodes) / len(nodes)
        cy = sum(n['y'] for n in nodes) / len(nodes)
        assert abs(cx) < 1.0, f"Centroid x too far from origin: {cx}"
        assert abs(cy) < 1.0, f"Centroid y too far from origin: {cy}"


class TestFixedPositions:
    """Test fixed-position constraint handling."""

    def test_fixed_node_stays(self):
        nodes = run_scenario('fixed')
        assert len(nodes) == 3
        # Node 0 is fixed at (5, 5)
        assert_near(nodes[0]['x'], 5.0)
        assert_near(nodes[0]['y'], 5.0)
        assert_near(nodes[0]['vx'], 0.0)
        assert_near(nodes[0]['vy'], 0.0)

    def test_fixed_other_nodes(self):
        nodes = run_scenario('fixed')
        assert_node(nodes[1], {
            'index': 1, 'x': -19.43352668571607, 'y': 15.24526397300625,
            'vx': -0.7727031733293153, 'vy': 0.5637687308734706
        })
        assert_node(nodes[2], {
            'index': 2, 'x': 2.778330757509846, 'y': -26.7102957898915,
            'vx': 0.1249546051064302, 'vy': -0.8536017903373809
        })

    def test_fixed_unfixed_move(self):
        """Unfixed nodes should move due to many-body repulsion."""
        nodes = run_scenario('fixed')
        init = run_scenario('init')
        for n in nodes[1:]:
            n_init = init[n['index']]
            assert n['x'] != n_init['x'] or n['y'] != n_init['y'], (
                f"Node {n['index']} should have moved"
            )
