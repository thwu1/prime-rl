"""
Mini Autodiff Framework
=======================
A self-contained automatic differentiation system implementing both
forward-mode (JVP via dual numbers) and reverse-mode (VJP via tape-based
backpropagation) differentiation for scalar computations.

Supports:
  - Scalar forward and reverse mode AD
  - grad(), jvp(), deriv(), value_and_grad()
  - Composable math functions: sin, cos, exp, log

"""

import math


# ================================================================
# Primitive Operations
# ================================================================

class Primitive:
    """A named primitive operation."""
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"Primitive({self.name})"

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return isinstance(other, Primitive) and self.name == other.name


add_p = Primitive("add")
mul_p = Primitive("mul")
sub_p = Primitive("sub")
neg_p = Primitive("neg")
div_p = Primitive("div")
sin_p = Primitive("sin")
cos_p = Primitive("cos")
exp_p = Primitive("exp")
log_p = Primitive("log")

# Concrete implementation rules for each primitive
impl_rules = {
    add_p: lambda x, y: x + y,
    mul_p: lambda x, y: x * y,
    sub_p: lambda x, y: x - y,
    neg_p: lambda x: -x,
    div_p: lambda x, y: x / y,
    sin_p: lambda x: math.sin(x),
    cos_p: lambda x: math.cos(x),
    exp_p: lambda x: math.exp(x),
    log_p: lambda x: math.log(x),
}


# ================================================================
# Tape: Records operations for reverse-mode AD
# ================================================================

class TapeEntry:
    """One recorded operation on the computation tape."""
    __slots__ = ['prim', 'inputs', 'output', 'input_vals', 'output_val']

    def __init__(self, prim, inputs, output):
        self.prim = prim
        self.inputs = inputs
        self.output = output
        self.input_vals = [v.val for v in inputs]
        self.output_val = output.val


class Tape:
    """Ordered record of primitive operations for backward pass."""
    def __init__(self):
        self.entries = []

    def record(self, prim, inputs, output):
        self.entries.append(TapeEntry(prim, inputs, output))

    def __len__(self):
        return len(self.entries)


# ================================================================
# Var: Tracked variable for autodiff
# ================================================================

class Var:
    """A scalar variable that participates in autodiff computation.

    When associated with a Tape, operations on this variable are recorded
    for backward-pass gradient computation.
    """
    _id_counter = 0

    def __init__(self, val, tape=None):
        self.val = float(val)
        self.tape = tape
        self.id = Var._id_counter
        Var._id_counter += 1

    def _get_tape(self, other=None):
        """Resolve the active tape from self or other operand."""
        if self.tape is not None:
            return self.tape
        if other is not None and isinstance(other, Var) and other.tape is not None:
            return other.tape
        return None

    def _ensure_var(self, other):
        """Coerce a Python numeric to Var if needed."""
        if isinstance(other, Var):
            return other
        return Var(float(other))

    def _binary_op(self, other, prim):
        other = self._ensure_var(other)
        result_val = impl_rules[prim](self.val, other.val)
        tape = self._get_tape(other)
        result = Var(result_val, tape=tape)
        if tape is not None:
            tape.record(prim, [self, other], result)
        return result

    def _unary_op(self, prim):
        result_val = impl_rules[prim](self.val)
        result = Var(result_val, tape=self.tape)
        if self.tape is not None:
            self.tape.record(prim, [self], result)
        return result

    def __add__(self, other):
        return self._binary_op(other, add_p)

    def __radd__(self, other):
        return self._ensure_var(other)._binary_op(self, add_p)

    def __mul__(self, other):
        return self._binary_op(other, mul_p)

    def __rmul__(self, other):
        return self._ensure_var(other)._binary_op(self, mul_p)

    def __sub__(self, other):
        return self._binary_op(other, sub_p)

    def __rsub__(self, other):
        return self._ensure_var(other)._binary_op(self, sub_p)

    def __truediv__(self, other):
        return self._binary_op(other, div_p)

    def __rtruediv__(self, other):
        return self._ensure_var(other)._binary_op(self, div_p)

    def __neg__(self):
        return self._unary_op(neg_p)

    def __float__(self):
        return self.val

    def __repr__(self):
        return f"Var({self.val})"


# ================================================================
# VJP Rules: Backward differentiation rules
# ================================================================
# Signature: vjp_rule(ct, input_vals, output_val) -> tuple of input cotangents
# ct: cotangent (gradient) flowing from the output
# input_vals: list of float values of the inputs during forward pass
# output_val: float value of the output during forward pass

vjp_rules = {}


def vjp_add(ct, input_vals, output_val):
    return (ct, ct)

vjp_rules[add_p] = vjp_add


def vjp_mul(ct, input_vals, output_val):
    x, y = input_vals
    return (ct * x, ct * y)

vjp_rules[mul_p] = vjp_mul


def vjp_sub(ct, input_vals, output_val):
    return (ct, -ct)

vjp_rules[sub_p] = vjp_sub


def vjp_neg(ct, input_vals, output_val):
    return (-ct,)

vjp_rules[neg_p] = vjp_neg


def vjp_div(ct, input_vals, output_val):
    x, y = input_vals
    return (ct / y, -ct * x / y)

vjp_rules[div_p] = vjp_div


def vjp_sin(ct, input_vals, output_val):
    x, = input_vals
    return (ct * math.cos(x),)

vjp_rules[sin_p] = vjp_sin


def vjp_cos(ct, input_vals, output_val):
    x, = input_vals
    return (-ct * math.sin(x),)

vjp_rules[cos_p] = vjp_cos


def vjp_log(ct, input_vals, output_val):
    x, = input_vals
    return (ct / x,)

vjp_rules[log_p] = vjp_log


# ================================================================
# Backward Pass: Reverse-mode gradient computation
# ================================================================

def backward(tape, output_var):
    """Walk the tape in reverse to compute gradients via chain rule.

    Args:
        tape: Tape with recorded operations from the forward pass.
        output_var: The output Var to differentiate from (receives ct=1).

    Returns:
        Dict mapping Var.id -> gradient (float).
    """
    grads = {output_var.id: 1.0}

    for entry in reversed(tape.entries):
        if entry.output.id not in grads:
            continue

        ct = grads[entry.output.id]

        if entry.prim not in vjp_rules:
            raise ValueError(
                f"No VJP rule registered for primitive '{entry.prim.name}'. "
                f"Cannot compute gradient through this operation."
            )

        input_cts = vjp_rules[entry.prim](ct, entry.input_vals, entry.output_val)

        for inp, ict in zip(entry.inputs, input_cts):
            if inp.id in grads:
                grads[inp.id] = ict
            else:
                grads[inp.id] = ict

    return grads


# ================================================================
# Grad API: User-facing reverse-mode interface
# ================================================================

def grad(f, argnums=0):
    """Return a function that computes the gradient of f via reverse-mode AD.

    Args:
        f: Scalar-valued function of one or more scalar arguments.
        argnums: int or tuple of ints indicating which args to differentiate.

    Returns:
        A function returning the gradient(s) at given input values.
    """
    def grad_f(*args):
        tape = Tape()

        if isinstance(argnums, int):
            tracked_indices = {argnums}
        else:
            tracked_indices = set(argnums)

        tracked_args = []
        tracked_vars = []
        for i, a in enumerate(args):
            if i in tracked_indices:
                v = Var(float(a), tape=tape)
                tracked_args.append(v)
                tracked_vars.append(v)
            else:
                tracked_args.append(Var(float(a)))

        result = f(*tracked_args)
        if not isinstance(result, Var):
            result = Var(float(result), tape=tape)

        grads_dict = backward(tape, result)

        if isinstance(argnums, int):
            return grads_dict.get(tracked_vars[0].id, 0.0)
        else:
            return tuple(grads_dict.get(v.id, 0.0) for v in tracked_vars)

    return grad_f


def value_and_grad(f, argnums=0):
    """Return a function giving both value and gradient of f."""
    def val_grad_f(*args):
        tape = Tape()

        if isinstance(argnums, int):
            tracked_indices = {argnums}
        else:
            tracked_indices = set(argnums)

        tracked_args = []
        tracked_vars = []
        for i, a in enumerate(args):
            if i in tracked_indices:
                v = Var(float(a), tape=tape)
                tracked_args.append(v)
                tracked_vars.append(v)
            else:
                tracked_args.append(Var(float(a)))

        result = f(*tracked_args)
        if not isinstance(result, Var):
            result = Var(float(result), tape=tape)

        grads_dict = backward(tape, result)

        if isinstance(argnums, int):
            return result.val, grads_dict.get(tracked_vars[0].id, 0.0)
        else:
            return result.val, tuple(grads_dict.get(v.id, 0.0) for v in tracked_vars)

    return val_grad_f


# ================================================================
# JVP Rules: Forward-mode differentiation rules
# ================================================================
# Signature: jvp_rule(primals, tangents) -> (primal_out, tangent_out)
# primals: tuple of float primal values
# tangents: tuple of float tangent values

jvp_rules = {}

jvp_rules[add_p] = lambda primals, tangents: (
    primals[0] + primals[1],
    tangents[0] + tangents[1]
)

jvp_rules[mul_p] = lambda primals, tangents: (
    primals[0] * primals[1],
    tangents[0] * primals[1] + primals[0] * tangents[1]
)

jvp_rules[sub_p] = lambda primals, tangents: (
    primals[0] - primals[1],
    tangents[0] + tangents[1]
)

jvp_rules[neg_p] = lambda primals, tangents: (
    -primals[0],
    -tangents[0]
)

jvp_rules[div_p] = lambda primals, tangents: (
    primals[0] / primals[1],
    (tangents[0] * primals[1] - primals[0] * tangents[1]) / (primals[1] ** 2)
)

jvp_rules[sin_p] = lambda primals, tangents: (
    math.sin(primals[0]),
    math.cos(primals[0]) * tangents[0]
)

jvp_rules[cos_p] = lambda primals, tangents: (
    math.cos(primals[0]),
    -math.sin(primals[0]) * tangents[0]
)

jvp_rules[exp_p] = lambda primals, tangents: (
    math.exp(primals[0]),
    math.exp(primals[0]) * tangents[0]
)

jvp_rules[log_p] = lambda primals, tangents: (
    math.log(primals[0]),
    tangents[0] / primals[0]
)


# ================================================================
# DualNumber: Carrier for forward-mode AD
# ================================================================

class DualNumber:
    """Dual number (primal, tangent) for forward-mode automatic differentiation."""

    def __init__(self, primal, tangent=0.0):
        self.primal = float(primal) if not isinstance(primal, float) else primal
        self.tangent = float(tangent) if not isinstance(tangent, float) else tangent

    def _ensure_dual(self, other):
        if isinstance(other, DualNumber):
            return other
        return DualNumber(float(other), 0.0)

    def __add__(self, other):
        other = self._ensure_dual(other)
        p, t = jvp_rules[add_p](
            (self.primal, other.primal), (self.tangent, other.tangent))
        return DualNumber(p, t)

    def __radd__(self, other):
        return self._ensure_dual(other).__add__(self)

    def __mul__(self, other):
        other = self._ensure_dual(other)
        p, t = jvp_rules[mul_p](
            (self.primal, other.primal), (self.tangent, other.tangent))
        return DualNumber(p, t)

    def __rmul__(self, other):
        return self._ensure_dual(other).__mul__(self)

    def __sub__(self, other):
        other = self._ensure_dual(other)
        p, t = jvp_rules[sub_p](
            (self.primal, other.primal), (self.tangent, other.tangent))
        return DualNumber(p, t)

    def __rsub__(self, other):
        return self._ensure_dual(other).__sub__(self)

    def __truediv__(self, other):
        other = self._ensure_dual(other)
        p, t = jvp_rules[div_p](
            (self.primal, other.primal), (self.tangent, other.tangent))
        return DualNumber(p, t)

    def __rtruediv__(self, other):
        return self._ensure_dual(other).__truediv__(self)

    def __neg__(self):
        p, t = jvp_rules[neg_p]((self.primal,), (self.tangent,))
        return DualNumber(p, t)

    def __float__(self):
        return self.primal

    def __repr__(self):
        return f"DualNumber({self.primal}, {self.tangent})"


# ================================================================
# Math Functions: Dispatch on Var, DualNumber, or plain float
# ================================================================

def sin(x):
    """Sine function supporting Var, DualNumber, and float inputs."""
    if isinstance(x, Var):
        return x._unary_op(sin_p)
    elif isinstance(x, DualNumber):
        p, t = jvp_rules[sin_p]((x.primal,), (x.tangent,))
        return DualNumber(p, t)
    return math.sin(x)


def cos(x):
    """Cosine function supporting Var, DualNumber, and float inputs."""
    if isinstance(x, Var):
        return x._unary_op(cos_p)
    elif isinstance(x, DualNumber):
        p, t = jvp_rules[cos_p]((x.primal,), (x.tangent,))
        return DualNumber(p, t)
    return math.cos(x)


def exp(x):
    """Exponential function supporting Var, DualNumber, and float inputs."""
    if isinstance(x, Var):
        return x._unary_op(exp_p)
    elif isinstance(x, DualNumber):
        p, t = jvp_rules[exp_p]((x.primal,), (x.tangent,))
        return DualNumber(p, t)
    return math.exp(x)


def log(x):
    """Natural logarithm supporting Var, DualNumber, and float inputs."""
    if isinstance(x, Var):
        return x._unary_op(log_p)
    elif isinstance(x, DualNumber):
        p, t = jvp_rules[log_p]((x.primal,), (x.tangent,))
        return DualNumber(p, t)
    return math.log(x)


# ================================================================
# JVP / Deriv API: User-facing forward-mode interface
# ================================================================

def jvp(f, primals, tangents):
    """Compute the Jacobian-vector product (forward-mode AD).

    Args:
        f: Function to differentiate.
        primals: Tuple of primal input values.
        tangents: Tuple of tangent (perturbation) vectors.

    Returns:
        (primal_out, tangent_out) pair.
    """
    duals = [DualNumber(p, t) for p, t in zip(primals, tangents)]
    if len(duals) == 1:
        result = f(duals[0])
    else:
        result = f(*duals)

    if isinstance(result, DualNumber):
        return result.primal, result.tangent
    return float(result), 0.0


def deriv(f):
    """Return the derivative function of a scalar -> scalar function.

    Uses forward-mode AD internally.
    """
    def df(x):
        _, tangent = jvp(f, (x,), (1.0,))
        return tangent
    return df
