
use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use tantivy::collector::TopDocs;
use tantivy::query::QueryParser;
use tantivy::schema::*;
use tantivy::{doc, DocAddress, Index, IndexWriter, Score};

const REFERENCE_EPOCH: f64 = 1750000000.0;

#[derive(Deserialize)]
struct CorpusDoc {
    id: u64,
    title: String,
    body: String,
    popularity: u64,
    published_epoch: u64,
}

#[derive(Serialize)]
struct ResultDoc {
    id: u64,
    title: String,
    bm25_score: f64,
    compound_score: f64,
    popularity: u64,
    published_epoch: u64,
}

fn compute_compound_score(bm25: f64, popularity: u64, published_epoch: u64) -> f64 {
    let popularity_factor = 1.0 + (1.0 + popularity as f64).ln() / 1001.0_f64.ln();
    let age_days = (REFERENCE_EPOCH - published_epoch as f64) / 86400.0;
    let recency_factor = 1.0 / (1.0 + 0.02 * age_days);
    bm25 * popularity_factor * recency_factor
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Read corpus
    let corpus_str = std::fs::read_to_string("/app/corpus.json")?;
    let corpus: Vec<CorpusDoc> = serde_json::from_str(&corpus_str)?;

    // Build schema: text fields for search, u64 stored fields for metadata
    let mut schema_builder = Schema::builder();
    let title_field = schema_builder.add_text_field("title", TEXT | STORED);
    let body_field = schema_builder.add_text_field("body", TEXT);
    let _id_field = schema_builder.add_u64_field(
        "id",
        NumericOptions::default().set_stored().set_fast(),
    );
    let _popularity_field = schema_builder.add_u64_field(
        "popularity",
        NumericOptions::default().set_stored().set_fast(),
    );
    let _published_epoch_field = schema_builder.add_u64_field(
        "published_epoch",
        NumericOptions::default().set_stored().set_fast(),
    );
    let schema = schema_builder.build();

    // Create in-memory index and index all documents
    let index = Index::create_in_ram(schema.clone());
    let mut index_writer: IndexWriter = index.writer(50_000_000)?;

    // Get field handles by name for the doc! macro
    let id_f = schema.get_field("id").unwrap();
    let pop_f = schema.get_field("popularity").unwrap();
    let epoch_f = schema.get_field("published_epoch").unwrap();

    for d in &corpus {
        index_writer.add_document(doc!(
            id_f => d.id,
            title_field => d.title.as_str(),
            body_field => d.body.as_str(),
            pop_f => d.popularity,
            epoch_f => d.published_epoch,
        ))?;
    }
    index_writer.commit()?;

    // Create searcher and query parser
    let reader = index.reader()?;
    let searcher = reader.searcher();
    let query_parser = QueryParser::for_index(&index, vec![title_field, body_field]);

    let queries = vec![
        "machine learning",
        "cloud computing infrastructure",
        "security vulnerability",
        "database optimization",
        "open source",
    ];

    let mut all_results: HashMap<String, Vec<ResultDoc>> = HashMap::new();

    for query_str in &queries {
        let query = query_parser.parse_query(query_str)?;

        // Retrieve all matches by BM25 score (limit > corpus size)
        let top_docs: Vec<(Score, DocAddress)> =
            searcher.search(&query, &TopDocs::with_limit(100))?;

        let mut results: Vec<ResultDoc> = Vec::new();

        for (bm25_score, doc_address) in top_docs {
            // Retrieve stored doc and parse via JSON (robust across tantivy versions)
            let retrieved_doc: TantivyDocument = searcher.doc(doc_address)?;
            let doc_json_str = retrieved_doc.to_json(&schema);
            let doc_json: serde_json::Value = serde_json::from_str(&doc_json_str)?;

            // tantivy stores field values as arrays (multi-valued support)
            let doc_id = doc_json["id"][0].as_u64().unwrap_or(0);
            let doc_title = doc_json["title"][0]
                .as_str()
                .unwrap_or("")
                .to_string();
            let doc_popularity = doc_json["popularity"][0].as_u64().unwrap_or(0);
            let doc_epoch = doc_json["published_epoch"][0].as_u64().unwrap_or(0);

            let compound =
                compute_compound_score(bm25_score as f64, doc_popularity, doc_epoch);

            results.push(ResultDoc {
                id: doc_id,
                title: doc_title,
                bm25_score: bm25_score as f64,
                compound_score: compound,
                popularity: doc_popularity,
                published_epoch: doc_epoch,
            });
        }

        // Sort by compound score descending
        results.sort_by(|a, b| {
            b.compound_score
                .partial_cmp(&a.compound_score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        // Keep top 5
        results.truncate(5);

        all_results.insert(query_str.to_string(), results);
    }

    // Write output
    let output = serde_json::json!({"results": all_results});
    let output_str = serde_json::to_string_pretty(&output)?;
    std::fs::write("/app/output.json", output_str)?;

    eprintln!("Successfully wrote results to /app/output.json");
    Ok(())
}
