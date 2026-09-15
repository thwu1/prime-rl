#!/usr/bin/env bash

set -euo pipefail

###############################################################################
# Reference solution: Hindley-Milner type inference in MoonBit
###############################################################################

# Install MoonBit toolchain using Python tarfile to avoid chmod failures
# in container runtimes (overlayfs, podman).
install_moon_patched() {
    echo "=== Installing MoonBit toolchain ==="
    mkdir -p /root/.moon/bin /root/.moon/lib

    echo "Downloading moonbit ..."
    curl -fsSL "https://cli.moonbitlang.com/binaries/latest/moonbit-linux-x86_64.tar.gz" -o /tmp/moonbit.tar.gz
    python3 -c "import tarfile; tarfile.open('/tmp/moonbit.tar.gz').extractall('/root/.moon', filter='data')"
    rm -f /tmp/moonbit.tar.gz
    find /root/.moon/bin -type f -exec chmod +x {} +
    find /root/.moon/bin/internal -type f -exec chmod +x {} + 2>/dev/null || true

    echo "Downloading core ..."
    curl -fsSL "https://cli.moonbitlang.com/cores/core-latest.tar.gz" -o /tmp/core.tar.gz
    python3 -c "import tarfile; tarfile.open('/tmp/core.tar.gz').extractall('/root/.moon/lib', filter='data')"
    rm -f /tmp/core.tar.gz

    echo "Bundling core ..."
    PATH="/root/.moon/bin:${PATH}" /root/.moon/bin/moon -C /root/.moon/lib/core bundle --warn-list -a --all
    PATH="/root/.moon/bin:${PATH}" /root/.moon/bin/moon -C /root/.moon/lib/core bundle --warn-list -a --target wasm-gc --quiet
}

export PATH="/root/.moon/bin:${PATH}"
if ! command -v moon &> /dev/null; then
    install_moon_patched
    export PATH="/root/.moon/bin:${PATH}"
fi

moon version

# Ensure moon.pkg.json exists (needed by newer MoonBit versions)
if [ ! -f /app/moon.pkg.json ]; then
    echo '{}' > /app/moon.pkg.json
fi

# Write the complete implementation as a single MoonBit source file
cat > /app/engine.mbt << 'MOONBIT_ENGINE'
// ============================================================================
// Hindley-Milner Type Inference Engine for MoonBit
// ============================================================================

// --- Expression AST ---------------------------------------------------------

///|
pub(all) enum Expr {
  EInt(Int)
  EBool(Bool)
  EVar(String)
  ELam(String, Expr)
  EApp(Expr, Expr)
  ELet(String, Expr, Expr)
  ELetRec(String, Expr, Expr)
  EIf(Expr, Expr, Expr)
  EBinOp(String, Expr, Expr)
}

// --- Type representation ----------------------------------------------------

///|
pub(all) enum Ty {
  TInt
  TBool
  TVar(Int)
  TArrow(Ty, Ty)
}

///|
struct Scheme {
  vars : Array[Int]
  ty : Ty
}

// --- Inference context (fresh variable supply) ------------------------------

///|
struct InferCtx {
  mut next_id : Int
}

///|
fn InferCtx::make() -> InferCtx {
  { next_id: 0 }
}

///|
fn fresh(self : InferCtx) -> Ty {
  let id = self.next_id
  self.next_id = id + 1
  TVar(id)
}

// --- Tokenizer --------------------------------------------------------------

///|
priv enum Token {
  LParen
  RParen
  TokIdent(String)
  TokInt(Int)
  TokBool(Bool)
}

///|
fn is_delim(c : Char) -> Bool {
  c == ' ' || c == '\n' || c == '\t' || c == '\r' || c == '(' || c == ')'
}

///|
fn try_parse_int(s : String) -> Int? {
  let chars : Array[Char] = []
  for c in s {
    chars.push(c)
  }
  if chars.is_empty() {
    return None
  }
  let mut start = 0
  let mut neg = false
  if chars[0] == '-' {
    if chars.length() < 2 {
      return None
    }
    neg = true
    start = 1
  }
  let mut result = 0
  let mut i = start
  while i < chars.length() {
    let c = chars[i]
    if c >= '0' && c <= '9' {
      result = result * 10 + (c.to_int() - 48)
    } else {
      return None
    }
    i = i + 1
  }
  if neg { Some(-result) } else { Some(result) }
}

///|
fn build_word(chars : Array[Char], start : Int, end : Int) -> String {
  let buf = StringBuilder::new()
  let mut i = start
  while i < end {
    buf.write_char(chars[i])
    i = i + 1
  }
  buf.to_string()
}

///|
fn tokenize(input : String) -> Array[Token] {
  let tokens : Array[Token] = []
  let chars : Array[Char] = []
  for c in input {
    chars.push(c)
  }
  let len = chars.length()
  let mut i = 0
  while i < len {
    let c = chars[i]
    if c == ' ' || c == '\n' || c == '\t' || c == '\r' {
      i = i + 1
    } else if c == '(' {
      tokens.push(LParen)
      i = i + 1
    } else if c == ')' {
      tokens.push(RParen)
      i = i + 1
    } else {
      let start = i
      while i < len && not(is_delim(chars[i])) {
        i = i + 1
      }
      let word = build_word(chars, start, i)
      if word == "true" {
        tokens.push(TokBool(true))
      } else if word == "false" {
        tokens.push(TokBool(false))
      } else {
        match try_parse_int(word) {
          Some(n) => tokens.push(TokInt(n))
          None => tokens.push(TokIdent(word))
        }
      }
    }
  }
  tokens
}

// --- Parser -----------------------------------------------------------------

///|
struct PState {
  tokens : Array[Token]
  mut pos : Int
}

///|
fn PState::make(tokens : Array[Token]) -> PState {
  { tokens, pos: 0 }
}

///|
fn peek(self : PState) -> Token? {
  if self.pos < self.tokens.length() {
    Some(self.tokens[self.pos])
  } else {
    None
  }
}

///|
fn advance(self : PState) -> Token!Error {
  if self.pos < self.tokens.length() {
    let tok = self.tokens[self.pos]
    self.pos = self.pos + 1
    tok
  } else {
    fail!("unexpected end of input")
  }
}

///|
fn expect_rparen(self : PState) -> Unit!Error {
  match self.advance!() {
    RParen => ()
    _ => fail!("expected )")
  }
}

///|
fn expect_ident(self : PState) -> String!Error {
  match self.advance!() {
    TokIdent(s) => s
    _ => fail!("expected identifier")
  }
}

///|
fn is_binop(s : String) -> Bool {
  s == "+" || s == "-" || s == "*" || s == "==" || s == "<"
}

///|
fn parse_expr(self : PState) -> Expr!Error {
  match self.peek() {
    Some(TokInt(_)) => {
      let tok = self.advance!()
      match tok {
        TokInt(n) => EInt(n)
        _ => fail!("impossible")
      }
    }
    Some(TokBool(_)) => {
      let tok = self.advance!()
      match tok {
        TokBool(b) => EBool(b)
        _ => fail!("impossible")
      }
    }
    Some(TokIdent(_)) => {
      let tok = self.advance!()
      match tok {
        TokIdent(s) => EVar(s)
        _ => fail!("impossible")
      }
    }
    Some(LParen) => {
      let _ = self.advance!()
      self.parse_compound!()
    }
    _ => fail!("unexpected token or end of input")
  }
}

///|
fn parse_compound(self : PState) -> Expr!Error {
  match self.peek() {
    Some(TokIdent(s)) => {
      if s == "fn" {
        let _ = self.advance!()
        let param = self.expect_ident!()
        let body = self.parse_expr!()
        self.expect_rparen!()
        return ELam(param, body)
      }
      if s == "let" {
        let _ = self.advance!()
        let name = self.expect_ident!()
        let def = self.parse_expr!()
        let body = self.parse_expr!()
        self.expect_rparen!()
        return ELet(name, def, body)
      }
      if s == "letrec" {
        let _ = self.advance!()
        let name = self.expect_ident!()
        let def = self.parse_expr!()
        let body = self.parse_expr!()
        self.expect_rparen!()
        return ELetRec(name, def, body)
      }
      if s == "if" {
        let _ = self.advance!()
        let cond = self.parse_expr!()
        let then_br = self.parse_expr!()
        let else_br = self.parse_expr!()
        self.expect_rparen!()
        return EIf(cond, then_br, else_br)
      }
      if is_binop(s) {
        let _ = self.advance!()
        let left = self.parse_expr!()
        let right = self.parse_expr!()
        self.expect_rparen!()
        return EBinOp(s, left, right)
      }
      // Default: function application (f arg)
      let func = self.parse_expr!()
      let arg = self.parse_expr!()
      self.expect_rparen!()
      EApp(func, arg)
    }
    _ => {
      // Function application where func is not an identifier
      let func = self.parse_expr!()
      let arg = self.parse_expr!()
      self.expect_rparen!()
      EApp(func, arg)
    }
  }
}

///|
fn parse(input : String) -> Expr!Error {
  let tokens = tokenize(input)
  let st = PState::make(tokens)
  st.parse_expr!()
}

// --- Substitution (association list) ----------------------------------------

///|
fn subst_lookup(subst : Array[(Int, Ty)], key : Int) -> Ty? {
  let mut i = 0
  while i < subst.length() {
    let entry = subst[i]
    match entry {
      (k, v) => {
        if k == key {
          return Some(v)
        }
      }
    }
    i = i + 1
  }
  None
}

///|
fn apply_subst(subst : Array[(Int, Ty)], ty : Ty) -> Ty {
  match ty {
    TInt => TInt
    TBool => TBool
    TVar(id) =>
      match subst_lookup(subst, id) {
        Some(t) => apply_subst(subst, t)
        None => TVar(id)
      }
    TArrow(t1, t2) => TArrow(apply_subst(subst, t1), apply_subst(subst, t2))
  }
}

// --- Occurs check -----------------------------------------------------------

///|
fn occurs_in(id : Int, ty : Ty, subst : Array[(Int, Ty)]) -> Bool {
  let resolved = apply_subst(subst, ty)
  match resolved {
    TVar(id2) => id == id2
    TArrow(t1, t2) => occurs_in(id, t1, subst) || occurs_in(id, t2, subst)
    _ => false
  }
}

// --- Unification ------------------------------------------------------------

///|
fn unify(t1 : Ty, t2 : Ty, subst : Array[(Int, Ty)]) -> Unit!Error {
  let s1 = apply_subst(subst, t1)
  let s2 = apply_subst(subst, t2)
  match (s1, s2) {
    (TInt, TInt) => ()
    (TBool, TBool) => ()
    (TVar(a), TVar(b)) => {
      if a != b {
        subst.push((a, TVar(b)))
      }
    }
    (TVar(a), t) => {
      if occurs_in(a, t, subst) {
        fail!("infinite type")
      }
      subst.push((a, t))
    }
    (t, TVar(a)) => {
      if occurs_in(a, t, subst) {
        fail!("infinite type")
      }
      subst.push((a, t))
    }
    (TArrow(l1, r1), TArrow(l2, r2)) => {
      unify!(l1, l2, subst)
      unify!(r1, r2, subst)
    }
    _ => fail!("type mismatch")
  }
}

// --- Environment (association list) -----------------------------------------

///|
fn env_lookup(
  env : Array[(String, Scheme)],
  name : String
) -> Scheme? {
  // Search from end for most recent binding (shadowing)
  let mut i = env.length() - 1
  while i >= 0 {
    let entry = env[i]
    match entry {
      (k, v) => {
        if k == name {
          return Some(v)
        }
      }
    }
    i = i - 1
  }
  None
}

///|
fn env_extend(
  env : Array[(String, Scheme)],
  name : String,
  scheme : Scheme
) -> Array[(String, Scheme)] {
  let new_env : Array[(String, Scheme)] = []
  let mut i = 0
  while i < env.length() {
    new_env.push(env[i])
    i = i + 1
  }
  new_env.push((name, scheme))
  new_env
}

// --- Free variables ---------------------------------------------------------

///|
fn collect_free_vars(ty : Ty, result : Array[Int]) -> Unit {
  match ty {
    TVar(id) => {
      if not(result.contains(id)) {
        result.push(id)
      }
    }
    TArrow(t1, t2) => {
      collect_free_vars(t1, result)
      collect_free_vars(t2, result)
    }
    _ => ()
  }
}

///|
fn free_vars_ty(ty : Ty) -> Array[Int] {
  let result : Array[Int] = []
  collect_free_vars(ty, result)
  result
}

///|
fn free_vars_env(
  env : Array[(String, Scheme)],
  subst : Array[(Int, Ty)]
) -> Array[Int] {
  let result : Array[Int] = []
  let mut i = 0
  while i < env.length() {
    let entry = env[i]
    match entry {
      (_, scheme) => {
        let applied = apply_subst(subst, scheme.ty)
        let fvs = free_vars_ty(applied)
        let mut j = 0
        while j < fvs.length() {
          let v = fvs[j]
          if not(scheme.vars.contains(v)) && not(result.contains(v)) {
            result.push(v)
          }
          j = j + 1
        }
      }
    }
    i = i + 1
  }
  result
}

// --- Generalization and instantiation ---------------------------------------

///|
fn generalize(
  env : Array[(String, Scheme)],
  ty : Ty,
  subst : Array[(Int, Ty)]
) -> Scheme {
  let resolved = apply_subst(subst, ty)
  let ty_fvs = free_vars_ty(resolved)
  let env_fvs = free_vars_env(env, subst)
  let quantified : Array[Int] = []
  let mut i = 0
  while i < ty_fvs.length() {
    let v = ty_fvs[i]
    if not(env_fvs.contains(v)) {
      quantified.push(v)
    }
    i = i + 1
  }
  { vars: quantified, ty: resolved }
}

///|
fn apply_mapping(ty : Ty, mapping : Array[(Int, Ty)]) -> Ty {
  match ty {
    TInt => TInt
    TBool => TBool
    TVar(id) =>
      match subst_lookup(mapping, id) {
        Some(t) => t
        None => TVar(id)
      }
    TArrow(t1, t2) =>
      TArrow(apply_mapping(t1, mapping), apply_mapping(t2, mapping))
  }
}

///|
fn instantiate(scheme : Scheme, ctx : InferCtx) -> Ty {
  let mapping : Array[(Int, Ty)] = []
  let mut i = 0
  while i < scheme.vars.length() {
    mapping.push((scheme.vars[i], ctx.fresh()))
    i = i + 1
  }
  apply_mapping(scheme.ty, mapping)
}

// --- Type inference (Algorithm W) -------------------------------------------

///|
fn infer(
  env : Array[(String, Scheme)],
  expr : Expr,
  ctx : InferCtx,
  subst : Array[(Int, Ty)]
) -> Ty!Error {
  match expr {
    EInt(_) => TInt
    EBool(_) => TBool
    EVar(name) =>
      match env_lookup(env, name) {
        Some(scheme) => instantiate(scheme, ctx)
        None => fail!("unbound variable")
      }
    ELam(param, body) => {
      let param_ty = ctx.fresh()
      let new_env = env_extend(env, param, { vars: [], ty: param_ty })
      let body_ty = infer!(new_env, body, ctx, subst)
      TArrow(param_ty, body_ty)
    }
    EApp(func, arg) => {
      let func_ty = infer!(env, func, ctx, subst)
      let arg_ty = infer!(env, arg, ctx, subst)
      let ret_ty = ctx.fresh()
      unify!(func_ty, TArrow(arg_ty, ret_ty), subst)
      ret_ty
    }
    ELet(name, def, body) => {
      let def_ty = infer!(env, def, ctx, subst)
      let scheme = generalize(env, def_ty, subst)
      let new_env = env_extend(env, name, scheme)
      infer!(new_env, body, ctx, subst)
    }
    ELetRec(name, def, body) => {
      let rec_ty = ctx.fresh()
      let rec_env = env_extend(env, name, { vars: [], ty: rec_ty })
      let def_ty = infer!(rec_env, def, ctx, subst)
      unify!(rec_ty, def_ty, subst)
      let scheme = generalize(env, rec_ty, subst)
      let new_env = env_extend(env, name, scheme)
      infer!(new_env, body, ctx, subst)
    }
    EIf(cond, then_br, else_br) => {
      let cond_ty = infer!(env, cond, ctx, subst)
      unify!(cond_ty, TBool, subst)
      let then_ty = infer!(env, then_br, ctx, subst)
      let else_ty = infer!(env, else_br, ctx, subst)
      unify!(then_ty, else_ty, subst)
      then_ty
    }
    EBinOp(op, left, right) => {
      let left_ty = infer!(env, left, ctx, subst)
      let right_ty = infer!(env, right, ctx, subst)
      if op == "+" || op == "-" || op == "*" {
        unify!(left_ty, TInt, subst)
        unify!(right_ty, TInt, subst)
        TInt
      } else if op == "==" || op == "<" {
        unify!(left_ty, TInt, subst)
        unify!(right_ty, TInt, subst)
        TBool
      } else {
        fail!("unknown operator")
      }
    }
  }
}

// --- Type pretty-printer ----------------------------------------------------

///|
fn collect_vars_ordered(ty : Ty, result : Array[Int]) -> Unit {
  match ty {
    TVar(id) => {
      if not(result.contains(id)) {
        result.push(id)
      }
    }
    TArrow(t1, t2) => {
      collect_vars_ordered(t1, result)
      collect_vars_ordered(t2, result)
    }
    _ => ()
  }
}

///|
fn var_name(idx : Int) -> String {
  let names : FixedArray[String] = [
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j",
    "k", "l", "m", "n", "o", "p", "q", "r", "s", "t",
    "u", "v", "w", "x", "y", "z",
  ]
  if idx < 26 {
    names[idx]
  } else {
    "t\{idx}"
  }
}

///|
fn format_ty(
  ty : Ty,
  name_map : Array[(Int, String)],
  in_arrow_left : Bool
) -> String {
  match ty {
    TInt => "Int"
    TBool => "Bool"
    TVar(id) =>
      match subst_lookup_str(name_map, id) {
        Some(name) => name
        None => "?"
      }
    TArrow(t1, t2) => {
      let left = format_ty(t1, name_map, true)
      let right = format_ty(t2, name_map, false)
      if in_arrow_left {
        "(\{left} -> \{right})"
      } else {
        "\{left} -> \{right}"
      }
    }
  }
}

///|
fn subst_lookup_str(
  mapping : Array[(Int, String)],
  key : Int
) -> String? {
  let mut i = 0
  while i < mapping.length() {
    let entry = mapping[i]
    match entry {
      (k, v) => {
        if k == key {
          return Some(v)
        }
      }
    }
    i = i + 1
  }
  None
}

///|
fn type_to_string(ty : Ty, subst : Array[(Int, Ty)]) -> String {
  let resolved = apply_subst(subst, ty)
  let var_ids : Array[Int] = []
  collect_vars_ordered(resolved, var_ids)
  let name_map : Array[(Int, String)] = []
  let mut idx = 0
  while idx < var_ids.length() {
    name_map.push((var_ids[idx], var_name(idx)))
    idx = idx + 1
  }
  format_ty(resolved, name_map, false)
}

// --- Public entry point -----------------------------------------------------

///|
fn do_infer_impl(input : String) -> String!Error {
  let expr = parse!(input)
  let ctx = InferCtx::make()
  let subst : Array[(Int, Ty)] = []
  let env : Array[(String, Scheme)] = []
  let ty = infer!(env, expr, ctx, subst)
  type_to_string(ty, subst)
}

///|
pub fn infer_type(input : String) -> String {
  try {
    do_infer_impl!(input)
  } catch {
    _ => "TYPE ERROR"
  }
}
MOONBIT_ENGINE

echo "=== Building project ==="
cd /app
moon build 2>&1 || true

echo "=== Running tests ==="
moon test 2>&1
