% Handler result composition using delimited continuations.
% Demonstrates that resume(v) returns the body's eventual result,
% and the handler can transform this result before returning.
%
% Pattern:
%   body: shift with arg=10, gets back X, returns X*3
%   handler: provides X = arg+5 = 15, gets body result = 45,
%            returns body_result + 100 = 145
%
% Run: swipl compose.pl

body_compose(Result) :-
    shift(eff(10, X)),
    Result is X * 3.

handle_compose(Final) :-
    reset(body_compose(BodyResult), Ball, Cont),
    (   Cont == 0
    ->  Final = BodyResult
    ;   Ball = eff(Arg, X)
    ->  X is Arg + 5,
        handle_resume(Cont, BodyResult, Final)
    ).

handle_resume(Cont, BodyResult, Final) :-
    reset(Cont, _, Cont2),
    (   Cont2 == 0
    ->  Final is BodyResult + 100
    ;   Final = error
    ).

main :-
    handle_compose(R),
    format("compose=~w~n", [R]),
    halt(0).

:- initialization(main).
