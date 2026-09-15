use std::fs;

const MAX_FEATURES: usize = 200;

#[derive(serde::Deserialize, Debug)]
struct Config {
    version: String,
    model_id: String,
    features: Vec<Feature>,
    feature_count: usize,
}

#[derive(serde::Deserialize, Debug, Clone)]
struct Feature {
    name: String,
    #[serde(rename = "type")]
    feature_type: String,
}

struct LoadedModel {
    features: Vec<Feature>,
    feature_slots: Vec<Option<f64>>,
}

fn validate_feature_count(count: usize) -> Result<usize, String> {
    if count > MAX_FEATURES {
        Err(format!(
            "Feature count {} exceeds maximum allowed {}",
            count, MAX_FEATURES
        ))
    } else {
        Ok(count)
    }
}

fn load_config(path: &str) -> Result<Config, String> {
    let data = fs::read_to_string(path)
        .map_err(|e| format!("Failed to read config file '{}': {}", path, e))?;
    let config: Config = serde_json::from_str(&data)
        .map_err(|e| format!("Failed to parse config JSON: {}", e))?;
    Ok(config)
}

fn init_model(config: Config) -> LoadedModel {
    match validate_feature_count(config.features.len()) {
        Ok(count) => {
            // Normal path: allocate feature slots
            let feature_slots = vec![None; count];
            LoadedModel {
                features: config.features,
                feature_slots,
            }
        }
        Err(msg) => {
            // Fail open: log warning and return empty model
            // Traffic continues without bot scoring rather than dropping requests
            eprintln!("WARNING: {}. Failing open with empty feature set.", msg);
            LoadedModel {
                features: Vec::new(),
                feature_slots: Vec::new(),
            }
        }
    }
}

fn main() {
    let config_path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "/app/config/features.json".to_string());

    println!("Loading feature config from: {}", config_path);

    let config = match load_config(&config_path) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("WARNING: {}. Failing open with defaults.", e);
            println!(
                "{{\"status\": \"degraded\", \"features_loaded\": 0, \"slots_allocated\": 0}}"
            );
            return;
        }
    };

    let original_count = config.features.len();
    println!("Loaded {} features from config", original_count);

    let model = init_model(config);

    let status = if model.features.len() < original_count {
        "degraded"
    } else {
        "ok"
    };
    println!(
        "{{\"status\": \"{}\", \"features_loaded\": {}, \"slots_allocated\": {}}}",
        status,
        model.features.len(),
        model.feature_slots.len()
    );
}
