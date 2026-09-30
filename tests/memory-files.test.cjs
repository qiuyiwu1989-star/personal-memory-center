const test = require('node:test');
const assert = require('node:assert/strict');
const {decode, split, MAX_TEXT_CHARS} = require('../assets/memory-files.js');

test('large UTF-8 files split without losing text or breaking emoji', () => {
  const text = '第一段\n'.repeat(5000) + '🙂'.repeat(3000) + '\n结尾';
  assert.equal(decode('notes.md', new TextEncoder().encode(text)), text);
  const parts = split(text);
  assert.ok(parts.length > 1);
  assert.equal(parts.join(''), text);
  assert.ok(parts.every(part => part.length <= 15000));
  assert.ok(parts.every(part => !/[\uD800-\uDBFF]$/.test(part)));
  assert.ok(parts.every(part => !/^[\uDC00-\uDFFF]/.test(part)));
});

test('JSON remains raw text and source limit is explicit', () => {
  const text = JSON.stringify({body:'内容'.repeat(12000)});
  assert.equal(split(decode('archive.json', new TextEncoder().encode(text))).join(''), text);
  assert.throws(() => decode('bad.json', new TextEncoder().encode('{')), /JSON 格式无效/);
  assert.throws(() => split('a'.repeat(MAX_TEXT_CHARS+1)), /200,000/);
  assert.throws(() => split('  '), /不能为空/);
});

test('escaped characters still fit a server source payload', () => {
  const text = ('\\\n\t'.repeat(12000)) + '🙂';
  const parts = split(text);
  assert.equal(parts.join(''), text);
  assert.ok(parts.every(part => JSON.stringify(part).length <= 18000));
  assert.ok(parts.every(part => !/[\uD800-\uDBFF]$/.test(part)));
});
