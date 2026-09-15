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

fn load_config(path: &str) -> Config {
    let data = fs::read_to_string(path).unwrap();
    let config: Config = serde_json::from_str(&data).unwrap();
    config
}

fn init_model(config: Config) -> LoadedModel {
    // Validate feature count against memory preallocation limit
    let validated_count = validate_feature_count(config.features.len()).unwrap();

    // Pre-allocate memory slots for feature values
    let feature_slots = vec![None; validated_count];

    LoadedModel {
        features: config.features,
        feature_slots,
    }
}

fn main() {
    let config_path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "/app/config/features.json".to_string());

    println!("Loading feature config from: {}", config_path);

    let config = load_config(&config_path);
    println!("Loaded {} features", config.features.len());

    let model = init_model(config);
    println!(
        "Model initialized with {} feature slots",
        model.feature_slots.len()
    );

    println!(
        "{{\"status\": \"ok\", \"features_loaded\": {}, \"slots_allocated\": {}}}",
        model.features.len(),
        model.feature_slots.len()
    );
}
