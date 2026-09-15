import modelchecker.*;
import programs.*;


/**
 * Entry point: runs the model checker on all test programs and prints results.
 */
public class Main {
    public static void main(String[] args) {
        boolean por = false;
        for (String arg : args) {
            if ("--por".equals(arg)) por = true;
        }

        ModelChecker checker = new ModelChecker(por);
        ConcurrentProgram[] programs = Programs.all();

        for (ConcurrentProgram prog : programs) {
            CheckerResult result = checker.check(prog);
            System.out.println("PROGRAM: " + prog.name);
            System.out.println("STATES: " + result.statesExplored);
            System.out.println("TRANSITIONS: " + result.transitionsExplored);
            System.out.println("VIOLATIONS: " + result.violations.size());
            for (Violation v : result.violations) {
                System.out.println("VIOLATION: " + v.type + ": " + v.message);
            }
            System.out.println("---");
        }
    }
}
