// Run against the shipped inline modules; no build step or test dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
const source = html.slice(html.indexOf('__modules["src/core/graph.js"]='), html.indexOf('__modules["src/audio.js"]='));
const modules = vm.runInNewContext('const __modules = {};\n' + source + '\n__modules');
const { generate, solve, validateGraph, repairSamples } = modules['src/core/graph.js'];
const { LEVELS, generatedLevel, dailyLevel } = modules['src/core/catalog.js'];
const { Session } = modules['src/core/session.js'];
const { sanitize } = modules['src/core/storage.js'];
const sceneSource = html.slice(html.indexOf('__modules["src/view/scene.js"]='), html.indexOf('__modules["src/app.js"]='));
const geometryView = vm.runInNewContext(sceneSource.replace('return {PALETTES,SceneView}', 'return {PALETTES,SceneView,skinFaces}'), { __modules: modules });
const { shape } = modules['src/core/graph.js'];
assert.equal(geometryView.skinFaces('ring', shape('ring',5).vertices).length, 0, 'a warped ring must not acquire a solid hull');
assert.equal(geometryView.skinFaces('star', shape('star',8).vertices).length, 16, 'star valleys retain their real facets');
const star = shape('star',6).vertices;
const turn = (star[1][0]-star[0][0])*(star[2][1]-star[1][1])-(star[1][1]-star[0][1])*(star[2][0]-star[1][0]);
assert.ok(turn < 0, 'the six-vertex star needs an actual concave valley');
const configs = [...LEVELS];
for (let difficulty = 1; difficulty <= 3; difficulty++)
    for (let i = 0; i < 100; i++) configs.push(generatedLevel(`regression-${i}`, difficulty));
configs.push(dailyLevel(new Date('2026-09-10T00:00:00Z')));
let moves = 0;
for (const config of configs) {
    const session = new Session(config), graph = session.graph, route = solve(graph, graph.start);
    assert.ok(validateGraph(graph).ok, config.seed);
    assert.equal(JSON.stringify(generate(config)), JSON.stringify(graph), 'deterministic graph');
    for (const edge of graph.edges.filter(e => e.kind === 'repair')) {
        const samples = repairSamples(graph.vertices[edge.a].p, graph.vertices[edge.b].p);
        assert.deepEqual(samples[0], graph.vertices[edge.a].p);
        assert.deepEqual(samples.at(-1), graph.vertices[edge.b].p);
        assert.ok(samples.every(p => p.every(Number.isFinite)));
    }
    for (const id of route) {
        assert.ok(session.available().some(e => e.id === id), `reachable layer: ${config.seed}, edge ${id}`);
        assert.ok(session.move(id, true).ok);
        moves++;
    }
    assert.ok(session.complete);
    assert.equal(session.current, graph.end);
    const completeHistory = JSON.stringify(session.history), unlocked = JSON.stringify([...session.unlocked]);
    const count = Math.min(8, route.length);
    for (let i = 0; i < count; i++) assert.ok(session.undo());
    assert.equal(session.redoStack.length, count);
    const restored = Session.restore(config, session.snapshot());
    assert.equal(JSON.stringify(restored.history), JSON.stringify(session.history));
    assert.equal(JSON.stringify([...restored.unlocked]), JSON.stringify([...session.unlocked]));
    assert.equal(restored.redoStack.length, 0, 'redo is local to this play session');
    for (let i = 0; i < count; i++) assert.ok(session.redo().ok);
    assert.equal(JSON.stringify(session.history), completeHistory);
    assert.equal(JSON.stringify([...session.unlocked]), unlocked);
    assert.ok(session.complete);
}
const branch = new Session(LEVELS[2]);
branch.move(solve(branch.graph, branch.current)[0]);
branch.undo();
assert.equal(branch.redoStack.length, 1);
assert.ok(branch.move(branch.available().find(e => e.id !== branch.redoStack[0]).id).ok);
assert.equal(branch.redoStack.length, 0, 'a new route clears redo');
assert.equal(branch.redo().ok, false);
const deadEnd = new Session(LEVELS[2]);
let unsafe;
function findUnsafe(s) {
    for (const e of s.available()) {
        const trial = Session.restore(s.config, s.snapshot());
        const result = trial.move(e.id);
        if (result.stranded) return { s, edge: e.id };
        if (!trial.complete) { const found = findUnsafe(trial); if (found) return found; }
    }
}
unsafe = findUnsafe(deadEnd);
assert.ok(unsafe);
const previous = JSON.stringify(unsafe.s.snapshot());
assert.equal(unsafe.s.move(unsafe.edge, true).reason, 'unsafe');
assert.equal(JSON.stringify(unsafe.s.snapshot()), previous);
const saved = sanitize({ version: 1, active: branch.snapshot(), records: {}, settings: {} });
assert.equal(JSON.stringify(saved.active.history), JSON.stringify(branch.history), 'v1 save remains readable');
console.log(`PASS: ${configs.length} puzzles, ${moves} legal moves, undo/redo, portals, guard, v1 saves, repair geometry`);
