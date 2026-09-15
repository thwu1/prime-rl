% Collector (emit/collect) effect using delimited continuations.
% Demonstrates sequential effect operations accumulated into a list.
%
% The body emits values one at a time via shift.
% The handler collects all emitted values into a Prolog list.
%
% Run: swipl collector.pl

body_collector :-
    shift(emit(a)),
    shift(emit(b)),
    shift(emit(c)).

run_collector(Goal, Collected) :-
    reset(Goal, Ball, Cont),
    (   Cont == 0
    ->  Collected = []
    ;   Ball = emit(V)
    ->  run_collector(Cont, Rest),
        Collected = [V|Rest]
    ).

main :-
    run_collector(body_collector, Items),
    format("collected=~w~n", [Items]),
    halt(0).

:- initialization(main).
