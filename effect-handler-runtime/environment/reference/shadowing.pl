% Handler shadowing: inner handler shadows outer handler for the same effect.
% Uses delimited continuations to demonstrate lexical handler scoping.
%
% outer_body performs ask, gets value from OUTER handler,
% then sets up an inner handler that shadows ask,
% inner_body performs ask, gets value from INNER handler.
%
% Run: swipl shadowing.pl

inner_body(Result) :-
    shift(ask(Result)).

outer_body(OuterResult, InnerResult) :-
    shift(ask(OuterResult)),
    run_inner(InnerResult).

run_inner(Result) :-
    reset(inner_body(Result), Ball, Cont),
    (   Cont == 0
    ->  true
    ;   Ball = ask(V)
    ->  V = inner_val,
        call(Cont)
    ).

run_outer :-
    reset(outer_body(OV, IR), Ball, Cont),
    (   Cont == 0
    ->  format("outer=~w~n", [OV]),
        format("inner=~w~n", [IR])
    ;   Ball = ask(V)
    ->  V = outer_val,
        finish_outer(Cont, OV, IR)
    ).

finish_outer(Cont, OV, IR) :-
    reset(Cont, _, Cont2),
    (   Cont2 == 0
    ->  format("outer=~w~n", [OV]),
        format("inner=~w~n", [IR])
    ;   true
    ).

main :-
    run_outer,
    halt(0).

:- initialization(main).
