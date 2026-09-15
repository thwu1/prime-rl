"""
Test suite for TypeScript variance annotation correctness.

Verifies that the reactive library's generic types enforce correct
assignability rules through variance annotations and compiler configuration.
"""

import subprocess
import json
import os
import re
import tempfile

import pytest


# --- Helpers ---

def read_library_types() -> str:
    """Read all library source files and strip export keywords for standalone compilation."""
    src_dir = '/app/src'
    code_parts = []
    for fname in sorted(os.listdir(src_dir)):
        if fname.endswith('.ts') and fname != 'index.ts':
            path = os.path.join(src_dir, fname)
            with open(path) as f:
                content = f.read()
            content = re.sub(r'\bexport\s+', '', content)
            code_parts.append(f'// --- from {fname} ---\n{content}')
    return '\n\n'.join(code_parts)


TYPE_HIERARCHY = """
declare class Animal { _brand_animal: void; name: string; }
declare class Dog extends Animal { _brand_dog: void; breed: string; }
"""


def tsc_compile(code: str) -> tuple:
    """Compile TypeScript code with strict mode. Returns (returncode, output)."""
    fd, path = tempfile.mkstemp(suffix='.ts', dir='/tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(code)
        result = subprocess.run(
            ['tsc', '--noEmit', '--strict', '--strictFunctionTypes',
             '--target', 'ES2020', path],
            capture_output=True, text=True, timeout=60
        )
        return result.returncode, result.stdout + result.stderr
    finally:
        if os.path.exists(path):
            os.unlink(path)


def assert_compiles(code: str, msg: str = ""):
    rc, output = tsc_compile(code)
    assert rc == 0, f"Expected compilation to succeed: {msg}\ntsc output:\n{output}"


def assert_rejects(code: str, msg: str = ""):
    rc, output = tsc_compile(code)
    assert rc != 0, f"Expected compilation to fail: {msg}\nCode compiled when it should not have."


def split_type_params(s: str) -> list:
    """Split type parameters at top-level commas, handling nested < >."""
    params = []
    depth = 0
    current = []
    for ch in s:
        if ch == '<':
            depth += 1
            current.append(ch)
        elif ch == '>':
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            params.append(''.join(current))
            current = []
        else:
            current.append(ch)
    if current:
        params.append(''.join(current))
    return params


# --- Configuration Tests ---

class TestTsConfig:
    def test_strict_function_types_not_disabled(self):
        """strictFunctionTypes must not be explicitly disabled."""
        with open('/app/tsconfig.json') as f:
            config = json.load(f)
        opts = config.get('compilerOptions', {})
        if 'strictFunctionTypes' in opts:
            assert opts['strictFunctionTypes'] is not False, \
                "strictFunctionTypes must not be explicitly set to false"

    def test_strict_mode_enabled(self):
        """strict mode must be enabled."""
        with open('/app/tsconfig.json') as f:
            config = json.load(f)
        opts = config.get('compilerOptions', {})
        assert opts.get('strict', False) is True, \
            "strict mode must be enabled"


# --- Library Compilation Tests ---

class TestLibraryCompiles:
    def test_no_compilation_errors(self):
        """The library must compile with zero errors using its own tsconfig."""
        result = subprocess.run(
            ['tsc', '--noEmit', '--project', '/app/tsconfig.json'],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, \
            f"Library should compile without errors:\n{result.stdout}\n{result.stderr}"

    def test_source_files_exist(self):
        """All expected source files must exist."""
        expected = ['types.ts', 'events.ts', 'stream.ts', 'config.ts',
                    'transform.ts', 'codec.ts', 'middleware.ts', 'compose.ts', 'index.ts']
        for fname in expected:
            assert os.path.exists(f'/app/src/{fname}'), f"Missing source file: src/{fname}"


# --- Variance Annotation Presence Tests ---

class TestAnnotationsPresent:
    def test_all_exported_types_have_variance_annotations(self):
        """Every exported generic type parameter must have an explicit variance annotation."""
        src_dir = '/app/src'
        issues = []
        for fname in sorted(os.listdir(src_dir)):
            if not fname.endswith('.ts') or fname == 'index.ts':
                continue
            with open(os.path.join(src_dir, fname)) as f:
                content = f.read()
            for m in re.finditer(
                r'export\s+(?:type|interface)\s+(\w+)\s*<([^>]+)>', content
            ):
                type_name = m.group(1)
                params_str = m.group(2)
                params = split_type_params(params_str)
                for param in params:
                    param = param.strip()
                    if not param:
                        continue
                    if not re.match(r'(in\s+out|out|in)\s+', param):
                        issues.append(
                            f"{fname}: {type_name} parameter '{param.split()[0]}' "
                            f"lacks variance annotation"
                        )
        assert not issues, \
            "Missing variance annotations:\n" + "\n".join(issues)


# --- Provider<T> Tests (must be covariant) ---

class TestProviderCovariance:
    def test_subtype_to_supertype_valid(self):
        """Provider<Dog> must be assignable to Provider<Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let pa: Provider<Animal>;
declare let pd: Provider<Dog>;
pa = pd;
"""
        assert_compiles(code, "Provider should be covariant: Dog -> Animal")

    def test_supertype_to_subtype_rejected(self):
        """Provider<Animal> must NOT be assignable to Provider<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let pa: Provider<Animal>;
declare let pd: Provider<Dog>;
pd = pa;
"""
        assert_rejects(code, "Provider<Animal> must not be assignable to Provider<Dog>")


# --- Consumer<T> Tests (must be contravariant) ---

class TestConsumerContravariance:
    def test_supertype_to_subtype_valid(self):
        """Consumer<Animal> must be assignable to Consumer<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ca: Consumer<Animal>;
declare let cd: Consumer<Dog>;
cd = ca;
"""
        assert_compiles(code, "Consumer should be contravariant: Animal -> Dog")

    def test_subtype_to_supertype_rejected(self):
        """Consumer<Dog> must NOT be assignable to Consumer<Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ca: Consumer<Animal>;
declare let cd: Consumer<Dog>;
ca = cd;
"""
        assert_rejects(code, "Consumer<Dog> must not be assignable to Consumer<Animal>")


# --- Mapper<T, U> Tests (T contravariant, U covariant) ---

class TestMapperVariance:
    def test_valid_direction(self):
        """Mapper<Animal, Dog> must be assignable to Mapper<Dog, Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let m1: Mapper<Animal, Dog>;
declare let m2: Mapper<Dog, Animal>;
m2 = m1;
"""
        assert_compiles(code, "Mapper<Animal,Dog> -> Mapper<Dog,Animal>")

    def test_invalid_direction_rejected(self):
        """Mapper<Dog, Animal> must NOT be assignable to Mapper<Animal, Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let m1: Mapper<Animal, Dog>;
declare let m2: Mapper<Dog, Animal>;
m1 = m2;
"""
        assert_rejects(code, "Mapper<Dog,Animal> must not be assignable to Mapper<Animal,Dog>")


# --- Store<T> Tests (must be invariant) ---

class TestStoreInvariance:
    def test_subtype_to_supertype_rejected(self):
        """Store<Dog> must NOT be assignable to Store<Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let sa: Store<Animal>;
declare let sd: Store<Dog>;
sa = sd;
"""
        assert_rejects(code, "Store<Dog> must not be assignable to Store<Animal>")

    def test_supertype_to_subtype_rejected(self):
        """Store<Animal> must NOT be assignable to Store<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let sa: Store<Animal>;
declare let sd: Store<Dog>;
sd = sa;
"""
        assert_rejects(code, "Store<Animal> must not be assignable to Store<Dog>")

    def test_same_type_valid(self):
        """Store<Dog> must be assignable to Store<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let s1: Store<Dog>;
declare let s2: Store<Dog>;
s1 = s2;
"""
        assert_compiles(code, "Store<Dog> should be assignable to Store<Dog>")


# --- ReadonlyStore<T> Tests (must be covariant) ---

class TestReadonlyStoreCovariance:
    def test_subtype_to_supertype_valid(self):
        """ReadonlyStore<Dog> must be assignable to ReadonlyStore<Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ra: ReadonlyStore<Animal>;
declare let rd: ReadonlyStore<Dog>;
ra = rd;
"""
        assert_compiles(code, "ReadonlyStore should be covariant: Dog -> Animal")

    def test_supertype_to_subtype_rejected(self):
        """ReadonlyStore<Animal> must NOT be assignable to ReadonlyStore<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ra: ReadonlyStore<Animal>;
declare let rd: ReadonlyStore<Dog>;
rd = ra;
"""
        assert_rejects(code, "ReadonlyStore<Animal> must not be assignable to ReadonlyStore<Dog>")


# --- EventHandler<T> Tests (must be contravariant) ---

class TestEventHandlerContravariance:
    def test_supertype_to_subtype_valid(self):
        """EventHandler<Animal> must be assignable to EventHandler<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ha: EventHandler<Animal>;
declare let hd: EventHandler<Dog>;
hd = ha;
"""
        assert_compiles(code, "EventHandler should be contravariant: Animal -> Dog")

    def test_subtype_to_supertype_rejected(self):
        """EventHandler<Dog> must NOT be assignable to EventHandler<Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ha: EventHandler<Animal>;
declare let hd: EventHandler<Dog>;
ha = hd;
"""
        assert_rejects(code, "EventHandler<Dog> must not be assignable to EventHandler<Animal>")


# --- EventBus<T> Tests (must be contravariant) ---

class TestEventBusContravariance:
    def test_supertype_to_subtype_valid(self):
        """EventBus<Animal> must be assignable to EventBus<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ba: EventBus<Animal>;
declare let bd: EventBus<Dog>;
bd = ba;
"""
        assert_compiles(code, "EventBus should be contravariant: Animal -> Dog")

    def test_subtype_to_supertype_rejected(self):
        """EventBus<Dog> must NOT be assignable to EventBus<Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ba: EventBus<Animal>;
declare let bd: EventBus<Dog>;
ba = bd;
"""
        assert_rejects(code, "EventBus<Dog> must not be assignable to EventBus<Animal>")


# --- EventEmitter<T> Tests (must be invariant) ---

class TestEventEmitterInvariance:
    def test_subtype_to_supertype_rejected(self):
        """EventEmitter<Dog> must NOT be assignable to EventEmitter<Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ea: EventEmitter<Animal>;
declare let ed: EventEmitter<Dog>;
ea = ed;
"""
        assert_rejects(code, "EventEmitter must be invariant: Dog -> Animal rejected")

    def test_supertype_to_subtype_rejected(self):
        """EventEmitter<Animal> must NOT be assignable to EventEmitter<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ea: EventEmitter<Animal>;
declare let ed: EventEmitter<Dog>;
ed = ea;
"""
        assert_rejects(code, "EventEmitter must be invariant: Animal -> Dog rejected")


# --- Stream<T> Tests (must be invariant due to circular chain) ---

class TestStreamInvariance:
    def test_subtype_to_supertype_rejected(self):
        """Stream<Dog> must NOT be assignable to Stream<Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let sa: Stream<Animal>;
declare let sd: Stream<Dog>;
sa = sd;
"""
        assert_rejects(code, "Stream must be invariant: Dog -> Animal rejected")

    def test_supertype_to_subtype_rejected(self):
        """Stream<Animal> must NOT be assignable to Stream<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let sa: Stream<Animal>;
declare let sd: Stream<Dog>;
sd = sa;
"""
        assert_rejects(code, "Stream must be invariant: Animal -> Dog rejected")


# --- Config<T> Tests (must be covariant after merge fix) ---

class TestConfigCovariance:
    def test_subtype_to_supertype_valid(self):
        """Config<Dog> must be assignable to Config<Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ca: Config<Animal>;
declare let cd: Config<Dog>;
ca = cd;
"""
        assert_compiles(code, "Config should be covariant: Dog -> Animal")

    def test_supertype_to_subtype_rejected(self):
        """Config<Animal> must NOT be assignable to Config<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ca: Config<Animal>;
declare let cd: Config<Dog>;
cd = ca;
"""
        assert_rejects(code, "Config<Animal> must not be assignable to Config<Dog>")


# --- Lens<S, A> Tests (both S and A must be invariant) ---

class TestLensInvariance:
    def test_s_subtype_rejected(self):
        """Lens<Dog, string> must NOT be assignable to Lens<Animal, string>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ld: Lens<Dog, string>;
declare let la: Lens<Animal, string>;
la = ld;
"""
        assert_rejects(code, "Lens S must be invariant: Dog -> Animal rejected")

    def test_s_supertype_rejected(self):
        """Lens<Animal, string> must NOT be assignable to Lens<Dog, string>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ld: Lens<Dog, string>;
declare let la: Lens<Animal, string>;
ld = la;
"""
        assert_rejects(code, "Lens S must be invariant: Animal -> Dog rejected")

    def test_a_subtype_rejected(self):
        """Lens<string, Dog> must NOT be assignable to Lens<string, Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let l1: Lens<string, Dog>;
declare let l2: Lens<string, Animal>;
l2 = l1;
"""
        assert_rejects(code, "Lens A must be invariant: Dog -> Animal rejected")

    def test_a_supertype_rejected(self):
        """Lens<string, Animal> must NOT be assignable to Lens<string, Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let l1: Lens<string, Dog>;
declare let l2: Lens<string, Animal>;
l1 = l2;
"""
        assert_rejects(code, "Lens A must be invariant: Animal -> Dog rejected")


# --- Reducer<T, A> Tests (T contravariant, A invariant) ---

class TestReducerVariance:
    def test_t_contravariant_valid(self):
        """Reducer<Animal, number> must be assignable to Reducer<Dog, number>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ra: Reducer<Animal, number>;
declare let rd: Reducer<Dog, number>;
rd = ra;
"""
        assert_compiles(code, "Reducer T should be contravariant: Animal -> Dog")

    def test_t_covariant_rejected(self):
        """Reducer<Dog, number> must NOT be assignable to Reducer<Animal, number>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ra: Reducer<Animal, number>;
declare let rd: Reducer<Dog, number>;
ra = rd;
"""
        assert_rejects(code, "Reducer<Dog> must not be assignable to Reducer<Animal>")

    def test_a_subtype_rejected(self):
        """Reducer<string, Dog> must NOT be assignable to Reducer<string, Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let r1: Reducer<string, Dog>;
declare let r2: Reducer<string, Animal>;
r2 = r1;
"""
        assert_rejects(code, "Reducer A must be invariant: Dog -> Animal rejected")

    def test_a_supertype_rejected(self):
        """Reducer<string, Animal> must NOT be assignable to Reducer<string, Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let r1: Reducer<string, Dog>;
declare let r2: Reducer<string, Animal>;
r1 = r2;
"""
        assert_rejects(code, "Reducer A must be invariant: Animal -> Dog rejected")


# --- Predicate<T> Tests (must be contravariant) ---

class TestPredicateContravariance:
    def test_supertype_to_subtype_valid(self):
        """Predicate<Animal> must be assignable to Predicate<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let pa: Predicate<Animal>;
declare let pd: Predicate<Dog>;
pd = pa;
"""
        assert_compiles(code, "Predicate should be contravariant: Animal -> Dog")

    def test_subtype_to_supertype_rejected(self):
        """Predicate<Dog> must NOT be assignable to Predicate<Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let pa: Predicate<Animal>;
declare let pd: Predicate<Dog>;
pa = pd;
"""
        assert_rejects(code, "Predicate<Dog> must not be assignable to Predicate<Animal>")


# --- Encoder<T> Tests (must be contravariant) ---

class TestEncoderContravariance:
    def test_supertype_to_subtype_valid(self):
        """Encoder<Animal> must be assignable to Encoder<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ea: Encoder<Animal>;
declare let ed: Encoder<Dog>;
ed = ea;
"""
        assert_compiles(code, "Encoder should be contravariant: Animal -> Dog")

    def test_subtype_to_supertype_rejected(self):
        """Encoder<Dog> must NOT be assignable to Encoder<Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ea: Encoder<Animal>;
declare let ed: Encoder<Dog>;
ea = ed;
"""
        assert_rejects(code, "Encoder<Dog> must not be assignable to Encoder<Animal>")


# --- Decoder<T> Tests (must be covariant) ---

class TestDecoderCovariance:
    def test_subtype_to_supertype_valid(self):
        """Decoder<Dog> must be assignable to Decoder<Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let da: Decoder<Animal>;
declare let dd: Decoder<Dog>;
da = dd;
"""
        assert_compiles(code, "Decoder should be covariant: Dog -> Animal")

    def test_supertype_to_subtype_rejected(self):
        """Decoder<Animal> must NOT be assignable to Decoder<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let da: Decoder<Animal>;
declare let dd: Decoder<Dog>;
dd = da;
"""
        assert_rejects(code, "Decoder<Animal> must not be assignable to Decoder<Dog>")


# --- Codec<T> Tests (must be invariant) ---

class TestCodecInvariance:
    def test_subtype_to_supertype_rejected(self):
        """Codec<Dog> must NOT be assignable to Codec<Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ca: Codec<Animal>;
declare let cd: Codec<Dog>;
ca = cd;
"""
        assert_rejects(code, "Codec must be invariant: Dog -> Animal rejected")

    def test_supertype_to_subtype_rejected(self):
        """Codec<Animal> must NOT be assignable to Codec<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ca: Codec<Animal>;
declare let cd: Codec<Dog>;
cd = ca;
"""
        assert_rejects(code, "Codec must be invariant: Animal -> Dog rejected")

    def test_same_type_valid(self):
        """Codec<Dog> must be assignable to Codec<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let c1: Codec<Dog>;
declare let c2: Codec<Dog>;
c1 = c2;
"""
        assert_compiles(code, "Codec<Dog> should be assignable to Codec<Dog>")


# --- Handler<Req, Res> Tests (Req contravariant, Res covariant) ---

class TestHandlerVariance:
    def test_valid_direction(self):
        """Handler<Animal, Dog> must be assignable to Handler<Dog, Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let h1: Handler<Animal, Dog>;
declare let h2: Handler<Dog, Animal>;
h2 = h1;
"""
        assert_compiles(code, "Handler<Animal,Dog> -> Handler<Dog,Animal>")

    def test_invalid_direction_rejected(self):
        """Handler<Dog, Animal> must NOT be assignable to Handler<Animal, Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let h1: Handler<Animal, Dog>;
declare let h2: Handler<Dog, Animal>;
h1 = h2;
"""
        assert_rejects(code, "Handler<Dog,Animal> must not be assignable to Handler<Animal,Dog>")


# --- Interceptor<T> Tests (must be invariant) ---

class TestInterceptorInvariance:
    def test_subtype_to_supertype_rejected(self):
        """Interceptor<Dog> must NOT be assignable to Interceptor<Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ia: Interceptor<Animal>;
declare let id: Interceptor<Dog>;
ia = id;
"""
        assert_rejects(code, "Interceptor must be invariant: Dog -> Animal rejected")

    def test_supertype_to_subtype_rejected(self):
        """Interceptor<Animal> must NOT be assignable to Interceptor<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ia: Interceptor<Animal>;
declare let id: Interceptor<Dog>;
id = ia;
"""
        assert_rejects(code, "Interceptor must be invariant: Animal -> Dog rejected")


# --- Source<T> Tests (must be covariant) ---

class TestSourceCovariance:
    def test_subtype_to_supertype_valid(self):
        """Source<Dog> must be assignable to Source<Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let sd: Source<Dog>;
declare let sa: Source<Animal>;
sa = sd;
"""
        assert_compiles(code, "Source should be covariant: Dog -> Animal")

    def test_supertype_to_subtype_rejected(self):
        """Source<Animal> must NOT be assignable to Source<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let sd: Source<Dog>;
declare let sa: Source<Animal>;
sd = sa;
"""
        assert_rejects(code, "Source<Animal> must not be assignable to Source<Dog>")


# --- Sink<T> Tests (must be contravariant) ---

class TestSinkContravariance:
    def test_supertype_to_subtype_valid(self):
        """Sink<Animal> must be assignable to Sink<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let sa: Sink<Animal>;
declare let sd: Sink<Dog>;
sd = sa;
"""
        assert_compiles(code, "Sink should be contravariant: Animal -> Dog")

    def test_subtype_to_supertype_rejected(self):
        """Sink<Dog> must NOT be assignable to Sink<Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let sa: Sink<Animal>;
declare let sd: Sink<Dog>;
sa = sd;
"""
        assert_rejects(code, "Sink<Dog> must not be assignable to Sink<Animal>")


# --- Through<T, U> Tests (T contravariant, U covariant) ---

class TestThroughMixedVariance:
    def test_valid_direction(self):
        """Through<Animal, Dog> must be assignable to Through<Dog, Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let t1: Through<Animal, Dog>;
declare let t2: Through<Dog, Animal>;
t2 = t1;
"""
        assert_compiles(code, "Through<Animal,Dog> -> Through<Dog,Animal>")

    def test_invalid_direction_rejected(self):
        """Through<Dog, Animal> must NOT be assignable to Through<Animal, Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let t1: Through<Animal, Dog>;
declare let t2: Through<Dog, Animal>;
t1 = t2;
"""
        assert_rejects(code, "Through<Dog,Animal> must not be assignable to Through<Animal,Dog>")


# --- Pipeline<T, U> Tests (T contravariant, U covariant) ---

class TestPipelineMixedVariance:
    def test_valid_direction(self):
        """Pipeline<Animal, Dog> must be assignable to Pipeline<Dog, Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let p1: Pipeline<Animal, Dog>;
declare let p2: Pipeline<Dog, Animal>;
p2 = p1;
"""
        assert_compiles(code, "Pipeline<Animal,Dog> -> Pipeline<Dog,Animal>")

    def test_invalid_direction_rejected(self):
        """Pipeline<Dog, Animal> must NOT be assignable to Pipeline<Animal, Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let p1: Pipeline<Animal, Dog>;
declare let p2: Pipeline<Dog, Animal>;
p1 = p2;
"""
        assert_rejects(code, "Pipeline<Dog,Animal> must not be assignable to Pipeline<Animal,Dog>")


# --- Duplex<T, U> Tests (T covariant, U contravariant) ---

class TestDuplexVariance:
    def test_t_covariant_valid(self):
        """Duplex<Dog, string> must be assignable to Duplex<Animal, string>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let dd: Duplex<Dog, string>;
declare let da: Duplex<Animal, string>;
da = dd;
"""
        assert_compiles(code, "Duplex T should be covariant: Dog -> Animal")

    def test_t_covariant_rejected(self):
        """Duplex<Animal, string> must NOT be assignable to Duplex<Dog, string>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let dd: Duplex<Dog, string>;
declare let da: Duplex<Animal, string>;
dd = da;
"""
        assert_rejects(code, "Duplex T must not be reverse-assignable")

    def test_u_contravariant_valid(self):
        """Duplex<string, Animal> must be assignable to Duplex<string, Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let da: Duplex<string, Animal>;
declare let dd: Duplex<string, Dog>;
dd = da;
"""
        assert_compiles(code, "Duplex U should be contravariant: Animal -> Dog")

    def test_u_contravariant_rejected(self):
        """Duplex<string, Dog> must NOT be assignable to Duplex<string, Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let da: Duplex<string, Animal>;
declare let dd: Duplex<string, Dog>;
da = dd;
"""
        assert_rejects(code, "Duplex U must not be reverse-assignable")


# --- Channel<T> Tests (must be invariant) ---

class TestChannelInvariance:
    def test_subtype_to_supertype_rejected(self):
        """Channel<Dog> must NOT be assignable to Channel<Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ca: Channel<Animal>;
declare let cd: Channel<Dog>;
ca = cd;
"""
        assert_rejects(code, "Channel must be invariant: Dog -> Animal rejected")

    def test_supertype_to_subtype_rejected(self):
        """Channel<Animal> must NOT be assignable to Channel<Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let ca: Channel<Animal>;
declare let cd: Channel<Dog>;
cd = ca;
"""
        assert_rejects(code, "Channel must be invariant: Animal -> Dog rejected")


# --- Fold<T, R> Tests (T contravariant, R invariant) ---

class TestFoldVariance:
    def test_t_contravariant_valid(self):
        """Fold<Animal, number> must be assignable to Fold<Dog, number>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let fa: Fold<Animal, number>;
declare let fd: Fold<Dog, number>;
fd = fa;
"""
        assert_compiles(code, "Fold T should be contravariant: Animal -> Dog")

    def test_t_covariant_rejected(self):
        """Fold<Dog, number> must NOT be assignable to Fold<Animal, number>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let fa: Fold<Animal, number>;
declare let fd: Fold<Dog, number>;
fa = fd;
"""
        assert_rejects(code, "Fold<Dog> must not be assignable to Fold<Animal>")

    def test_r_subtype_rejected(self):
        """Fold<string, Dog> must NOT be assignable to Fold<string, Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let f1: Fold<string, Dog>;
declare let f2: Fold<string, Animal>;
f2 = f1;
"""
        assert_rejects(code, "Fold R must be invariant: Dog -> Animal rejected")

    def test_r_supertype_rejected(self):
        """Fold<string, Animal> must NOT be assignable to Fold<string, Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let f1: Fold<string, Dog>;
declare let f2: Fold<string, Animal>;
f1 = f2;
"""
        assert_rejects(code, "Fold R must be invariant: Animal -> Dog rejected")


# --- Splitter<T, A, B> Tests (T contravariant, A covariant, B covariant) ---

class TestSplitterVariance:
    def test_t_contravariant_valid(self):
        """Splitter<Animal, string, string> must be assignable to Splitter<Dog, string, string>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let s1: Splitter<Animal, string, string>;
declare let s2: Splitter<Dog, string, string>;
s2 = s1;
"""
        assert_compiles(code, "Splitter T should be contravariant: Animal -> Dog")

    def test_t_covariant_rejected(self):
        """Splitter<Dog, string, string> must NOT be assignable to Splitter<Animal, string, string>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let s1: Splitter<Animal, string, string>;
declare let s2: Splitter<Dog, string, string>;
s1 = s2;
"""
        assert_rejects(code, "Splitter<Dog> must not be assignable to Splitter<Animal>")

    def test_a_covariant_valid(self):
        """Splitter<string, Dog, string> must be assignable to Splitter<string, Animal, string>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let s1: Splitter<string, Dog, string>;
declare let s2: Splitter<string, Animal, string>;
s2 = s1;
"""
        assert_compiles(code, "Splitter A should be covariant: Dog -> Animal")

    def test_a_covariant_rejected(self):
        """Splitter<string, Animal, string> must NOT be assignable to Splitter<string, Dog, string>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let s1: Splitter<string, Dog, string>;
declare let s2: Splitter<string, Animal, string>;
s1 = s2;
"""
        assert_rejects(code, "Splitter A must not be reverse-assignable")

    def test_b_covariant_valid(self):
        """Splitter<string, string, Dog> must be assignable to Splitter<string, string, Animal>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let s1: Splitter<string, string, Dog>;
declare let s2: Splitter<string, string, Animal>;
s2 = s1;
"""
        assert_compiles(code, "Splitter B should be covariant: Dog -> Animal")

    def test_b_covariant_rejected(self):
        """Splitter<string, string, Animal> must NOT be assignable to Splitter<string, string, Dog>."""
        code = read_library_types() + TYPE_HIERARCHY + """
declare let s1: Splitter<string, string, Dog>;
declare let s2: Splitter<string, string, Animal>;
s1 = s2;
"""
        assert_rejects(code, "Splitter B must not be reverse-assignable")


# --- Index and Compose Module Tests ---

class TestModuleIntegration:
    def test_compose_exported_from_index(self):
        """index.ts must re-export the compose module."""
        with open('/app/src/index.ts') as f:
            content = f.read()
        assert './compose' in content, \
            "index.ts must re-export the compose module"

    def test_codec_exported_from_index(self):
        """index.ts must re-export the codec module."""
        with open('/app/src/index.ts') as f:
            content = f.read()
        assert './codec' in content, \
            "index.ts must re-export the codec module"

    def test_middleware_exported_from_index(self):
        """index.ts must re-export the middleware module."""
        with open('/app/src/index.ts') as f:
            content = f.read()
        assert './middleware' in content, \
            "index.ts must re-export the middleware module"

    def test_compose_has_required_types(self):
        """compose.ts must define all required types."""
        with open('/app/src/compose.ts') as f:
            content = f.read()
        for name in ['Source', 'Sink', 'Through', 'Pipeline', 'Duplex',
                     'Channel', 'Fold', 'Splitter']:
            assert re.search(rf'\b(type|interface)\s+{name}\b', content), \
                f"compose.ts must define type {name}"
