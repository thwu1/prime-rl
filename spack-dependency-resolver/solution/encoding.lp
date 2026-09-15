% ==============================================================================
% ASP Encoding for HPC Package Dependency Resolution
% ==============================================================================
%
% This encoding is invoked by a Python driver that generates ground facts
% describing the package repository and user request. The encoding selects
% versions, assigns variants, activates conditional dependencies, resolves
% virtual packages to concrete providers, detects conflicts, and optimizes
% for latest versions and preferred providers.
%
% Expected fact predicates from the driver:
%   root/1, avail/2, vpri/3, var_bool/3, var_enum/3,
%   dep/3, dep_has_cond/3, dep_cond_var/5, dep_cond_ver/4,
%   dep_vrange/4, dep_req_var/5,
%   conflict/2, conflict_has_ver/2, conflict_ver/3,
%   conflict_has_var/2, conflict_var/4,
%   virtual/1, provider/3, provides_virtual/2,
%   vconstraint/2, v_in_range/3,
%   user_variant/3, user_provider/2

% --- Package installation ---
% The root package is always installed.
installed(P) :- root(P).
% A package is installed if it appears as a dependency target.
installed(D) :- dep_edge(_, D).
% A chosen provider is installed.
installed(Prov) :- chosen_provider(_, Prov).

% --- Version selection ---
% Select exactly one version for each installed concrete package.
1 { selected(P, V) : avail(P, V) } 1 :- installed(P), not virtual(P).

% --- Version constraints ---
% Every version constraint on a package must be satisfied.
:- selected(P, V), vconstraint(P, R), not v_in_range(P, V, R).

% --- Variant assignment ---
% Boolean variant: use default when not forced.
variant_val(P, Var, Def) :- installed(P), not virtual(P),
    var_bool(P, Var, Def), not var_forced(P, Var).

% Enum variant: use default when not forced.
variant_val(P, Var, Def) :- installed(P), not virtual(P),
    var_enum(P, Var, Def), not var_forced(P, Var).

% Forced variant value (from required_variants, user overrides, etc.)
variant_val(P, Var, Val) :- var_force(P, Var, Val), installed(P), not virtual(P).
var_forced(P, Var) :- var_force(P, Var, _), installed(P).

% Conflicting forced values are unsatisfiable.
:- var_force(P, Var, V1), var_force(P, Var, V2), V1 != V2, installed(P).

% --- Dependency activation ---
% Unconditional dependency.
dep_active(P, D, DID) :- installed(P), dep(P, D, DID),
    not dep_has_cond(P, D, DID).

% Variant-positive condition (+var).
dep_active(P, D, DID) :- installed(P), dep(P, D, DID),
    dep_cond_var(P, D, DID, Var, true),
    variant_val(P, Var, true).

% Variant-negative condition (~var).
dep_active(P, D, DID) :- installed(P), dep(P, D, DID),
    dep_cond_var(P, D, DID, Var, false),
    variant_val(P, Var, false).

% Version condition (@range).
dep_active(P, D, DID) :- installed(P), dep(P, D, DID),
    dep_cond_ver(P, D, DID, VR),
    selected(P, V),
    v_in_range(P, V, VR).

% --- Virtual package resolution ---
% A virtual is needed when any active dependency targets it.
needs_virtual(Virt) :- dep_active(_, Virt, _), virtual(Virt).

% Select exactly one provider for each needed virtual.
1 { chosen_provider(Virt, Prov) : provider(Virt, Prov, _) } 1 :-
    needs_virtual(Virt).

% Provider consistency: if a chosen provider also provides another
% needed virtual, it must be chosen for that virtual too.
:- chosen_provider(V1, Prov), provides_virtual(Prov, V2),
   needs_virtual(V2), not chosen_provider(V2, Prov).

% User-forced provider constraint.
:- user_provider(Virt, Prov), chosen_provider(Virt, Other), Prov != Other.

% --- Dependency edges ---
% For virtual deps: edge goes to the chosen provider.
dep_edge(P, Prov) :- dep_active(P, Virt, _), virtual(Virt),
    chosen_provider(Virt, Prov).
% For concrete deps: edge goes directly to the dependency.
dep_edge(P, D) :- dep_active(P, D, _), not virtual(D).

% --- Version constraints from dependency declarations ---
% Concrete dependency version range.
vconstraint(D, VR) :- dep_active(P, D, DID), dep_vrange(P, D, DID, VR),
    not virtual(D).
% Virtual dependency version range transfers to provider.
vconstraint(Prov, VR) :- dep_active(P, Virt, DID), virtual(Virt),
    chosen_provider(Virt, Prov), dep_vrange(P, Virt, DID, VR).

% --- Required variant propagation ---
% Concrete dependency required variants.
var_force(D, Var, Val) :- dep_active(P, D, DID),
    dep_req_var(P, D, DID, Var, Val), not virtual(D).
% Virtual dependency required variants transfer to provider.
var_force(Prov, Var, Val) :- dep_active(P, Virt, DID), virtual(Virt),
    chosen_provider(Virt, Prov), dep_req_var(P, Virt, DID, Var, Val).

% User variant overrides.
var_force(P, Var, Val) :- user_variant(P, Var, Val).

% --- Conflict detection ---
% A conflict is triggered if both version and variant parts match.
:- installed(P), conflict(P, CID), conflict_matches(P, CID).

conflict_matches(P, CID) :- conflict(P, CID),
    conflict_ver_ok(P, CID), conflict_var_ok(P, CID).

% Version part: matches if no version constraint or version is in range.
conflict_ver_ok(P, CID) :- conflict(P, CID), not conflict_has_ver(P, CID).
conflict_ver_ok(P, CID) :- conflict(P, CID), conflict_ver(P, CID, VR),
    selected(P, V), v_in_range(P, V, VR).

% Variant part: matches if no variant constraint or all variants match.
conflict_var_ok(P, CID) :- conflict(P, CID), not conflict_has_var(P, CID).
conflict_var_ok(P, CID) :- conflict(P, CID), conflict_has_var(P, CID),
    not conflict_var_fail(P, CID).

% A conflict variant fails to match if any specified variant differs.
conflict_var_fail(P, CID) :- conflict_var(P, CID, Var, Val),
    variant_val(P, Var, ActVal), Val != ActVal.
conflict_var_fail(P, CID) :- conflict_var(P, CID, Var, _),
    installed(P), not has_variant_val(P, Var).

has_variant_val(P, Var) :- variant_val(P, Var, _).

% --- Optimization ---
% Prefer latest versions (lower priority index = better).
#minimize { Pri@2,P,V : selected(P, V), vpri(P, V, Pri) }.
% Prefer first-listed providers (lower priority index = better).
#minimize { Pri@1,Virt,Prov : chosen_provider(Virt, Prov), provider(Virt, Prov, Pri) }.

% --- Output projection ---
#show selected/2.
#show variant_val/3.
#show dep_edge/2.
#show chosen_provider/2.
#show installed/1.
