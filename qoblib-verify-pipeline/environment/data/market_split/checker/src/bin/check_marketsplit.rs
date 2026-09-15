// QOBLIB Market Split Problem Solution Checker
// Part of QOBLIB - Quantum Optimization Benchmarking Library
// Licensed under the Apache License, Version 2.0
// Copyright (C) 2025 by Thorsten Koch

const VERSION : &str = "1.0";

use std::fs;
use std::env;
use regex::Regex;

fn extract_solution_01(data : &[u8], dim : usize) -> Vec<u32> {
    let mut solution = Vec::<u32>::new();
    let mut i = 0;
    while i < data.len() {
        let c = data[i] as char;
        if c == '0' || c == '1' {
            solution.push((data[i] - b'0') as u32);
        } else if !c.is_ascii_whitespace() && !c.is_ascii_punctuation() {
            panic!("Parsing solution. Expected 0/1 found {}", c);
        }
        i += 1;
    }
    if solution.len() != dim {
        panic!("Expected solution length {dim} but found {}", solution.len());
    }
    solution
}

fn extract_solution_numb(data : &[u8], dim : usize) -> Vec<u32> {
    let mut solution   = vec![0u32; dim];
    let mut lineno = 1;
    let mut index  = 0;
    let mut i      = 0;

    while i < data.len() {
        let c = data[i] as char;

        if c.is_ascii_whitespace() || c.is_ascii_punctuation() {
            if index > 0 {
                solution[index - 1] = 1;
                index = 0;
            }
            if c == '\n' {
                lineno += 1;
            }
        }
        if c.is_ascii_digit() {
            index = index * 10 + ((data[i] - b'0') as usize);
            if index > dim {
                panic!("Solution line {lineno}. Expected variable index between 1..{dim}: found {index}");
            }
        }
        i += 1;
    }
    solution
}

fn extract_solution_text(data: &[u8], dim: usize) -> Vec<u32> {
    let mut solution = vec![0u32; dim];
    let re = Regex::new(r"x#(\d+)\s+([01])").unwrap();
    let text = std::str::from_utf8(data).expect("Invalid UTF-8 sequence");

    for (lineno, cap) in re.captures_iter(text).enumerate() {
        let index: usize = cap[1].parse().unwrap_or_else(|err| panic!("Solution line {}. Expected variable index: {err}", lineno + 1));
        if index < 1 || index > dim {
            panic!("Solution line {}. Expected variable index between 1..{}: found {}", lineno + 1, dim, index);
        }
        let value: u32 = cap[2].parse().unwrap();
        solution[index - 1] = value;
    }
    solution
}

#[derive(PartialEq)]
enum SolutionFormat {
    OnlySpace,
    ZeroOneVec,
    IndexList,
    XVarList,
}

fn detect_solution_format(data : &[u8]) -> SolutionFormat {
    let mut format = SolutionFormat::OnlySpace;

    for b in data {
        let c = *b as char;

        if format == SolutionFormat::OnlySpace && !c.is_ascii_whitespace() {
            format = SolutionFormat::ZeroOneVec;
        }
        if format == SolutionFormat::ZeroOneVec && !c.is_ascii_whitespace() && !c.is_ascii_punctuation() && c != '0' && c != '1' {
            format = SolutionFormat::IndexList;
        }
        if format == SolutionFormat::IndexList && !c.is_ascii_whitespace() && !c.is_ascii_punctuation() && !c.is_ascii_digit() {
            format = SolutionFormat::XVarList;
            break;
        }
    }
    format
}

fn extract_solution(data : &[u8], dim : usize) -> Vec<u32> {
    match detect_solution_format(data) {
        SolutionFormat::OnlySpace  => panic!("Parsing solution: found empty file"),
        SolutionFormat::ZeroOneVec => extract_solution_01(data, dim),
        SolutionFormat::IndexList  => extract_solution_numb(data, dim),
        SolutionFormat::XVarList   => extract_solution_text(data, dim)
    }
}

fn verify_solution(instance_data : &str, solution_data : &[u8]) -> bool {
    let mut solution = Vec::<u32>::new();
    let mut num_cons = 0;
    let mut num_vars = 0;
    let mut cnt_cons = 0;
    let mut verified = true;

    for (lineno, line) in instance_data.replace(",", " ").lines().enumerate() {
        let fields : Vec<&str> = line.split_whitespace().collect();

        if fields.is_empty() || fields[0].starts_with('#') {
            continue;
        }
        if fields.len() >= 2 && num_cons == 0 && num_vars == 0 {
            num_cons = fields[0].parse::<usize>().unwrap_or_else(|err| panic!("Line {} expected number of constraints: {err}", lineno + 1));
            num_vars = fields[1].parse::<usize>().unwrap_or_else(|err| panic!("Line {} expected number of variables: {err}", lineno + 1));

            solution = extract_solution(solution_data, num_vars);
            println!("Problem has {num_vars} variables.");
            continue;
        }
        if fields.len() > num_vars && num_cons > 0 {
            let mut sum = 0;
            let mut tot = 0;

            for i in 0..num_vars {
                let val : u32 = fields[i].parse().unwrap_or_else(|err| panic!("Line {} expected value: {err}", lineno + 1));
                tot += val;
                sum += val * solution[i];
            }
            let rhs : u32 = fields[num_vars].parse().unwrap_or_else(|err| panic!("Line {} expected value: {err}", lineno + 1));

            cnt_cons += 1;

            if tot / 2 != rhs {
                panic!("Constraint {cnt_cons} line {} RHS expected {} found {rhs}", lineno + 1, tot / 2);
            }

            print!("Constraint {cnt_cons} ");
            if sum == rhs {
                println!("ok");
            } else {
                println!("failed: expected {rhs} got {sum}");
                verified = false;
            }
            continue;
        }
        panic!("Line {} syntax error", lineno + 1);
    }
    if cnt_cons != num_cons {
        panic!("Expected {num_cons} constraints, got {cnt_cons}");
    }

    verified
}

fn main() {
    println!("Qbench Market Split Solution Checker Version {VERSION}");

    let args: Vec<String> = env::args().collect();

    if args.len() < 3 {
        panic!("usage: {} instance-file solution-file|01-string", &args[0]);
    }
    let instance_data = fs::read_to_string(&args[1]).unwrap_or_else(|err| panic!("Reading {} failed: {err}", args[1]));

    let solution_arg = &args[2];

    let is_binary = |s: &str| s.chars().all(|c| c == '0' || c == '1');

    let solution_data = if is_binary(solution_arg) {
        solution_arg.as_bytes().to_vec()
    } else {
        fs::read(solution_arg).unwrap_or_else(|err| panic!("Reading {} failed: {err}", solution_arg))
    };

    if verify_solution(&instance_data, &solution_data) {
        println!("VALID: Solution successfully verified");
        std::process::exit(0);
    } else {
        println!("INVALID: Solution failed verification");
        std::process::exit(1);
    }
}
