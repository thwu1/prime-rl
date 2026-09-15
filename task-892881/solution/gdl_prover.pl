% gdl_prover.pl - GDL inference helpers for SWI-Prolog
%
% Provides dynamic state/move context, query entry points, and
% term-to-KIF output conversion for the GDL state machine engine.
%

:- style_check(-discontiguous).
:- style_check(-singleton).

:- dynamic gdl_true/1.
:- dynamic gdl_does/2.

% Clear all dynamic context (state + moves)
clear_ctx :-
    retractall(gdl_true(_)),
    retractall(gdl_does(_, _)).

% ---- Term to KIF string conversion ----

to_kif(T, S) :-
    number(T), !,
    number_codes(T, C),
    atom_codes(S, C).
to_kif(T, S) :-
    atom(T), !, S = T.
to_kif(T, S) :-
    compound(T),
    T =.. [F|Args],
    maplist(to_kif, Args, KifArgs),
    atomic_list_concat(KifArgs, ' ', ArgsStr),
    format(atom(S), "(~w ~w)", [F, ArgsStr]).

% Print a list of terms as sorted KIF strings, one per line
print_results(Terms) :-
    maplist(to_kif, Terms, Strs),
    sort(Strs, Sorted),
    forall(member(S, Sorted), writeln(S)).

% ---- Query entry points ----

do_roles :-
    findall(R, gdl_role(R), Rs),
    sort(Rs, Sorted),
    forall(member(R, Sorted), writeln(R)).

do_initial :-
    findall(F, gdl_init(F), Fs),
    print_results(Fs).

do_legal(Role) :-
    findall(M, gdl_legal(Role, M), Ms),
    sort(Ms, Unique),
    print_results(Unique).

do_next :-
    findall(F, gdl_next(F), Fs),
    sort(Fs, Unique),
    print_results(Unique).

do_terminal :-
    (gdl_terminal -> writeln(true) ; writeln(false)).

do_goal(Role) :-
    (gdl_goal(Role, V) -> writeln(V) ; writeln(none)).
