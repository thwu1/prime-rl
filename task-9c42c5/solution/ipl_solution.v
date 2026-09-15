
Require Import Ltac2.Ltac2.

Module IPLSolver.

  Import Ltac2.Control.
  Import Ltac2.Std.

  Ltac2 Type exn ::= [ SearchFailed ].

  Ltac2 rec solve_prop (depth : int) : unit :=
    if Int.le depth 0 then Control.zero SearchFailed
    else
      let d := Int.sub depth 1 in

      (* 1: exact match via assumption *)
      Control.plus (fun () =>
        Std.assumption ()
      ) (fun _ =>

      (* 2: goal is True *)
      Control.plus (fun () =>
        match! goal with
        | [ |- True ] => Std.constructor false
        end
      ) (fun _ =>

      (* 3: False hypothesis — ex falso *)
      Control.plus (fun () =>
        match! goal with
        | [ h : False |- _ ] =>
            let hv := Control.hyp h in
            Std.case false (hv, NoBindings)
        end
      ) (fun _ =>

      (* 4: conjunction goal — split and recurse *)
      Control.plus (fun () =>
        match! goal with
        | [ |- _ /\ _ ] =>
            Std.split false NoBindings;
            Control.enter (fun () => solve_prop d)
        end
      ) (fun _ =>

      (* 5: iff goal — split and recurse *)
      Control.plus (fun () =>
        match! goal with
        | [ |- _ <-> _ ] =>
            Std.split false NoBindings;
            Control.enter (fun () => solve_prop d)
        end
      ) (fun _ =>

      (* 6: implication/forall goal — intro, no depth consumed *)
      Control.plus (fun () =>
        match! goal with
        | [ |- _ -> _ ] =>
            Std.intro None None;
            solve_prop depth
        end
      ) (fun _ =>

      (* 7: negation goal — intro on not A, no depth consumed *)
      Control.plus (fun () =>
        match! goal with
        | [ |- not _ ] =>
            Std.intro None None;
            solve_prop depth
        end
      ) (fun _ =>

      (* 8: conjunction hypothesis — decompose *)
      Control.plus (fun () =>
        match! goal with
        | [ h : _ /\ _ |- _ ] =>
            let hv := Control.hyp h in
            Std.case false (hv, NoBindings);
            Std.clear [h];
            Std.intro None None;
            Std.intro None None;
            solve_prop depth
        end
      ) (fun _ =>

      (* 9: iff hypothesis — decompose *)
      Control.plus (fun () =>
        match! goal with
        | [ h : _ <-> _ |- _ ] =>
            let hv := Control.hyp h in
            Std.case false (hv, NoBindings);
            Std.clear [h];
            Std.intro None None;
            Std.intro None None;
            solve_prop depth
        end
      ) (fun _ =>

      (* 10: disjunction hypothesis — case split *)
      Control.plus (fun () =>
        match! goal with
        | [ h : _ \/ _ |- _ ] =>
            let hv := Control.hyp h in
            Std.case false (hv, NoBindings);
            Control.enter (fun () =>
              Std.clear [h];
              Std.intro None None;
              solve_prop d)
        end
      ) (fun _ =>

      (* 11: left for disjunction goal *)
      Control.plus (fun () =>
        match! goal with
        | [ |- _ \/ _ ] =>
            Std.left false NoBindings;
            solve_prop d
        end
      ) (fun _ =>

      (* 12: right for disjunction goal *)
      Control.plus (fun () =>
        match! goal with
        | [ |- _ \/ _ ] =>
            Std.right false NoBindings;
            solve_prop d
        end
      ) (fun _ =>

      (* 13: backward chaining — apply implication hypothesis *)
      Control.plus (fun () =>
        match! goal with
        | [ h : _ -> _ |- _ ] =>
            Std.apply false true
              [(fun () => (Control.hyp h, NoBindings))] None;
            Control.enter (fun () => solve_prop d)
        end
      ) (fun _ =>

        (* 14: backward chaining — apply negation hypothesis *)
        match! goal with
        | [ h : not _ |- _ ] =>
            Std.apply false true
              [(fun () => (Control.hyp h, NoBindings))] None;
            Control.enter (fun () => solve_prop d)
        end

      )))))))))))))
    .

  Ltac2 ipl_auto () : unit := solve_prop 20.

End IPLSolver.
