#!/usr/bin/env python3
"""Compiler optimization regression test runner — FIXED.

Reads config.toml, compiles and runs test programs at multiple
optimization levels with multiple compilers, writes raw_results.json.
"""
import subprocess
import json
import os
import sys
import glob
import tomllib


def load_config(path):
    with open(path, 'rb') as f:
        return tomllib.load(f)


def compile_single(src, opt_level, compiler, output):
    """Compile a single-file test program."""
    cmd = [compiler, opt_level, '-o', output, src, '-lm', '-w']
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode == 0, result.stderr


def compile_separate(caller, callee, opt_level, compiler, output):
    """Compile caller/callee as separate translation units and link."""
    callee_o = output + '_callee.o'
    caller_o = output + '_caller.o'

    r1 = subprocess.run(
        [compiler, opt_level, '-c', callee, '-o', callee_o, '-w'],
        capture_output=True, text=True, timeout=30
    )
    if r1.returncode != 0:
        return False, r1.stderr

    r2 = subprocess.run(
        [compiler, opt_level, '-c', caller, '-o', caller_o, '-w'],
        capture_output=True, text=True, timeout=30
    )
    if r2.returncode != 0:
        return False, r2.stderr

    r3 = subprocess.run(
        [compiler, callee_o, caller_o, '-o', output, '-lm', '-w'],
        capture_output=True, text=True, timeout=30
    )
    for tmp in [callee_o, caller_o]:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return r3.returncode == 0, r3.stderr


def run_binary(binary, timeout=10):
    """Execute a compiled binary and return its exit code."""
    try:
        result = subprocess.run(
            [binary], capture_output=True, text=True, timeout=timeout
        )
        return result.returncode
    except subprocess.TimeoutExpired:
        return -1


def run_category(cat_name, cat_config, opt_levels):
    """Run all tests in a single category."""
    test_dir = cat_config['path']
    compiler = cat_config.get('compiler', 'gcc')
    separate = cat_config.get('separate_compilation', False)

    if not os.path.isdir(test_dir):
        print(f"  Warning: directory {test_dir} not found, skipping {cat_name}")
        return None

    results = {'tests': []}

    if separate:
        callee_files = sorted(glob.glob(os.path.join(test_dir, '*_callee.c')))
        for callee in callee_files:
            prefix = callee.replace('_callee.c', '')
            caller = prefix + '_caller.c'
            if not os.path.exists(caller):
                continue
            test_name = os.path.basename(prefix)
            test_result = {'name': test_name, 'levels': {}}
            for opt in opt_levels:
                binary = f'/tmp/{cat_name}_{test_name}_{opt.replace("-", "")}'
                ok, err = compile_separate(caller, callee, opt, compiler, binary)
                if ok:
                    exit_code = run_binary(binary)
                    test_result['levels'][opt] = {
                        'compiled': True, 'exit_code': exit_code
                    }
                else:
                    test_result['levels'][opt] = {
                        'compiled': False, 'error': err
                    }
                if os.path.exists(binary):
                    os.unlink(binary)
            results['tests'].append(test_result)
    else:
        c_files = sorted(glob.glob(os.path.join(test_dir, '*.c')))
        for c_file in c_files:
            test_name = os.path.basename(c_file)
            test_result = {'name': test_name, 'levels': {}}
            for opt in opt_levels:
                binary = f'/tmp/{cat_name}_{test_name}_{opt.replace("-", "")}'
                ok, err = compile_single(c_file, opt, compiler, binary)
                if ok:
                    exit_code = run_binary(binary)
                    test_result['levels'][opt] = {
                        'compiled': True, 'exit_code': exit_code
                    }
                else:
                    test_result['levels'][opt] = {
                        'compiled': False, 'error': err
                    }
                if os.path.exists(binary):
                    os.unlink(binary)
            results['tests'].append(test_result)

    return results


def main():
    config = load_config('/app/config.toml')
    opt_levels = config['general']['opt_levels']
    compilers = config['general'].get('compilers', ['gcc'])

    all_results = {}
    for compiler_name in compilers:
        compiler_results = {}
        for cat_name, cat_config in config['categories'].items():
            modified_config = dict(cat_config)
            modified_config['compiler'] = compiler_name
            print(f"Running {cat_name} with {compiler_name}")
            result = run_category(cat_name, modified_config, opt_levels)
            if result is not None:
                compiler_results[cat_name] = result
        all_results[compiler_name] = compiler_results

    with open('/app/raw_results.json', 'w') as f:
        json.dump(all_results, f, indent=2)

    print(f"\nResults written to /app/raw_results.json")
    for comp, comp_data in all_results.items():
        print(f"  {comp}:")
        for cat, data in comp_data.items():
            n = len(data['tests'])
            print(f"    {cat}: {n} tests")


if __name__ == '__main__':
    main()
