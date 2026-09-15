const Y = require('yjs');
const fs = require('fs');
const path = require('path');

const FIXTURES_DIR = '/app/fixtures';

function main() {
    const [cmd, ...args] = process.argv.slice(2);
    switch (cmd) {
        case 'generate-fixtures':
            return generateFixtures();
        case 'apply':
            return applyAndPrint(args[0], args.slice(1));
        case 'sv':
            return writeStateVector(args[0], args.slice(1));
        default:
            console.error('Unknown command: ' + cmd);
            process.exit(1);
    }
}

function applyAndPrint(textName, files) {
    const doc = new Y.Doc();
    for (const file of files) {
        const data = fs.readFileSync(file);
        Y.applyUpdate(doc, new Uint8Array(data));
    }
    const text = doc.getText(textName).toString();
    console.log(JSON.stringify({ text: text }));
}

function writeStateVector(outputFile, inputFiles) {
    const doc = new Y.Doc();
    for (const file of inputFiles) {
        const data = fs.readFileSync(file);
        Y.applyUpdate(doc, new Uint8Array(data));
    }
    const svBytes = Y.encodeStateVector(doc);
    fs.writeFileSync(outputFile, Buffer.from(svBytes));
}

function generateFixtures() {
    fs.mkdirSync(FIXTURES_DIR, { recursive: true });
    const manifest = {};

    // 1. Basic hello — single insert
    (function() {
        const doc = new Y.Doc();
        doc.clientID = 100;
        doc.getText('t').insert(0, 'hello');
        const update = Y.encodeStateAsUpdate(doc);
        fs.writeFileSync(path.join(FIXTURES_DIR, 'basic_hello.bin'), Buffer.from(update));
        manifest.basic_hello = {
            file: 'basic_hello.bin',
            expected_text: 'hello',
            expected_sv: { '100': 5 }
        };
    })();

    // 2. Hello world — sequential inserts (merged into compound item)
    (function() {
        const doc = new Y.Doc();
        doc.clientID = 100;
        doc.getText('t').insert(0, 'hello');
        doc.getText('t').insert(5, ' world');
        const update = Y.encodeStateAsUpdate(doc);
        fs.writeFileSync(path.join(FIXTURES_DIR, 'hello_world.bin'), Buffer.from(update));
        manifest.hello_world = {
            file: 'hello_world.bin',
            expected_text: 'hello world',
            expected_sv: { '100': 11 }
        };
    })();

    // 3. With deletes
    (function() {
        const doc = new Y.Doc();
        doc.clientID = 100;
        doc.getText('t').insert(0, 'hello world');
        doc.getText('t').delete(1, 3); // delete "ell"
        const update = Y.encodeStateAsUpdate(doc);
        fs.writeFileSync(path.join(FIXTURES_DIR, 'with_delete.bin'), Buffer.from(update));
        manifest.with_delete = {
            file: 'with_delete.bin',
            expected_text: 'ho world',
            expected_sv: { '100': 11 }
        };
    })();

    // 4. Insert in middle — tests origin references and item splitting
    (function() {
        const doc = new Y.Doc();
        doc.clientID = 100;
        doc.getText('t').insert(0, 'ac');
        doc.getText('t').insert(1, 'b'); // between 'a' and 'c'
        const update = Y.encodeStateAsUpdate(doc);
        fs.writeFileSync(path.join(FIXTURES_DIR, 'insert_middle.bin'), Buffer.from(update));
        manifest.insert_middle = {
            file: 'insert_middle.bin',
            expected_text: 'abc',
            expected_sv: { '100': 3 }
        };
    })();

    // 5. Multi-type document — multiple named text sequences
    (function() {
        const doc = new Y.Doc();
        doc.clientID = 100;
        doc.getText('title').insert(0, 'Hello');
        doc.getText('body').insert(0, 'World');
        const update = Y.encodeStateAsUpdate(doc);
        fs.writeFileSync(path.join(FIXTURES_DIR, 'multi_type.bin'), Buffer.from(update));
        manifest.multi_type = {
            file: 'multi_type.bin',
            expected_title: 'Hello',
            expected_body: 'World',
            expected_sv: { '100': 10 }
        };
    })();

    // 6. Two concurrent clients at same position
    (function() {
        const docA = new Y.Doc(); docA.clientID = 100;
        docA.getText('t').insert(0, 'abc');
        const updateA = Y.encodeStateAsUpdate(docA);
        fs.writeFileSync(path.join(FIXTURES_DIR, 'client_a.bin'), Buffer.from(updateA));

        const docB = new Y.Doc(); docB.clientID = 200;
        docB.getText('t').insert(0, 'xyz');
        const updateB = Y.encodeStateAsUpdate(docB);
        fs.writeFileSync(path.join(FIXTURES_DIR, 'client_b.bin'), Buffer.from(updateB));

        const merged = new Y.Doc();
        Y.applyUpdate(merged, updateA);
        Y.applyUpdate(merged, updateB);
        manifest.concurrent_two = {
            files: ['client_a.bin', 'client_b.bin'],
            expected_text: merged.getText('t').toString()
        };
    })();

    // 7. Three concurrent clients at same position
    (function() {
        const clients = [300, 301, 302];
        const chars = ['a', 'b', 'c'];
        const updates = [];
        for (let i = 0; i < 3; i++) {
            const d = new Y.Doc(); d.clientID = clients[i];
            d.getText('t').insert(0, chars[i]);
            const u = Y.encodeStateAsUpdate(d);
            fs.writeFileSync(path.join(FIXTURES_DIR, 'three_' + i + '.bin'), Buffer.from(u));
            updates.push(u);
        }
        const merged = new Y.Doc();
        for (const u of updates) Y.applyUpdate(merged, u);
        manifest.concurrent_three = {
            files: ['three_0.bin', 'three_1.bin', 'three_2.bin'],
            expected_text: merged.getText('t').toString()
        };
    })();

    // 8. Shared base with divergent edits
    (function() {
        const base = new Y.Doc(); base.clientID = 100;
        base.getText('t').insert(0, 'hello');
        const baseUpdate = Y.encodeStateAsUpdate(base);
        const baseSV = Y.encodeStateVector(base);
        fs.writeFileSync(path.join(FIXTURES_DIR, 'shared_base.bin'), Buffer.from(baseUpdate));

        const docA = new Y.Doc(); docA.clientID = 101;
        Y.applyUpdate(docA, baseUpdate);
        docA.getText('t').insert(5, ' world');
        const diffA = Y.encodeStateAsUpdate(docA, baseSV);
        fs.writeFileSync(path.join(FIXTURES_DIR, 'diverge_a.bin'), Buffer.from(diffA));

        const docB = new Y.Doc(); docB.clientID = 102;
        Y.applyUpdate(docB, baseUpdate);
        docB.getText('t').insert(0, 'say: ');
        const diffB = Y.encodeStateAsUpdate(docB, baseSV);
        fs.writeFileSync(path.join(FIXTURES_DIR, 'diverge_b.bin'), Buffer.from(diffB));

        const merged = new Y.Doc();
        Y.applyUpdate(merged, baseUpdate);
        Y.applyUpdate(merged, diffA);
        Y.applyUpdate(merged, diffB);
        manifest.divergent_sync = {
            base: 'shared_base.bin',
            diffs: ['diverge_a.bin', 'diverge_b.bin'],
            expected_text: merged.getText('t').toString()
        };
    })();

    // 9. Five concurrent clients at different positions
    (function() {
        const base = new Y.Doc(); base.clientID = 100;
        base.getText('t').insert(0, 'abcdef');
        const baseUpdate = Y.encodeStateAsUpdate(base);
        const baseSV = Y.encodeStateVector(base);
        fs.writeFileSync(path.join(FIXTURES_DIR, 'five_base.bin'), Buffer.from(baseUpdate));

        const positions = [1, 2, 3, 4, 5];
        const chars = ['1', '2', '3', '4', '5'];
        const diffs = [];
        for (let i = 0; i < 5; i++) {
            const d = new Y.Doc(); d.clientID = 401 + i;
            Y.applyUpdate(d, baseUpdate);
            d.getText('t').insert(positions[i], chars[i]);
            const diffU = Y.encodeStateAsUpdate(d, baseSV);
            fs.writeFileSync(path.join(FIXTURES_DIR, 'five_' + i + '.bin'), Buffer.from(diffU));
            diffs.push('five_' + i + '.bin');
        }

        const merged = new Y.Doc();
        Y.applyUpdate(merged, baseUpdate);
        for (let i = 0; i < 5; i++) {
            const data = fs.readFileSync(path.join(FIXTURES_DIR, diffs[i]));
            Y.applyUpdate(merged, new Uint8Array(data));
        }
        manifest.five_concurrent = {
            base: 'five_base.bin',
            diffs: diffs,
            expected_text: merged.getText('t').toString()
        };
    })();

    // 10. Complex editing: insert, delete, re-insert
    (function() {
        const doc = new Y.Doc(); doc.clientID = 100;
        doc.getText('t').insert(0, 'abcdefgh');
        doc.getText('t').delete(2, 3); // delete "cde" -> "abfgh"
        doc.getText('t').insert(2, 'XY'); // -> "abXYfgh"
        const update = Y.encodeStateAsUpdate(doc);
        fs.writeFileSync(path.join(FIXTURES_DIR, 'complex_edit.bin'), Buffer.from(update));
        manifest.complex_edit = {
            file: 'complex_edit.bin',
            expected_text: 'abXYfgh',
            expected_sv: { '100': 10 }
        };
    })();

    // 11. Concurrent delete and insert
    (function() {
        const base = new Y.Doc(); base.clientID = 100;
        base.getText('t').insert(0, 'abcde');
        const baseUpdate = Y.encodeStateAsUpdate(base);
        const baseSV = Y.encodeStateVector(base);
        fs.writeFileSync(path.join(FIXTURES_DIR, 'del_ins_base.bin'), Buffer.from(baseUpdate));

        const d1 = new Y.Doc(); d1.clientID = 101;
        Y.applyUpdate(d1, baseUpdate);
        d1.getText('t').delete(1, 3); // delete "bcd"

        const d2 = new Y.Doc(); d2.clientID = 102;
        Y.applyUpdate(d2, baseUpdate);
        d2.getText('t').insert(2, 'x'); // insert after 'b'

        const diff1 = Y.encodeStateAsUpdate(d1, baseSV);
        const diff2 = Y.encodeStateAsUpdate(d2, baseSV);
        fs.writeFileSync(path.join(FIXTURES_DIR, 'del_ins_1.bin'), Buffer.from(diff1));
        fs.writeFileSync(path.join(FIXTURES_DIR, 'del_ins_2.bin'), Buffer.from(diff2));

        const merged = new Y.Doc();
        Y.applyUpdate(merged, baseUpdate);
        Y.applyUpdate(merged, diff1);
        Y.applyUpdate(merged, diff2);
        manifest.concurrent_del_ins = {
            base: 'del_ins_base.bin',
            diffs: ['del_ins_1.bin', 'del_ins_2.bin'],
            expected_text: merged.getText('t').toString()
        };
    })();

    fs.writeFileSync(path.join(FIXTURES_DIR, 'manifest.json'), JSON.stringify(manifest, null, 2));
    console.log('Fixtures generated successfully');
}

main();
