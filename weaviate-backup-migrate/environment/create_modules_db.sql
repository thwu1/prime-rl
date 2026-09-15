CREATE TABLE modules (
    name TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK(type IN ('text', 'multimodal', 'image', 'generative', 'backup')),
    default_dimensions INTEGER,
    status TEXT NOT NULL CHECK(status IN ('active', 'deprecated', 'removed')),
    notes TEXT
);

CREATE TABLE compatibility_map (
    source_module TEXT NOT NULL,
    target_module TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    PRIMARY KEY (source_module, target_module),
    FOREIGN KEY (source_module) REFERENCES modules(name),
    FOREIGN KEY (target_module) REFERENCES modules(name)
);

INSERT INTO modules VALUES ('text2vec-contextionary', 'text', 300, 'deprecated', 'Legacy contextionary vectorizer, no longer maintained');
INSERT INTO modules VALUES ('text2vec-transformers', 'text', 384, 'active', NULL);
INSERT INTO modules VALUES ('text2vec-openai', 'text', 1536, 'active', 'Requires OpenAI API key');
INSERT INTO modules VALUES ('text2vec-ollama', 'text', 384, 'active', NULL);
INSERT INTO modules VALUES ('multi2vec-clip', 'multimodal', 512, 'active', 'CLIP-based multimodal vectorizer for text and images');
INSERT INTO modules VALUES ('img2vec-neural', 'image', 2048, 'active', NULL);
INSERT INTO modules VALUES ('generative-ollama', 'generative', NULL, 'active', 'Generative module, not a vectorizer');
INSERT INTO modules VALUES ('backup-filesystem', 'backup', NULL, 'active', 'Backup module, not a vectorizer');

INSERT INTO compatibility_map VALUES ('text2vec-contextionary', 'text2vec-transformers', 1, 'Direct replacement, different dimensions');
INSERT INTO compatibility_map VALUES ('text2vec-contextionary', 'text2vec-ollama', 2, 'Alternative replacement, same dimensions as transformers');
INSERT INTO compatibility_map VALUES ('text2vec-openai', 'text2vec-ollama', 1, 'Self-hosted replacement, different dimensions');
INSERT INTO compatibility_map VALUES ('multi2vec-clip', 'img2vec-neural', 1, 'Image-only replacement, different dimensions');
