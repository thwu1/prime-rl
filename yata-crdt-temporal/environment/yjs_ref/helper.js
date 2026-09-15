//
// Yjs reference helper — explore Yjs behavior to inform your implementation.
// Usage: node /app/yjs_ref/helper.js <command>

const Y = require('/app/yjs_ref/node_modules/yjs');

function createDoc(clientId) {
    const doc = new Y.Doc();
    doc.clientID = clientId;
    return doc;
}

function getText(doc) {
    return doc.getText('content');
}

function sync(doc1, doc2) {
    const sv1 = Y.encodeStateVector(doc1);
    const sv2 = Y.encodeStateVector(doc2);
    const u1 = Y.encodeStateAsUpdate(doc1, sv2);
    const u2 = Y.encodeStateAsUpdate(doc2, sv1);
    Y.applyUpdate(doc1, u2);
    Y.applyUpdate(doc2, u1);
}

const cmd = process.argv[2];

if (cmd === 'concurrent-two') {
    // Two clients independently insert at position 0
    const doc1 = createDoc(1);
    const doc2 = createDoc(2);
    getText(doc1).insert(0, 'a');
    getText(doc2).insert(0, 'b');
    sync(doc1, doc2);
    console.log('doc1:', JSON.stringify(getText(doc1).toString()));
    console.log('doc2:', JSON.stringify(getText(doc2).toString()));
    console.log('converged:', getText(doc1).toString() === getText(doc2).toString());

} else if (cmd === 'concurrent-three') {
    // Three clients independently insert at position 0
    const doc1 = createDoc(1);
    const doc2 = createDoc(2);
    const doc3 = createDoc(3);
    getText(doc1).insert(0, 'a');
    getText(doc2).insert(0, 'b');
    getText(doc3).insert(0, 'c');
    sync(doc1, doc2);
    sync(doc1, doc3);
    sync(doc2, doc3);
    console.log('doc1:', JSON.stringify(getText(doc1).toString()));
    console.log('doc2:', JSON.stringify(getText(doc2).toString()));
    console.log('doc3:', JSON.stringify(getText(doc3).toString()));

} else if (cmd === 'concurrent-same-context') {
    // Two clients insert between the same pair of characters
    const doc1 = createDoc(1);
    const doc2 = createDoc(2);
    getText(doc1).insert(0, 'ac');
    sync(doc1, doc2);
    getText(doc1).insert(1, 'x');
    getText(doc2).insert(1, 'y');
    sync(doc1, doc2);
    console.log('doc1:', JSON.stringify(getText(doc1).toString()));
    console.log('doc2:', JSON.stringify(getText(doc2).toString()));

} else if (cmd === 'commutativity') {
    // Show that merge order does not matter
    const docs = [createDoc(1), createDoc(2), createDoc(3)];
    docs.forEach((d, i) => getText(d).insert(0, String.fromCharCode(97 + i)));

    const updates = docs.map(d => Y.encodeStateAsUpdate(d));

    // Order 1: 0,1,2
    const t1 = createDoc(10);
    updates.forEach(u => Y.applyUpdate(t1, u));

    // Order 2: 2,0,1
    const t2 = createDoc(11);
    [updates[2], updates[0], updates[1]].forEach(u => Y.applyUpdate(t2, u));

    // Order 3: 1,2,0
    const t3 = createDoc(12);
    [updates[1], updates[2], updates[0]].forEach(u => Y.applyUpdate(t3, u));

    console.log('order 0,1,2:', JSON.stringify(getText(t1).toString()));
    console.log('order 2,0,1:', JSON.stringify(getText(t2).toString()));
    console.log('order 1,2,0:', JSON.stringify(getText(t3).toString()));
    console.log('all equal:', getText(t1).toString() === getText(t2).toString()
        && getText(t2).toString() === getText(t3).toString());

} else if (cmd === 'idempotent') {
    // Show that applying the same update twice is a no-op
    const doc1 = createDoc(1);
    const doc2 = createDoc(2);
    getText(doc1).insert(0, 'hello');
    const update = Y.encodeStateAsUpdate(doc1);
    Y.applyUpdate(doc2, update);
    const after1 = getText(doc2).toString();
    Y.applyUpdate(doc2, update);
    const after2 = getText(doc2).toString();
    console.log('after first apply:', JSON.stringify(after1));
    console.log('after second apply:', JSON.stringify(after2));
    console.log('idempotent:', after1 === after2);

} else if (cmd === 'snapshot') {
    // Snapshot and restore
    const doc = createDoc(1);
    getText(doc).insert(0, 'hello');
    const snap = Y.snapshot(doc);
    getText(doc).insert(5, ' world');
    console.log('current:', JSON.stringify(getText(doc).toString()));
    const restored = getText(doc).toDelta(snap);
    const text = restored.map(op => op.insert || '').join('');
    console.log('at snapshot:', JSON.stringify(text));

} else if (cmd === 'custom') {
    // Custom scenario: pass JSON array of {client, ops: [{type, index, text/length}]}
    // All clients start from empty docs, perform ops independently, then full sync.
    const scenario = JSON.parse(process.argv[3]);
    const docs = {};
    for (const entry of scenario) {
        const doc = createDoc(entry.client);
        docs[entry.client] = doc;
        for (const op of entry.ops) {
            if (op.type === 'insert') {
                getText(doc).insert(op.index, op.text);
            } else if (op.type === 'delete') {
                getText(doc).delete(op.index, op.length);
            }
        }
    }
    // Sync all pairs
    const keys = Object.keys(docs).map(Number).sort((a, b) => a - b);
    for (let i = 0; i < keys.length; i++) {
        for (let j = i + 1; j < keys.length; j++) {
            sync(docs[keys[i]], docs[keys[j]]);
        }
    }
    for (const k of keys) {
        console.log(`client ${k}: ${JSON.stringify(getText(docs[k]).toString())}`);
    }

} else if (cmd === 'phased') {
    // Phased scenario: JSON array of phases allowing interleaved edits and syncs.
    // Phase types:
    //   {"edit": <clientID>, "ops": [{type: "insert"/"delete", index, text/length}]}
    //   {"sync": [<clientID>, <clientID>, ...]}
    //
    // Example:
    //   [{"edit":1,"ops":[{"type":"insert","index":0,"text":"abc"}]},
    //    {"sync":[1,2]},
    //    {"edit":1,"ops":[{"type":"insert","index":1,"text":"X"}]},
    //    {"edit":2,"ops":[{"type":"insert","index":1,"text":"Y"}]},
    //    {"sync":[1,2]}]
    const phases = JSON.parse(process.argv[3]);
    const docs = {};
    for (const phase of phases) {
        if ('edit' in phase) {
            const cid = phase.edit;
            if (!(cid in docs)) {
                docs[cid] = createDoc(cid);
            }
            for (const op of phase.ops) {
                if (op.type === 'insert') {
                    getText(docs[cid]).insert(op.index, op.text);
                } else if (op.type === 'delete') {
                    getText(docs[cid]).delete(op.index, op.length);
                }
            }
        } else if ('sync' in phase) {
            const clients = phase.sync;
            for (let i = 0; i < clients.length; i++) {
                for (let j = i + 1; j < clients.length; j++) {
                    if (clients[i] in docs && clients[j] in docs) {
                        sync(docs[clients[i]], docs[clients[j]]);
                    }
                }
            }
        }
    }
    const keys = Object.keys(docs).map(Number).sort((a, b) => a - b);
    for (const k of keys) {
        console.log(`client ${k}: ${JSON.stringify(getText(docs[k]).toString())}`);
    }

} else {
    console.log('Yjs Reference Helper');
    console.log('====================');
    console.log('');
    console.log('Usage: node /app/yjs_ref/helper.js <command>');
    console.log('');
    console.log('Commands:');
    console.log('  concurrent-two          Two clients insert at position 0');
    console.log('  concurrent-three        Three clients insert at position 0');
    console.log('  concurrent-same-context Two clients insert between same characters');
    console.log('  commutativity           Prove update order does not matter');
    console.log('  idempotent              Prove re-applying updates is a no-op');
    console.log('  snapshot                Snapshot and restore demo');
    console.log('  custom <json>           Custom scenario (JSON array of client ops, then full sync)');
    console.log('  phased <json>           Phased scenario (interleaved edits and syncs)');
    console.log('');
    console.log('For ad-hoc exploration:');
    console.log("  node -e \"const Y = require('/app/yjs_ref/node_modules/yjs'); ...\"");
}
