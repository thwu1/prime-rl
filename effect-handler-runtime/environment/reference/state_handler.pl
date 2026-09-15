% State effect handler using delimited continuations (reset/3, shift/1).
% Demonstrates the get/put pattern for mutable-state effects.
%
% The body performs get to read state and put to update it.
% The handler threads state through recursive reset/shift calls.
%
% Run: swipl state_handler.pl

body_state :-
    shift(get(X)),
    X1 is X + 1,
    shift(put(X1)),
    shift(get(Y)),
    Y1 is Y * 2,
    shift(put(Y1)),
    shift(get(Final)),
    format("final=~w~n", [Final]).

run_state(Goal, State) :-
    reset(Goal, Ball, Cont),
    (   Cont == 0
    ->  true
    ;   Ball = get(V)
    ->  V = State,
        run_state(Cont, State)
    ;   Ball = put(NewState)
    ->  run_state(Cont, NewState)
    ).

main :-
    format("init=0~n"),
    run_state(body_state, 0),
    format("init=10~n"),
    run_state(body_state, 10),
    halt(0).

:- initialization(main).
