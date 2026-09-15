
use serde::Serialize;
use std::env;
use std::fs;
use std::path::Path;

#[derive(Serialize)]
struct IsingInstance {
    #[serde(rename = "type")]
    instance_type: String,
    n: usize,
    couplings: Vec<[f64; 3]>,
    fields: Vec<f64>,
}

#[derive(Serialize)]
struct QuboInstance {
    #[serde(rename = "type")]
    instance_type: String,
    n: usize,
    #[serde(rename = "Q")]
    q_matrix: Vec<Vec<f64>>,
}

fn parse_ising(content: &str) -> IsingInstance {
    let mut n: usize = 0;
    let mut couplings: Vec<[f64; 3]> = Vec::new();
    let mut fields: Vec<f64> = Vec::new();

    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.is_empty() {
            continue;
        }
        match parts[0] {
            "N" => {
                n = parts[1].parse().unwrap();
                fields = vec![0.0; n];
            }
            "J" => {
                let i: usize = parts[1].parse().unwrap();
                let j: usize = parts[2].parse().unwrap();
                let val: f64 = parts[3].parse().unwrap();
                couplings.push([i as f64, j as f64, val]);
            }
            "H" => {
                let i: usize = parts[1].parse().unwrap();
                let val: f64 = parts[2].parse().unwrap();
                fields[i] = val;
            }
            _ => {}
        }
    }

    IsingInstance {
        instance_type: "ising".to_string(),
        n,
        couplings,
        fields,
    }
}

fn parse_qubo(content: &str) -> QuboInstance {
    let mut n: usize = 0;
    let mut q_matrix: Vec<Vec<f64>> = Vec::new();

    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.is_empty() {
            continue;
        }
        match parts[0] {
            "N" => {
                n = parts[1].parse().unwrap();
                q_matrix = vec![vec![0.0; n]; n];
            }
            "Q" => {
                let i: usize = parts[1].parse().unwrap();
                let j: usize = parts[2].parse().unwrap();
                let val: f64 = parts[3].parse().unwrap();
                q_matrix[i][j] = val;
            }
            _ => {}
        }
    }

    QuboInstance {
        instance_type: "qubo".to_string(),
        n,
        q_matrix,
    }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 {
        eprintln!("Usage: ising-converter <input_dir> <output_dir>");
        std::process::exit(1);
    }

    let input_dir = &args[1];
    let output_dir = &args[2];

    fs::create_dir_all(output_dir).unwrap();

    for entry in fs::read_dir(input_dir).unwrap() {
        let entry = entry.unwrap();
        let path = entry.path();
        let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");

        if ext != "ising" && ext != "qubo" {
            continue;
        }

        let content = fs::read_to_string(&path).unwrap();
        let stem = path.file_stem().unwrap().to_str().unwrap();
        let output_path = Path::new(output_dir).join(format!("{}.json", stem));

        let json = match ext {
            "ising" => {
                let instance = parse_ising(&content);
                serde_json::to_string_pretty(&instance).unwrap()
            }
            "qubo" => {
                let instance = parse_qubo(&content);
                serde_json::to_string_pretty(&instance).unwrap()
            }
            _ => continue,
        };

        fs::write(&output_path, json).unwrap();
        println!("Converted {} -> {}", path.display(), output_path.display());
    }
}
