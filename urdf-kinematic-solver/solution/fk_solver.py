#!/usr/bin/env python3
"""
URDF Forward Kinematics Solver for the WR-6 manipulator.
Parses robot.urdf, computes FK/Jacobian/max-reach, writes results.json.
"""


import json
import xml.etree.ElementTree as ET
import numpy as np
from scipy.optimize import minimize


def rot_x(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rot_y(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rot_z(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def rpy_to_rotation(roll, pitch, yaw):
    return rot_z(yaw) @ rot_y(pitch) @ rot_x(roll)


def axis_angle_rotation(axis, angle):
    axis = np.array(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0]
    ])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def make_transform(R, p):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = p
    return T


def parse_urdf(urdf_path):
    tree = ET.parse(urdf_path)
    root = tree.getroot()

    joints = {}
    for joint_elem in root.findall('joint'):
        name = joint_elem.get('name')
        jtype = joint_elem.get('type')
        parent = joint_elem.find('parent').get('link')
        child = joint_elem.find('child').get('link')

        origin = joint_elem.find('origin')
        xyz = [0.0, 0.0, 0.0]
        rpy = [0.0, 0.0, 0.0]
        if origin is not None:
            if origin.get('xyz'):
                xyz = list(map(float, origin.get('xyz').split()))
            if origin.get('rpy'):
                rpy = list(map(float, origin.get('rpy').split()))

        axis = [0.0, 0.0, 1.0]
        axis_elem = joint_elem.find('axis')
        if axis_elem is not None and axis_elem.get('xyz'):
            axis = list(map(float, axis_elem.get('xyz').split()))

        limits = {'lower': -np.pi, 'upper': np.pi}
        limit_elem = joint_elem.find('limit')
        if limit_elem is not None:
            if limit_elem.get('lower'):
                limits['lower'] = float(limit_elem.get('lower'))
            if limit_elem.get('upper'):
                limits['upper'] = float(limit_elem.get('upper'))

        joints[name] = {
            'name': name,
            'type': jtype,
            'parent': parent,
            'child': child,
            'xyz': xyz,
            'rpy': rpy,
            'axis': axis,
            'limits': limits,
        }

    return joints


def build_chain(joints, start_link, end_link):
    """Build ordered list of joints from start_link to end_link."""
    child_to_joint = {}
    for jname, jdata in joints.items():
        child_to_joint[jdata['child']] = jdata

    chain = []
    current = end_link
    while current != start_link:
        if current not in child_to_joint:
            raise ValueError(f"Cannot find path from {start_link} to {end_link}")
        j = child_to_joint[current]
        chain.append(j)
        current = j['parent']
    chain.reverse()
    return chain


def get_active_joints(chain):
    """Return ordered list of active (revolute/prismatic) joints in chain."""
    return [j for j in chain if j['type'] in ('revolute', 'continuous', 'prismatic')]


def compute_fk(chain, joint_values, joint_order):
    """Compute FK: returns 4x4 homogeneous transform from first parent to last child."""
    q_map = {}
    active = get_active_joints(chain)
    for i, j in enumerate(active):
        if i < len(joint_values):
            q_map[j['name']] = joint_values[i]

    T = np.eye(4)
    for j in chain:
        xyz = j['xyz']
        rpy = j['rpy']
        R_origin = rpy_to_rotation(rpy[0], rpy[1], rpy[2])
        T_origin = make_transform(R_origin, xyz)
        T = T @ T_origin

        if j['type'] in ('revolute', 'continuous'):
            q = q_map.get(j['name'], 0.0)
            R_joint = axis_angle_rotation(j['axis'], q)
            T_joint = make_transform(R_joint, [0, 0, 0])
            T = T @ T_joint
        elif j['type'] == 'prismatic':
            q = q_map.get(j['name'], 0.0)
            axis = np.array(j['axis'])
            T_joint = make_transform(np.eye(3), q * axis)
            T = T @ T_joint

    return T


def compute_joint_frames(chain, joint_values):
    """Compute position and axis direction (in world frame) for each active joint."""
    q_map = {}
    active = get_active_joints(chain)
    for i, j in enumerate(active):
        if i < len(joint_values):
            q_map[j['name']] = joint_values[i]

    frames = []
    T = np.eye(4)
    for j in chain:
        xyz = j['xyz']
        rpy = j['rpy']
        R_origin = rpy_to_rotation(rpy[0], rpy[1], rpy[2])
        T_origin = make_transform(R_origin, xyz)
        T = T @ T_origin

        if j['type'] in ('revolute', 'continuous'):
            axis_world = T[:3, :3] @ np.array(j['axis'])
            pos = T[:3, 3].copy()
            frames.append({'name': j['name'], 'axis': axis_world, 'pos': pos, 'type': 'revolute'})
            q = q_map.get(j['name'], 0.0)
            R_joint = axis_angle_rotation(j['axis'], q)
            T_joint = make_transform(R_joint, [0, 0, 0])
            T = T @ T_joint
        elif j['type'] == 'prismatic':
            axis_world = T[:3, :3] @ np.array(j['axis'])
            pos = T[:3, 3].copy()
            frames.append({'name': j['name'], 'axis': axis_world, 'pos': pos, 'type': 'prismatic'})
            q = q_map.get(j['name'], 0.0)
            T_joint = make_transform(np.eye(3), q * np.array(j['axis']))
            T = T @ T_joint

    return frames


def compute_geometric_jacobian(chain, joint_values, joint_order):
    """Compute 6x6 geometric Jacobian."""
    T_ee = compute_fk(chain, joint_values, joint_order)
    p_ee = T_ee[:3, 3]
    frames = compute_joint_frames(chain, joint_values)

    n = len(frames)
    J = np.zeros((6, n))
    for i, f in enumerate(frames):
        z = f['axis']
        p = f['pos']
        if f['type'] == 'revolute':
            J[:3, i] = np.cross(z, p_ee - p)
            J[3:, i] = z
        elif f['type'] == 'prismatic':
            J[:3, i] = z
            J[3:, i] = 0

    return J


def check_limits(joints_data, joint_names, joint_values):
    """Check if joint values are within limits."""
    violated = []
    for name, val in zip(joint_names, joint_values):
        if name in joints_data:
            j = joints_data[name]
            lo = j['limits']['lower']
            hi = j['limits']['upper']
            if val < lo - 1e-9 or val > hi + 1e-9:
                violated.append(name)
    return violated


def compute_max_reach(chain, joints_data, joint_order):
    """Compute maximum reach distance from base_link origin to tool0."""
    active = get_active_joints(chain)
    n = len(active)

    bounds = []
    for j in active:
        lo = j['limits']['lower']
        hi = j['limits']['upper']
        bounds.append((lo, hi))

    def neg_distance(q):
        T = compute_fk(chain, q, joint_order)
        p = T[:3, 3]
        return -np.linalg.norm(p)

    best = 0.0
    # Sample configurations and optimize from best ones
    np.random.seed(42)
    candidates = []
    # Try corners and random samples
    for _ in range(2000):
        q = np.array([np.random.uniform(lo, hi) for lo, hi in bounds])
        d = -neg_distance(q)
        candidates.append((d, q))

    # Also try key configurations
    special_configs = [
        [0, -np.pi/2, 0, 0, 0, 0],  # arm straight up
        [0, 0, 0, 0, 0, 0],          # arm horizontal
        [0, -np.pi/2, 0, np.pi/2, 0, 0],
        [0, -np.pi/2, 0, -np.pi/2, 0, 0],
        [0, np.pi/2, 0, 0, 0, 0],    # arm pointing down
    ]
    for sc in special_configs:
        d = -neg_distance(sc)
        candidates.append((d, sc))

    candidates.sort(key=lambda x: -x[0])

    for d, q0 in candidates[:20]:
        result = minimize(neg_distance, q0, method='L-BFGS-B', bounds=bounds)
        reach = -result.fun
        if reach > best:
            best = reach

    return best


def main():
    urdf_path = '/app/robot.urdf'
    queries_path = '/app/queries.json'
    output_path = '/app/output/results.json'

    joints_data = parse_urdf(urdf_path)
    with open(queries_path) as f:
        queries = json.load(f)

    joint_order = queries['joint_order']

    # Build chains
    chain_tool0 = build_chain(joints_data, 'base_link', 'tool0')
    chain_camera = build_chain(joints_data, 'base_link', 'camera_link')

    results = {}

    # Forward kinematics
    fk_results = {}
    for q in queries['forward_kinematics']:
        jv = q['joint_values']
        T = compute_fk(chain_tool0, jv, joint_order)
        pos = T[:3, 3].tolist()
        rot = T[:3, :3].tolist()
        violated = check_limits(joints_data, joint_order, jv)
        fk_results[q['id']] = {
            'position': pos,
            'rotation_matrix': rot,
            'within_limits': len(violated) == 0,
        }
    results['forward_kinematics'] = fk_results

    # Joint limit checks
    jl_results = {}
    for q in queries['joint_limit_checks']:
        jv = q['joint_values']
        violated = check_limits(joints_data, joint_order, jv)
        jl_results[q['id']] = {
            'within_limits': len(violated) == 0,
            'violated_joints': violated,
        }
    results['joint_limit_violations'] = jl_results

    # Frame transforms
    ft_query = queries['frame_transform']
    jv = ft_query['joint_values']
    T = compute_fk(chain_camera, jv, joint_order)
    results['frame_transforms'] = {
        ft_query['id']: {
            'position': T[:3, 3].tolist(),
            'rotation_matrix': T[:3, :3].tolist(),
        }
    }

    # Jacobian
    jac_query = queries['jacobian_query']
    jv = jac_query['joint_values']
    J = compute_geometric_jacobian(chain_tool0, jv, joint_order)
    results['jacobian'] = {
        jac_query['id']: J.tolist(),
    }

    # Max reach
    max_reach = compute_max_reach(chain_tool0, joints_data, joint_order)
    results['max_reach'] = max_reach

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Results written to {output_path}")


if __name__ == '__main__':
    main()
