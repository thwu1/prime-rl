"""
Tests for systemd ExecStart tokenizer and service file fixes.

"""
import subprocess
import tempfile
import os
import re
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_tokenizer(input_text):
    """Run /app/sd_tokenize.sh with given input, return stdout."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(input_text)
        f.flush()
        fname = f.name
    try:
        result = subprocess.run(
            ['/app/sd_tokenize.sh', fname],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout
    finally:
        os.unlink(fname)


def parse_blocks(output):
    """Parse tokenizer output into list of {prefixes, argv} dicts."""
    blocks = []
    current = None
    for line in output.strip().split('\n'):
        line = line.rstrip()
        if line.startswith('PREFIXES:'):
            current = {'prefixes': line[len('PREFIXES:'):], 'argv': []}
        elif line.startswith('ARGV['):
            # Extract value after the colon following ARGV[N]
            colon = line.index(':')
            val = line[colon+1:]
            if current is not None:
                current['argv'].append(val)
        elif line == '---':
            if current is not None:
                blocks.append(current)
                current = None
    return blocks


def normalize_path(p):
    """Normalize /bin/X to /usr/bin/X for systems where /bin -> /usr/bin."""
    if p.startswith('/bin/'):
        alt = '/usr/bin/' + p[5:]
        return alt
    return p


def assert_argv_match(expected_argv, actual_argv):
    """Compare argv lists, normalizing /bin/ vs /usr/bin/ for the command."""
    assert len(actual_argv) == len(expected_argv), \
        f"Argument count mismatch: expected {len(expected_argv)}, got {len(actual_argv)}\n" \
        f"  expected: {expected_argv}\n  actual: {actual_argv}"
    for i, (exp, act) in enumerate(zip(expected_argv, actual_argv)):
        if i == 0:
            # Normalize command path
            assert normalize_path(act) == normalize_path(exp), \
                f"ARGV[{i}] mismatch: expected {exp}, got {act}"
        else:
            assert act == exp, \
                f"ARGV[{i}] mismatch: expected {exp!r}, got {act!r}"


# ---------------------------------------------------------------------------
# Tokenizer tests — derived from systemd.service(5) man page examples
# ---------------------------------------------------------------------------

class TestTokenizerManPageExamples:
    """Tests based on canonical examples from the systemd.service(5) man page."""

    def test_basic_var_expansion(self):
        """Man page example: $VAR splitting and ${VAR} exact substitution."""
        inp = """Environment="ONE=one" 'TWO=two two'
ExecStart=echo $ONE $TWO ${TWO}
"""
        blocks = parse_blocks(run_tokenizer(inp))
        assert len(blocks) == 1
        b = blocks[0]
        assert b['prefixes'] == 'NONE'
        assert_argv_match(
            ['/usr/bin/echo', 'one', 'two', 'two', 'two two'],
            b['argv']
        )

    def test_braced_with_literal_quotes(self):
        """Man page example: ${VAR} preserves literal quotes in value."""
        inp = """Environment=ONE='one' "TWO='two two' too" THREE=
ExecStart=/bin/echo ${ONE} ${TWO} ${THREE}
"""
        blocks = parse_blocks(run_tokenizer(inp))
        assert len(blocks) == 1
        b = blocks[0]
        assert b['prefixes'] == 'NONE'
        assert_argv_match(
            ['/bin/echo', "'one'", "'two two' too", ''],
            b['argv']
        )

    def test_unbraced_splitting_with_quotes(self):
        """Man page example: $VAR re-tokenizes value respecting quotes."""
        inp = """Environment=ONE='one' "TWO='two two' too" THREE=
ExecStart=/bin/echo $ONE $TWO $THREE
"""
        blocks = parse_blocks(run_tokenizer(inp))
        assert len(blocks) == 1
        b = blocks[0]
        assert b['prefixes'] == 'NONE'
        # $ONE='one' -> unquoted split respecting single quotes -> "one"
        # $TWO="'two two' too" -> split respecting quotes -> "two two", "too"
        # $THREE="" -> zero args
        assert_argv_match(
            ['/bin/echo', 'one', 'two two', 'too'],
            b['argv']
        )

    def test_colon_suppresses_expansion(self):
        """Man page example: : prefix makes $USER literal."""
        inp = """ExecStart=:echo $USER
"""
        blocks = parse_blocks(run_tokenizer(inp))
        assert len(blocks) == 1
        b = blocks[0]
        assert ':' in b['prefixes']
        assert_argv_match(
            ['/usr/bin/echo', '$USER'],
            b['argv']
        )

    def test_dash_prefix(self):
        """Man page example: - prefix, failure ignored."""
        inp = """ExecStart=-/bin/false
"""
        blocks = parse_blocks(run_tokenizer(inp))
        assert len(blocks) == 1
        b = blocks[0]
        assert '-' in b['prefixes']
        assert_argv_match(['/bin/false'], b['argv'])

    def test_combined_prefixes(self):
        """Man page example: +, :, @ combined — elevated, no expansion, argv[0] override."""
        inp = """ExecStart=+:@/bin/true $TEST
"""
        blocks = parse_blocks(run_tokenizer(inp))
        assert len(blocks) == 1
        b = blocks[0]
        # Prefixes should include +, :, @
        for p in ['+', ':', '@']:
            assert p in b['prefixes'], f"Missing prefix {p}"
        # : suppresses expansion, so $TEST stays literal
        assert_argv_match(['/bin/true', '$TEST'], b['argv'])

    def test_literal_metacharacters(self):
        """Man page example: >, &, ; are NOT shell metacharacters in systemd."""
        inp = """ExecStart=echo / >/dev/null & \\; \\
ls
"""
        blocks = parse_blocks(run_tokenizer(inp))
        assert len(blocks) == 1
        b = blocks[0]
        assert b['prefixes'] == 'NONE'
        assert_argv_match(
            ['/usr/bin/echo', '/', '>/dev/null', '&', ';', 'ls'],
            b['argv']
        )


class TestTokenizerEdgeCases:
    """Tests for additional documented edge cases."""

    def test_dollar_escape_with_braced_var(self):
        """$$ produces literal $, ${VAR} expands inline."""
        inp = """Environment="PRICE=10"
ExecStart=/bin/echo $$${PRICE} total
"""
        blocks = parse_blocks(run_tokenizer(inp))
        assert len(blocks) == 1
        b = blocks[0]
        assert_argv_match(['/bin/echo', '$10', 'total'], b['argv'])

    def test_braced_var_in_middle_of_word(self):
        """${VAR} embedded in a larger token."""
        inp = """Environment="HOST=example.com"
ExecStart=/bin/echo http://${HOST}/api
"""
        blocks = parse_blocks(run_tokenizer(inp))
        assert len(blocks) == 1
        assert_argv_match(
            ['/bin/echo', 'http://example.com/api'],
            blocks[0]['argv']
        )

    def test_undefined_braced_produces_empty(self):
        """${UNDEFINED} produces an empty-string argument."""
        inp = """ExecStart=/bin/echo ${UNDEFINED_VAR} end
"""
        blocks = parse_blocks(run_tokenizer(inp))
        assert len(blocks) == 1
        b = blocks[0]
        assert len(b['argv']) == 3  # echo, "", end
        assert b['argv'][0] in ('/bin/echo', '/usr/bin/echo')
        assert b['argv'][1] == ''
        assert b['argv'][2] == 'end'

    def test_undefined_unbraced_produces_nothing(self):
        """$UNDEFINED as standalone word produces zero arguments."""
        inp = """ExecStart=/bin/echo $UNDEFINED_VAR end
"""
        blocks = parse_blocks(run_tokenizer(inp))
        assert len(blocks) == 1
        b = blocks[0]
        # $UNDEFINED_VAR -> zero args, so total is echo + end = 2
        assert len(b['argv']) == 2
        assert b['argv'][1] == 'end'

    def test_multiple_environment_lines(self):
        """Multiple Environment= lines accumulate variables."""
        inp = """Environment="A=hello"
Environment="B=world"
ExecStart=/bin/echo ${A} ${B}
"""
        blocks = parse_blocks(run_tokenizer(inp))
        assert len(blocks) == 1
        assert_argv_match(['/bin/echo', 'hello', 'world'], blocks[0]['argv'])

    def test_c_escape_tab(self):
        """Double-quoted \\t produces a real tab character."""
        inp = r"""ExecStart=/bin/echo "hello\tworld"
"""
        blocks = parse_blocks(run_tokenizer(inp))
        assert len(blocks) == 1
        assert_argv_match(['/bin/echo', 'hello\tworld'], blocks[0]['argv'])

    def test_empty_braced_var(self):
        """${EMPTY} where EMPTY="" produces one empty argument."""
        inp = """Environment="EMPTY="
ExecStart=/bin/echo ${EMPTY} end
"""
        blocks = parse_blocks(run_tokenizer(inp))
        assert len(blocks) == 1
        b = blocks[0]
        assert len(b['argv']) == 3
        assert b['argv'][1] == ''
        assert b['argv'][2] == 'end'

    def test_path_resolution(self):
        """Simple command name is resolved to an absolute path."""
        inp = """ExecStart=echo hello
"""
        blocks = parse_blocks(run_tokenizer(inp))
        assert len(blocks) == 1
        b = blocks[0]
        # echo should resolve to /usr/bin/echo or /bin/echo
        assert b['argv'][0] in ('/usr/bin/echo', '/bin/echo'), \
            f"Unexpected resolved path: {b['argv'][0]}"
        assert b['argv'][1] == 'hello'


# ---------------------------------------------------------------------------
# Service-fix tests
# ---------------------------------------------------------------------------

class TestServiceFixes:
    """Tests verifying the corrected service files."""

    def _read_fixed(self, name):
        path = f'/app/fixed/{name}'
        assert os.path.isfile(path), f"Missing fixed service: {path}"
        with open(path) as f:
            return f.read()

    def test_data_pipeline_uses_shell(self):
        """data-pipeline.service must wrap pipe/redirect in a shell invocation."""
        content = self._read_fixed('data-pipeline.service')
        # Should NOT have bare | or > outside of shell wrapping
        exec_lines = [l.strip() for l in content.split('\n')
                      if l.strip().startswith('ExecStart=')]
        assert len(exec_lines) >= 1
        for line in exec_lines:
            val = line.split('=', 1)[1]
            # Must use sh -c or reference a wrapper script
            uses_shell = ('sh -c' in val or 'sh  -c' in val or
                          '/app/fixed/scripts/' in val)
            assert uses_shell, \
                f"ExecStart must use shell invocation or wrapper script, got: {val}"

    def test_app_server_var_expansion(self):
        """app-server.service must use $JVM_OPTS (split) and ${CONFIG_FILE} (exact)."""
        content = self._read_fixed('app-server.service')
        exec_lines = [l.strip() for l in content.split('\n')
                      if l.strip().startswith('ExecStart=')]
        assert len(exec_lines) >= 1
        exec_val = exec_lines[0].split('=', 1)[1]
        # Strip any prefixes
        stripped = exec_val.lstrip('@-:+!|')

        # JVM_OPTS should be unbraced $JVM_OPTS for splitting
        assert '${JVM_OPTS}' not in stripped, \
            "JVM_OPTS must use $JVM_OPTS (not ${JVM_OPTS}) for word splitting"
        # CONFIG_FILE should be braced ${CONFIG_FILE} for preservation
        # Check that $CONFIG_FILE is NOT used as standalone (unbraced)
        # Allow ${CONFIG_FILE} or a wrapper that handles it
        if 'CONFIG_FILE' in stripped:
            assert '${CONFIG_FILE}' in stripped or '/app/fixed/scripts/' in stripped, \
                "CONFIG_FILE must use ${CONFIG_FILE} to preserve spaces"

    def test_deploy_hook_no_colon_prefix(self):
        """deploy-hook.service ExecStart must NOT have : prefix (needs var expansion)."""
        content = self._read_fixed('deploy-hook.service')
        exec_lines = [l.strip() for l in content.split('\n')
                      if l.strip().startswith('ExecStart=')]
        assert len(exec_lines) >= 1
        val = exec_lines[0].split('=', 1)[1]
        # The prefix chars before the command path
        prefix_chars = ''
        for c in val:
            if c in '@-:+!|':
                prefix_chars += c
            else:
                break
        assert ':' not in prefix_chars, \
            f"ExecStart must not have : prefix (suppresses needed expansion), got prefixes: {prefix_chars}"

    def test_multi_step_structure(self):
        """multi-step.service must use ExecStartPre for init steps, not multiple ExecStart with Type=simple."""
        content = self._read_fixed('multi-step.service')

        exec_start_lines = [l.strip() for l in content.split('\n')
                            if l.strip().startswith('ExecStart=') and
                            not l.strip().startswith('ExecStartPre=') and
                            not l.strip().startswith('ExecStartPost=')]
        exec_pre_lines = [l.strip() for l in content.split('\n')
                          if l.strip().startswith('ExecStartPre=')]

        # Should have ExecStartPre for init steps
        assert len(exec_pre_lines) >= 2, \
            f"Expected at least 2 ExecStartPre lines for init steps, got {len(exec_pre_lines)}"
        # Should have exactly 1 ExecStart for the main long-running process
        assert len(exec_start_lines) == 1, \
            f"Expected exactly 1 ExecStart for main process, got {len(exec_start_lines)}"

        # Verify Type is not oneshot (main process is long-running) unless
        # they restructured the approach. If Type=simple, only 1 ExecStart allowed.
        type_lines = [l.strip() for l in content.split('\n')
                      if l.strip().startswith('Type=')]
        if type_lines:
            type_val = type_lines[-1].split('=', 1)[1].strip()
            if type_val == 'simple':
                assert len(exec_start_lines) == 1

    def test_healthcheck_no_shell_constructs(self):
        """healthcheck.service must not have bare && or shell loops in Exec directives."""
        content = self._read_fixed('healthcheck.service')

        exec_pre_lines = [l.strip() for l in content.split('\n')
                          if l.strip().startswith('ExecStartPre=')]
        exec_post_lines = [l.strip() for l in content.split('\n')
                           if l.strip().startswith('ExecStartPost=')]

        # Should have separate ExecStartPre lines (no && chaining)
        assert len(exec_pre_lines) >= 2, \
            "check-deps and migrate-db must be separate ExecStartPre lines"
        for line in exec_pre_lines:
            val = line.split('=', 1)[1]
            assert '&&' not in val, f"ExecStartPre must not contain &&: {val}"

        # ExecStartPost should use shell or wrapper (no bare while/do/done)
        assert len(exec_post_lines) >= 1
        for line in exec_post_lines:
            val = line.split('=', 1)[1]
            has_bare_shell = (val.lstrip('@-:+!|').startswith('while ') or
                              val.lstrip('@-:+!|').startswith('for ') or
                              val.lstrip('@-:+!|').startswith('if '))
            assert not has_bare_shell, \
                f"ExecStartPost must not use bare shell syntax: {val}"

    def test_healthcheck_wrapper_exists(self):
        """healthcheck wrapper script must exist and be executable."""
        scripts_dir = '/app/fixed/scripts'
        assert os.path.isdir(scripts_dir), f"Missing scripts directory: {scripts_dir}"
        # Find any .sh file in scripts/ that relates to healthcheck
        scripts = [f for f in os.listdir(scripts_dir)
                   if f.endswith('.sh') and 'health' in f.lower()]
        assert len(scripts) >= 1, \
            "Expected a healthcheck wrapper script in /app/fixed/scripts/"
        for s in scripts:
            path = os.path.join(scripts_dir, s)
            assert os.access(path, os.X_OK), f"Wrapper script not executable: {path}"

    def test_all_fixed_services_exist(self):
        """All 5 corrected service files must exist."""
        expected = [
            'data-pipeline.service',
            'app-server.service',
            'deploy-hook.service',
            'multi-step.service',
            'healthcheck.service',
        ]
        for name in expected:
            path = f'/app/fixed/{name}'
            assert os.path.isfile(path), f"Missing fixed service file: {path}"

    def test_systemd_analyze_verify(self):
        """Fixed service files should pass systemd-analyze verify (basic syntax)."""
        fixed_dir = '/app/fixed'
        services = [f for f in os.listdir(fixed_dir) if f.endswith('.service')]
        assert len(services) >= 5

        for svc in services:
            path = os.path.join(fixed_dir, svc)
            result = subprocess.run(
                ['systemd-analyze', '--user', 'verify', path],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, 'SYSTEMD_LOG_LEVEL': 'warning'}
            )
            # systemd-analyze verify returns 0 for valid files
            # It may warn about missing targets/services which is OK
            # We check it doesn't fail with parsing errors
            stderr = result.stderr.lower()
            parsing_errors = [
                'failed to parse',
                'invalid',
                'unknown section',
                'executable path is not absolute',
            ]
            for err in parsing_errors:
                if err in stderr:
                    # Check it's not just a warning about missing referenced units
                    lines_with_err = [l for l in result.stderr.split('\n')
                                      if err in l.lower()]
                    for line in lines_with_err:
                        # Skip warnings about missing dependency units
                        if any(skip in line.lower() for skip in
                               ['network.target', 'multi-user.target',
                                'postgresql.service', 'not found']):
                            continue
                        pytest.fail(
                            f"systemd-analyze verify found parsing error in {svc}: {line}")
