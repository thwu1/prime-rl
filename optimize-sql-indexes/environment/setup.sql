-- Sales analytics database setup
-- Schema, data generation, and initial (suboptimal) indexes

CREATE TABLE subsidiaries (
    subsidiary_id INT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    city VARCHAR(100),
    country VARCHAR(50)
);

CREATE TABLE employees (
    employee_id INT NOT NULL,
    subsidiary_id INT NOT NULL,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    date_of_birth DATE,
    phone_number VARCHAR(20),
    CONSTRAINT employees_pk PRIMARY KEY (employee_id, subsidiary_id),
    CONSTRAINT employees_sub_fk FOREIGN KEY (subsidiary_id) REFERENCES subsidiaries(subsidiary_id)
);

CREATE TABLE sales (
    sale_id INT PRIMARY KEY,
    employee_id INT NOT NULL,
    subsidiary_id INT NOT NULL,
    sale_date TIMESTAMP NOT NULL,
    eur_value NUMERIC(10,2) NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL DEFAULT 1,
    channel VARCHAR(20) DEFAULT 'online',
    CONSTRAINT sales_emp_fk FOREIGN KEY (employee_id, subsidiary_id)
        REFERENCES employees(employee_id, subsidiary_id)
);

CREATE TABLE messages (
    message_id INT PRIMARY KEY,
    receiver VARCHAR(100) NOT NULL,
    sender VARCHAR(100) NOT NULL,
    subject VARCHAR(200),
    message_text TEXT,
    processed CHAR(1) NOT NULL DEFAULT 'N',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    priority INT DEFAULT 0
);

-- ============================================================
-- Data generation
-- ============================================================

-- 30 subsidiaries
INSERT INTO subsidiaries (subsidiary_id, name, city, country)
SELECT s,
       'Subsidiary ' || s,
       (ARRAY['New York','London','Tokyo','Berlin','Paris',
              'Sydney','Toronto','Mumbai','Shanghai','Sao Paulo'])[1 + (s % 10)],
       (ARRAY['US','UK','JP','DE','FR','AU','CA','IN','CN','BR'])[1 + (s % 10)]
FROM generate_series(1, 30) s;

-- 9990 employees (333 per subsidiary)
INSERT INTO employees (employee_id, subsidiary_id, first_name, last_name, date_of_birth, phone_number)
SELECT
    e AS employee_id,
    s AS subsidiary_id,
    (ARRAY['James','Mary','John','Patricia','Robert','Jennifer','Michael','Linda',
           'David','Elizabeth','William','Barbara','Richard','Susan','Joseph',
           'Jessica','Thomas','Sarah','Charles','Karen','Daniel','Nancy',
           'Matthew','Betty','Anthony','Margaret','Mark','Sandra','Donald','Ashley',
           'Steven','Dorothy','Paul','Kimberly','Andrew','Emily','Joshua','Donna',
           'Kenneth','Michelle'])[1 + ((e * 7 + s * 3) % 40)] AS first_name,
    (ARRAY['Smith','Johnson','Williams','Brown','Jones','Garcia','Miller','Davis',
           'Rodriguez','Martinez','Hernandez','Lopez','Gonzalez','Wilson','Anderson',
           'Thomas','Taylor','Moore','Jackson','Martin','Lee','Perez','Thompson',
           'White','Harris','Sanchez','Clark','Ramirez','Lewis','Robinson',
           'Walker','Young','Allen','King','Wright','Scott','Torres','Nguyen',
           'Hill','Flores','Green','Adams','Nelson','Baker','Hall','Rivera',
           'Campbell','Mitchell','Carter','Roberts'])[1 + ((e * 13 + s * 17) % 50)] AS last_name,
    DATE '1960-01-01' + ((e * 23 + s * 7) % 14600) AS date_of_birth,
    '+1-555-' || LPAD(((e * 31 + s * 11) % 10000)::TEXT, 4, '0') AS phone_number
FROM generate_series(1, 30) s, generate_series(1, 333) e;

-- 500,000 sales spanning ~2 years (2023-01-01 to ~2024-12-28)
INSERT INTO sales (sale_id, employee_id, subsidiary_id, sale_date, eur_value, product_id, quantity, channel)
SELECT
    g AS sale_id,
    1 + (g % 333) AS employee_id,
    1 + (g % 30) AS subsidiary_id,
    TIMESTAMP '2023-01-01' + (g * INTERVAL '126 seconds') AS sale_date,
    ROUND((10 + (g * 73 % 991))::NUMERIC, 2) AS eur_value,
    1 + (g % 100) AS product_id,
    1 + (g % 5) AS quantity,
    (ARRAY['online','store','phone'])[1 + (g % 3)] AS channel
FROM generate_series(1, 500000) g;

-- 200,000 messages (~2% unprocessed, pseudo-random distribution)
SELECT setseed(0.42);

INSERT INTO messages (message_id, receiver, sender, subject, message_text, processed, created_at, priority)
SELECT
    g AS message_id,
    'user_' || (1 + (g % 1000)) AS receiver,
    'sender_' || (1 + ((g * 7) % 500)) AS sender,
    'Subject line ' || g AS subject,
    'Message body for message ' || g AS message_text,
    CASE WHEN random() < 0.02 THEN 'N' ELSE 'Y' END AS processed,
    TIMESTAMP '2024-01-01' + (g * INTERVAL '5 seconds') AS created_at,
    (g % 5) AS priority
FROM generate_series(1, 200000) g;

-- Guarantee unprocessed messages exist for user_42 (test data)
INSERT INTO messages (message_id, receiver, sender, subject, message_text, processed, created_at, priority)
SELECT
    200000 + g,
    'user_42',
    'sender_test_' || g,
    'Urgent: action required ' || g,
    'Please review and process this message. Reference: ' || g,
    'N',
    TIMESTAMP '2025-01-01' + (g * INTERVAL '1 hour'),
    g % 5
FROM generate_series(1, 20) g;

-- ============================================================
-- Suboptimal initial indexes (these are part of the problem)
-- ============================================================
CREATE INDEX idx_sales_date ON sales(sale_date);
CREATE INDEX idx_messages_processed ON messages(processed);
CREATE INDEX idx_sales_value ON sales(eur_value);

-- Update statistics
VACUUM ANALYZE subsidiaries;
VACUUM ANALYZE employees;
VACUUM ANALYZE sales;
VACUUM ANALYZE messages;
