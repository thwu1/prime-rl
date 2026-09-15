#!/usr/bin/env python3
"""Generate deterministic seed data for a normalized email archive database."""
import sqlite3
import random
import hashlib
from datetime import datetime, timedelta

random.seed(42)

conn = sqlite3.connect('/app/archive.db')
c = conn.cursor()

c.executescript("""
CREATE TABLE sources (
    id INTEGER PRIMARY KEY,
    source_type TEXT NOT NULL,
    identifier TEXT NOT NULL UNIQUE,
    display_name TEXT
);

CREATE TABLE participants (
    id INTEGER PRIMARY KEY,
    email_address TEXT UNIQUE NOT NULL,
    display_name TEXT,
    domain TEXT NOT NULL
);

CREATE TABLE conversations (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    message_count INTEGER DEFAULT 0,
    last_message_at TEXT
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    source_id INTEGER NOT NULL REFERENCES sources(id),
    sender_id INTEGER NOT NULL REFERENCES participants(id),
    sent_at TEXT NOT NULL,
    subject TEXT,
    snippet TEXT,
    size_estimate INTEGER,
    has_attachments INTEGER DEFAULT 0
);

CREATE TABLE message_recipients (
    id INTEGER PRIMARY KEY,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    participant_id INTEGER NOT NULL REFERENCES participants(id),
    recipient_type TEXT NOT NULL CHECK(recipient_type IN ('from','to','cc','bcc'))
);

CREATE TABLE labels (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    name TEXT NOT NULL,
    label_type TEXT NOT NULL CHECK(label_type IN ('system','user'))
);

CREATE TABLE message_labels (
    message_id INTEGER NOT NULL REFERENCES messages(id),
    label_id INTEGER NOT NULL REFERENCES labels(id),
    PRIMARY KEY (message_id, label_id)
);

CREATE TABLE attachments (
    id INTEGER PRIMARY KEY,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    filename TEXT,
    mime_type TEXT,
    size INTEGER,
    content_hash TEXT
);

CREATE INDEX idx_messages_conversation ON messages(conversation_id);
CREATE INDEX idx_messages_sender ON messages(sender_id);
CREATE INDEX idx_messages_sent_at ON messages(sent_at);
CREATE INDEX idx_recip_message ON message_recipients(message_id);
CREATE INDEX idx_recip_participant ON message_recipients(participant_id);
CREATE INDEX idx_mlabel_message ON message_labels(message_id);
CREATE INDEX idx_mlabel_label ON message_labels(label_id);
CREATE INDEX idx_attach_message ON attachments(message_id);

CREATE VIEW email_communication_graph AS
SELECT
    p_s.email_address AS sender,
    p_r.email_address AS recipient,
    COUNT(*) AS message_count
FROM messages m
JOIN participants p_s ON m.sender_id = p_s.id
JOIN message_recipients mr ON m.id = mr.message_id
JOIN participants p_r ON mr.participant_id = p_r.id
GROUP BY p_s.email_address, p_r.email_address;
""")

# --- Sources ---
sources = [
    (1, 'gmail', 'alice@techcorp.com', 'Alice Chen'),
    (2, 'gmail', 'bob@researchlab.org', 'Bob Martinez'),
    (3, 'imap', 'carol@startup.io', 'Carol Nakamura'),
]
c.executemany("INSERT INTO sources VALUES (?,?,?,?)", sources)

# --- Participants ---
DOMAINS = [
    'techcorp.com', 'researchlab.org', 'startup.io', 'bigbank.com',
    'university.edu', 'consulting.net', 'healthcare.org', 'media.co',
    'govagency.gov', 'nonprofit.org', 'dataeng.io', 'cloudops.com',
    'analytics.ai', 'security.net', 'devtools.dev'
]

NAMES = [
    'alice', 'bob', 'carol', 'david', 'eve', 'frank', 'grace', 'hank',
    'iris', 'jack', 'karen', 'leo', 'maria', 'nate', 'olivia', 'pat',
    'quinn', 'rosa', 'sam', 'tina', 'uma', 'vic', 'wendy', 'xander',
    'yuki', 'zara', 'alex', 'blake', 'casey', 'dana', 'ellis', 'faye',
    'glen', 'holly', 'ivan', 'jules', 'kim', 'liam', 'mona', 'neil',
    'orla', 'pete', 'rain', 'sage', 'troy', 'val', 'walt', 'xena',
    'yves', 'zeke'
]

for i, name in enumerate(NAMES):
    domain = DOMAINS[i % len(DOMAINS)]
    c.execute("INSERT INTO participants VALUES (?,?,?,?)",
              (i + 1, f"{name}@{domain}", name.capitalize(), domain))

# --- Labels ---
labels_data = [
    (1, 1, 'INBOX', 'system'), (2, 1, 'SENT', 'system'),
    (3, 1, 'DRAFT', 'system'), (4, 1, 'SPAM', 'system'),
    (5, 1, 'TRASH', 'system'), (6, 1, 'IMPORTANT', 'system'),
    (7, 1, 'STARRED', 'system'),
    (8, 1, 'Project-Alpha', 'user'), (9, 1, 'Project-Beta', 'user'),
    (10, 1, 'Urgent', 'user'), (11, 1, 'Follow-Up', 'user'),
    (12, 1, 'Newsletter', 'user'), (13, 1, 'Receipts', 'user'),
    (14, 2, 'INBOX', 'system'), (15, 2, 'SENT', 'system'),
    (16, 2, 'Research', 'user'), (17, 2, 'Collaboration', 'user'),
    (18, 2, 'Grants', 'user'),
    (19, 3, 'INBOX', 'system'), (20, 3, 'SENT', 'system'),
    (21, 3, 'Engineering', 'user'), (22, 3, 'Product', 'user'),
    (23, 3, 'Hiring', 'user'),
]
c.executemany("INSERT INTO labels VALUES (?,?,?,?)", labels_data)

# Pre-compute label lookups
source_inbox = {}
source_sent = {}
source_extra_labels = {}

for lid, sid, name, ltype in labels_data:
    if name == 'INBOX':
        source_inbox[sid] = lid
    elif name == 'SENT':
        source_sent[sid] = lid

for sid in [1, 2, 3]:
    source_extra_labels[sid] = [
        lid for lid, s, n, lt in labels_data
        if s == sid and n not in ('INBOX', 'SENT')
    ]

SOURCE_OWNERS = {1: 1, 2: 2, 3: 3}

ATTACHMENT_TYPES = [
    ('report.pdf', 'application/pdf'),
    ('spreadsheet.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
    ('presentation.pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'),
    ('document.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    ('screenshot.png', 'image/png'),
    ('photo.jpg', 'image/jpeg'),
    ('data.csv', 'text/csv'),
    ('config.json', 'application/json'),
    ('diagram.svg', 'image/svg+xml'),
    ('archive.zip', 'application/zip'),
]

TOPICS = [
    'Data Pipeline Migration', 'API Redesign', 'Security Audit',
    'Performance Optimization', 'Hiring Plan', 'Budget Allocation',
    'Product Roadmap', 'Customer Feedback', 'Infrastructure Upgrade',
    'Compliance Review', 'Team Offsite', 'Training Program',
    'Vendor Evaluation', 'Release Planning', 'Architecture Review',
    'Incident Postmortem', 'Cost Reduction', 'Feature Request',
    'Bug Triage', 'Documentation Update',
]

# Power-law activity weights
activity_weights = [1.0 / (i + 1) ** 0.7 for i in range(len(NAMES))]

start_date = datetime(2020, 1, 1)
end_date = datetime(2024, 12, 31)
total_seconds = int((end_date - start_date).total_seconds())

msg_id = 0
recip_id = 0
attach_id = 0
NUM_CONVERSATIONS = 2000

for conv_id in range(1, NUM_CONVERSATIONS + 1):
    source_id = random.choices([1, 2, 3], weights=[0.5, 0.3, 0.2])[0]
    owner_pid = SOURCE_OWNERS[source_id]

    c.execute("INSERT INTO conversations VALUES (?,?,0,NULL)", (conv_id, source_id))

    # Geometric thread depth, capped at 12
    depth = 1
    while random.random() < 0.5 and depth < 12:
        depth += 1

    conv_start = start_date + timedelta(seconds=random.randint(0, total_seconds))

    # Pick thread participants (owner + 1-4 others)
    num_others = random.randint(1, 4)
    other_pids = []
    for _ in range(num_others):
        pid = random.choices(range(1, len(NAMES) + 1), weights=activity_weights)[0]
        if pid != owner_pid and pid not in other_pids:
            other_pids.append(pid)
    if not other_pids:
        cands = [p for p in range(1, len(NAMES) + 1) if p != owner_pid]
        other_pids = [random.choice(cands)]
    thread_pids = [owner_pid] + other_pids

    topic = random.choice(TOPICS)
    subject = f"{topic} - {conv_start.strftime('%b %Y')}"
    prev_sent = conv_start

    for msg_pos in range(depth):
        msg_id += 1
        sender_pid = thread_pids[msg_pos % len(thread_pids)]

        if msg_pos > 0:
            r = random.random()
            if r < 0.25:
                gap = random.randint(1, 30)
            elif r < 0.55:
                gap = random.randint(31, 240)
            elif r < 0.80:
                gap = random.randint(241, 1440)
            else:
                gap = random.randint(1441, 4320)
            sent_at = prev_sent + timedelta(minutes=gap)
        else:
            sent_at = conv_start

        # Business-hours bias
        if random.random() < 0.65:
            sent_at = sent_at.replace(hour=random.randint(8, 17))

        prev_sent = sent_at
        sent_str = sent_at.strftime('%Y-%m-%d %H:%M:%S')
        has_attach = 1 if random.random() < 0.18 else 0
        size_est = random.randint(800, 45000)
        msg_subj = subject if msg_pos == 0 else f"Re: {subject}"

        c.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?)",
                  (msg_id, conv_id, source_id, sender_pid, sent_str,
                   msg_subj, f"Message about {topic}", size_est, has_attach))

        # --- Recipients ---
        recip_id += 1
        c.execute("INSERT INTO message_recipients VALUES (?,?,?,?)",
                  (recip_id, msg_id, sender_pid, 'from'))

        to_cands = [p for p in thread_pids if p != sender_pid]
        if not to_cands:
            to_cands = [random.choice(
                [p for p in range(1, len(NAMES) + 1) if p != sender_pid])]
        num_to = min(len(to_cands),
                     random.choices([1, 2, 3], weights=[0.6, 0.3, 0.1])[0])
        to_selected = random.sample(to_cands, num_to)
        for tp in to_selected:
            recip_id += 1
            c.execute("INSERT INTO message_recipients VALUES (?,?,?,?)",
                      (recip_id, msg_id, tp, 'to'))

        # Optional CC (20%)
        if random.random() < 0.2:
            cc_pool = [p for p in range(1, len(NAMES) + 1)
                       if p != sender_pid and p not in to_selected]
            if cc_pool:
                num_cc = min(len(cc_pool), random.randint(1, 2))
                for cp in random.sample(cc_pool, num_cc):
                    recip_id += 1
                    c.execute("INSERT INTO message_recipients VALUES (?,?,?,?)",
                              (recip_id, msg_id, cp, 'cc'))

        # --- Labels ---
        msg_labels = set()
        if sender_pid == owner_pid:
            msg_labels.add(source_sent[source_id])
        else:
            msg_labels.add(source_inbox[source_id])

        extras = source_extra_labels[source_id]
        if random.random() < 0.4 and extras:
            num_extra = min(len(extras), random.randint(1, 3))
            for el in random.sample(extras, num_extra):
                msg_labels.add(el)

        for lid in msg_labels:
            c.execute("INSERT OR IGNORE INTO message_labels VALUES (?,?)",
                      (msg_id, lid))

        # --- Attachments ---
        if has_attach:
            num_att = random.randint(1, 3)
            for _ in range(num_att):
                attach_id += 1
                atype = random.choice(ATTACHMENT_TYPES)
                asize = random.randint(1000, 5000000)
                ahash = hashlib.sha256(
                    f"att_{attach_id}".encode()).hexdigest()
                c.execute("INSERT INTO attachments VALUES (?,?,?,?,?,?)",
                          (attach_id, msg_id, atype[0], atype[1], asize, ahash))

# Update conversation metadata
c.execute("""
    UPDATE conversations SET
        message_count = (SELECT COUNT(*) FROM messages m
                         WHERE m.conversation_id = conversations.id),
        last_message_at = (SELECT MAX(sent_at) FROM messages m
                           WHERE m.conversation_id = conversations.id)
""")

conn.commit()
conn.close()
