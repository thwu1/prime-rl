use std::fs;

mod parser;

fn main() {
    let input_path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "/app/input.txt".to_string());
    let output_path = std::env::args()
        .nth(2)
        .unwrap_or_else(|| "/app/output.json".to_string());

    let input =
        fs::read_to_string(&input_path).unwrap_or_else(|e| panic!("Failed to read {}: {}", input_path, e));

    let mut results: Vec<parser::ParseResult> = Vec::new();

    for line in input.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let result = parser::parse_proforma(line);
        results.push(result);
    }

    let json = serde_json::to_string_pretty(&results).expect("Failed to serialize results");
    fs::write(&output_path, &json)
        .unwrap_or_else(|e| panic!("Failed to write {}: {}", output_path, e));

    eprintln!(
        "Parsed {} ProForma strings -> {}",
        results.len(),
        output_path
    );
}
