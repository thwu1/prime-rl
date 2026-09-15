
import sqlite3


def load_gpu_specs(db_path):
    """Load GPU hardware specifications from the database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    gpu_specs = {}
    for name, value, unit in c.execute(
            'SELECT spec_name, spec_value, unit FROM gpu_specs'):
        gpu_specs[name] = value
    conn.close()
    return gpu_specs


def load_kernel_configs(db_path):
    """Load kernel tuning configurations from the database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    configs = []
    for row in c.execute(
            'SELECT config_id, block_m, block_n, block_k, '
            'group_size_m, num_stages, num_warps '
            'FROM kernel_configs ORDER BY config_id'):
        configs.append({
            'config_id': row[0],
            'BLOCK_M': row[1],
            'BLOCK_N': row[2],
            'BLOCK_K': row[3],
            'GROUP_SIZE_M': row[4],
            'num_stages': row[5],
            'num_warps': row[6],
        })
    conn.close()
    return configs


def load_workloads(db_path):
    """Load workload definitions from the database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    workloads = []
    for row in c.execute(
            'SELECT dim_m, dim_n, dim_k FROM workloads ORDER BY workload_id'):
        workloads.append((row[0], row[1], row[2]))
    conn.close()
    return workloads
