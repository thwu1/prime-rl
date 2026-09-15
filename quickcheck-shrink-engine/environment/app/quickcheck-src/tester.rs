// Excerpts from BurntSushi's quickcheck crate — tester.rs
// https://github.com/BurntSushi/quickcheck
// License: MIT / UNLICENSE
//
// This file contains the QuickCheck test runner, TestResult, and the
// Testable trait including the shrinking loop.

use std::cmp;
use std::env;
use std::fmt::Debug;
use std::panic;

use crate::{
    tester::Status::{Discard, Fail, Pass},
    Arbitrary, Gen,
};

/// The main `QuickCheck` type for setting configuration and running
/// `QuickCheck`.
pub struct QuickCheck {
    tests: u64,
    max_tests: u64,
    min_tests_passed: u64,
    rng: Gen,
}

impl QuickCheck {
    pub fn new() -> QuickCheck {
        let rng = Gen::new(100);
        QuickCheck { tests: 100, max_tests: 10_000, min_tests_passed: 0, rng }
    }

    pub fn tests(mut self, tests: u64) -> QuickCheck {
        self.tests = tests;
        self
    }

    pub fn max_tests(mut self, max_tests: u64) -> QuickCheck {
        self.max_tests = max_tests;
        self
    }

    /// Tests a property and returns the result.
    pub fn quicktest<A>(&mut self, f: A) -> Result<u64, TestResult>
    where
        A: Testable,
    {
        let mut n_tests_passed = 0;
        for _ in 0..self.max_tests {
            if n_tests_passed >= self.tests {
                break;
            }
            match f.result(&mut self.rng) {
                TestResult { status: Pass, .. } => n_tests_passed += 1,
                TestResult { status: Discard, .. } => continue,
                r @ TestResult { status: Fail, .. } => return Err(r),
            }
        }
        Ok(n_tests_passed)
    }
}

/// Describes the status of a single instance of a test.
#[derive(Clone, Debug)]
pub struct TestResult {
    status: Status,
    arguments: Option<Vec<String>>,
    err: Option<String>,
}

#[derive(Clone, Debug)]
enum Status {
    Pass,
    Fail,
    Discard,
}

impl TestResult {
    pub fn passed() -> TestResult {
        TestResult::from_bool(true)
    }

    pub fn failed() -> TestResult {
        TestResult::from_bool(false)
    }

    pub fn discard() -> TestResult {
        TestResult { status: Discard, arguments: None, err: None }
    }

    pub fn from_bool(b: bool) -> TestResult {
        TestResult {
            status: if b { Pass } else { Fail },
            arguments: None,
            err: None,
        }
    }

    pub fn is_failure(&self) -> bool {
        match self.status {
            Fail => true,
            Pass | Discard => false,
        }
    }
}

/// `Testable` describes types whose values can be tested.
pub trait Testable: 'static {
    fn result(&self, _: &mut Gen) -> TestResult;
}

impl Testable for bool {
    fn result(&self, _: &mut Gen) -> TestResult {
        TestResult::from_bool(*self)
    }
}

impl Testable for TestResult {
    fn result(&self, _: &mut Gen) -> TestResult {
        self.clone()
    }
}

/// The core shrinking loop used by the Testable implementation for functions.
/// When a failure is found, it shrinks the failing input by iterating through
/// candidates from the shrinker. The first candidate that also fails becomes
/// the new input to shrink from — the iterator is replaced immediately.
macro_rules! testable_fn {
    ($($name: ident),*) => {

impl<T: Testable,
     $($name: Arbitrary + Debug),*> Testable for fn($($name),*) -> T {
    #[allow(non_snake_case)]
    fn result(&self, g: &mut Gen) -> TestResult {
        let self_ = *self;
        let a: ($($name,)*) = Arbitrary::arbitrary(g);
        let ( $($name,)* ) = a.clone();
        let mut r = safe(move || {self_($($name),*)}).result(g);

        if r.is_failure() {
            // Shrinking: iterate through shrunk candidates.
            // When a candidate also fails, switch to shrinking THAT value
            // instead (greedy descent toward minimal counterexample).
            let mut a = a.shrink();
            while let Some(t) = a.next() {
                let ($($name,)*) = t.clone();
                let mut r_new = safe(move || {self_($($name),*)}).result(g);
                if r_new.is_failure() {
                    r = r_new;

                    // Switch to shrinking the new, smaller failing value.
                    // This replaces the current iterator, so remaining
                    // candidates from the previous level are abandoned.
                    a = t.shrink()
                }
            }
        }

        r
    }
}}}

fn safe<T, F>(fun: F) -> Result<T, String>
where
    F: FnOnce() -> T,
    F: 'static,
    T: 'static,
{
    panic::catch_unwind(panic::AssertUnwindSafe(fun)).map_err(|any_err| {
        if let Some(&s) = any_err.downcast_ref::<&str>() {
            s.to_owned()
        } else if let Some(s) = any_err.downcast_ref::<String>() {
            s.to_owned()
        } else {
            "UNABLE TO SHOW RESULT OF PANIC.".to_owned()
        }
    })
}
