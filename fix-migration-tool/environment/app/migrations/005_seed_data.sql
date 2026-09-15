-- migration: 005_seed_data
-- depends_on: 004_create_post_tags
-- description: Insert seed data for testing

INSERT INTO users (username, email) VALUES ('admin', 'admin@example.com');
INSERT INTO users (username, email) VALUES ('editor', 'editor@example.com');
INSERT INTO posts (user_id, title, body) VALUES (1, 'Welcome Post', 'Hello; welcome to the platform!');
INSERT INTO tags (name, created_by) VALUES ('announcements', 1);
INSERT INTO post_tags (post_id, tag_id) VALUES (1, 1);
