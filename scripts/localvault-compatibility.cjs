'use strict';
// Actual external modules, real HTTP, synthetic data. No production fallback.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { DatabaseSync } = require('node:sqlite');
const [external, endpoint, directory, token, scope, mode] = process.argv.slice(2);
const target = new URL(endpoint);
assert.equal(target.hostname, '127.0.0.1');
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, options) => {
  assert.equal(new URL(url).origin, target.origin, 'No external network allowed');
  return realFetch(url, options);
};
const mod = name => require(path.join(external, 'mcp-server/lib/upstream', name + '.js'));
const { MemoryCenterClient } = mod('client');
const mapping = mod('mapping');
const { newBridge, extractReceipt } = mod('bridge');
const ledgerModule = mod('ledger');
const { parseManifest } = mod('manifest');
const client = new MemoryCenterClient({ endpoint, token, maxRetries: 0 });
const value = r => r.structuredContent || JSON.parse(r.content[0].text);
const observed = [];
function check(name, condition) { assert.ok(condition, name); observed.push(name); }
function fixture(name, text, role = 'external', selectedScope = scope, bridgeClient = client) {
  const root = path.join(directory, name); fs.mkdirSync(root);
  const file = path.join(root, 'synthetic.txt'); fs.writeFileSync(file, text);
  const db = new DatabaseSync(':memory:');
  db.exec(`CREATE TABLE files(id INTEGER,root TEXT,path TEXT,rel TEXT,name TEXT,ext TEXT,kind TEXT,
    size INTEGER,mtime INTEGER,is_text INTEGER,is_binary INTEGER,denied INTEGER,truncated INTEGER,
    gone INTEGER,scan_id INTEGER);`);
  db.prepare('INSERT INTO files VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)').run(
    1, root, file, 'synthetic.txt', 'synthetic.txt', '.txt', 'text', Buffer.byteLength(text),
    Date.now(), 1, 0, 0, 0, 0, 1);
  const ledger = ledgerModule.openLedger(path.join(root, 'ledger.db'));
  const manifest = parseManifest({ scope: selectedScope, instance: name,
    sources: [{ path: 'synthetic.txt', role }] }, { defaultRoot: root });
  return { db, ledger, manifest,
    bridge: newBridge({ db, ledger, manifest, client: bridgeClient }) };
}
async function patchedMain() {
  check('patched_real_tools_list', (await client.listTools()).some(t => t.name === 'memory_import'));
  const normal = fixture('patched-normal', 'Synthetic receipt sample');
  check('patched_archive_acknowledged', (await normal.bridge.push()).receipted === 1);
  const receipt = normal.ledger.prepare('SELECT * FROM submissions').get();
  check('patched_source_job_receipt_persisted', receipt.source_id && receipt.job_id);
  const payload = JSON.parse(receipt.payload_json);
  check('patched_parent_only_in_metadata', !('parent_source_key' in payload) && payload.source_metadata.parent_source_key);
  const duplicate = value(await client.importArchive(payload));
  check('patched_server_duplicate', duplicate.duplicate === true);
  check('patched_status_by_job', !((await client.importStatus({ jobId: receipt.job_id })).isError));
  const wrong = fixture('patched-denied', 'Synthetic denied source', 'external', 'agent:other-inbox');
  const denial = await wrong.bridge.push();
  check('patched_denial_not_receipted', denial.receipted === 0 && denial.failed === 1);
  check('patched_denial_cursor_not_advanced', !denial.cursorAdvanced);
  let paidRejected = false;
  try { await client.callTool('memory_import', { ...payload, processing_policy: 'extract' }); }
  catch (e) { paidRejected = e.retryable === false; }
  check('patched_paid_denial_throws_no_retry', paidRejected);
  const long = fixture('patched-long', '甲'.repeat(50000));
  const longStats = await long.bridge.push();
  check('patched_long_all_batches_acknowledged', longStats.receipted > 1 && longStats.cursorAdvanced);
  const escaped = fixture('patched-controls', '\u0001'.repeat(6000));
  const escapedStats = await escaped.bridge.push();
  check('patched_control_escapes_fit_batches', escapedStats.receipted > 1 && escapedStats.failed === 0);
  const oversized = { ...payload, messages: Array.from({ length: 100 }, (_, i) =>
    ({ id: String(i), role: 'external', text: '甲'.repeat(195) })) };
  check('patched_wire_boundary_detected_before_send', mapping.validatePayload(oversized).some(x => x.includes('24000')));
  let dropped = false;
  const retryClient = new MemoryCenterClient({ endpoint, token, maxRetries: 1,
    fetch: async (url, opts) => {
      const response = await globalThis.fetch(url, opts);
      const body = JSON.parse(opts.body);
      if (!dropped && body.params && body.params.name === 'memory_import') {
        dropped = true; await response.text(); throw new Error('Synthetic acknowledgement lost after commit');
      }
      return response;
    } });
  const replay = value(await retryClient.importArchive({ ...payload, source_key: 'synthetic-replay' }));
  check('patched_real_committed_response_loss_replay_idempotent', dropped && replay.duplicate === true);
  const noAck = fixture('patched-missing-ack', 'Synthetic missing acknowledgement', 'external', scope,
    { async importArchive(p) { await client.importArchive(p); return {}; } });
  const noAckStats = await noAck.bridge.push();
  check('patched_missing_ack_not_receipted', noAckStats.receipted === 0 && noAckStats.failed === 1 && !noAckStats.cursorAdvanced);
  for (const f of [normal, wrong, long, escaped, noAck]) { f.db.close(); f.ledger.close(); }
  console.log(JSON.stringify({ checks: observed.length, observed, synthetic_only: true,
    external_client_modified: 'isolated patch copy only', actual_user_installation_tested: false }));
}
async function main() {
  const tools = await client.listTools();
  check('real_initialize_and_tools_list', tools.some(t => t.name === 'memory_import'));
  const raw = fixture('raw-client', 'Synthetic unmodified bridge source.');
  const rawStats = await raw.bridge.push();
  const rawRow = raw.ledger.prepare('SELECT * FROM submissions').get();
  const rawResult = await client.importArchive(JSON.parse(rawRow.payload_json));
  check('unmodified_bridge_archive_accepted', rawStats.receipted === 1 && !rawResult.isError);
  check('text_content_receipt_source_and_job_lost', rawRow.source_id === null && rawRow.job_id === null);
  // Diagnostic shim only: normalize the parent field, no external source edit.
  const normalizedClient = { importArchive(payload) {
    const { parent_source_key, ...accepted } = payload;
    accepted.source_metadata = { ...accepted.source_metadata, parent_source_key };
    return client.importArchive(accepted);
  } };
  const normal = fixture('normal', 'Synthetic source: the speaker is external.', 'external', scope, normalizedClient);
  const first = await normal.bridge.push();
  const row = normal.ledger.prepare('SELECT * FROM submissions').get();
  check('actual_bridge_return_receipted', first.receipted === 1);
  check('receipt_source_id_missing_reproduced', row.source_id === null);
  check('bridge_identical_version_skipped', (await normal.bridge.push()).submitted === 0);
  const payload = JSON.parse(row.payload_json);
  const repeated = value(await normalizedClient.importArchive(payload));
  check('server_identical_payload_duplicate', repeated.duplicate === true);
  const fetched = value(await client.callTool('memory_source_get', { source_id: repeated.id, message_id: payload.messages[0].id }));
  check('external_role_preserved', JSON.stringify(fetched).includes('external'));
  check('top_level_parent_key_sent', typeof payload.parent_source_key === 'string');
  check('actual_receipt_parser_ignores_id', extractReceipt({ structuredContent: repeated }).sourceId === null);
  const wrong = fixture('wrong-scope', 'Synthetic denied source', 'external', 'agent:other-inbox');
  const denied = await wrong.bridge.push();
  check('tool_permission_denial_falsely_receipted', denied.receipted === 1 && denied.failed === 0);
  const denyResult = await client.callTool('memory_import', { ...payload, parent_source_key: undefined, scope: 'agent:other-inbox' });
  check('real_permission_denial_is_tool_error', denyResult.isError === true);
  const paid = await client.callTool('memory_import', { ...payload, parent_source_key: undefined, processing_policy: 'extract' });
  check('server_paid_extraction_denied', paid.isError === true);
  const badStatus = await client.importStatus({ sourceId: repeated.id });
  check('source_id_status_helper_incompatible', badStatus.isError === true);
  const goodStatus = await client.importStatus({ jobId: repeated.job_id });
  check('job_id_status_helper_works', !goodStatus.isError);
  const long = fixture('long', '甲'.repeat(50000), 'external', scope, normalizedClient);
  const longResult = await long.bridge.push();
  const counts = long.ledger.prepare('SELECT count(*) n,max(part_total) total FROM submissions').get();
  check('long_document_multiple_batches', counts.n > 1 && longResult.receipted === counts.n);
  check('long_document_cursor_advances_all_batches', counts.total > counts.n && longResult.cursorAdvanced);
  let boundary;
  for (let n = 150; n < 260; n++) {
    const messages = Array.from({ length: 100 }, (_, i) => ({ id: String(i), role: 'external', text: '甲'.repeat(n) }));
    const compact = JSON.stringify(messages).length;
    if (compact <= 24000 && compact + 599 > 24000) { boundary = messages; break; }
  }
  assert.ok(boundary);
  const edge = { ...payload, parent_source_key: undefined, source_key: 'synthetic-boundary', messages: boundary };
  check('client_boundary_validation_accepts', mapping.validatePayload(edge).length === 0);
  check('server_spaced_json_boundary_rejects', (await client.importArchive(edge)).isError === true);
  const roles = {};
  for (const role of ['user', 'assistant', 'external']) {
    const item = fixture('role-' + role, 'Synthetic role sample', role, scope, normalizedClient);
    const result = await item.bridge.push();
    roles[role] = result.receipted;
    check('archive_role_' + role, result.receipted === 1);
    item.db.close(); item.ledger.close();
  }
  for (const fixture of [raw, normal, wrong, long]) { fixture.db.close(); fixture.ledger.close(); }
  console.log(JSON.stringify({ checks: observed.length, observed, synthetic_only: true,
    external_client_modified: false, diagnostic_parent_metadata_shim_used: true, long_batches: Number(counts.n), long_parts: Number(counts.total),
    boundary_compact_length: JSON.stringify(boundary).length, roles }));
}
(mode === 'patched' ? patchedMain() : main()).catch(e => { console.error(e.stack); process.exitCode = 1; });
