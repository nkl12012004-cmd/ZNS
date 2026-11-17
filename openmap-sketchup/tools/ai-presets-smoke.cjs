/* SPDX-License-Identifier: MIT — no provider, browser or DOM required. */
'use strict';
const assert = require('node:assert/strict');
const presets = require('../extension/openmap_sketchup/ui/ai-presets.js');

assert.equal(presets.version, 1);
for (const name of ['scene', 'style', 'context', 'lighting', 'extras', 'referenceRoles']) {
  assert(Object.isFrozen(presets[name]));
  assert.equal(new Set(presets[name].map(item => item.id)).size, presets[name].length);
  for (const item of presets[name]) {
    assert(Object.isFrozen(item));
    assert.match(item.id, /^[a-z_]+$/);
    assert.equal(typeof item.label, 'string');
    assert.equal(typeof item.prompt, 'string');
    assert(item.prompt.length <= 300);
  }
}
assert(Object.isFrozen(presets));
assert.throws(() => { presets.style[1].prompt = 'changed'; }, TypeError);
assert.throws(() => { presets.extras.push({id: 'unexpected'}); }, TypeError);

assert.equal(presets.compose(), '');
assert.equal(presets.compose([]), '');
assert.equal(presets.compose({scene: 'auto', style: 'original', context: 'original', lighting: 'original', extras: []}), '');
assert.equal(presets.compose({scene: 'custom', style: 'custom', context: 'custom', lighting: 'custom'}), '');
assert.equal(presets.compose({scene: '__proto__', style: 'constructor', context: '<script>', lighting: 2, extras: ['not_real']}), '');
assert.equal(presets.compose({scene: 'exterior'}), presets.compose({scene: 'architecture'}));
assert.equal(presets.compose({extras: ['people', 'people']}), presets.compose({extras: ['people']}));
assert(!presets.compose({scene: 'interior'}).includes('xe'));
assert(!presets.compose({scene: 'interior'}).includes('bổ sung một ít người'));

const chosen = {scene: 'aerial', style: 'photoreal', context: 'rural', lighting: 'golden', extras: ['plants'], references: [{index: 1, role: 'material', region: 2}]};
const snapshot = JSON.stringify(chosen);
const text = presets.compose(chosen);
assert.equal(JSON.stringify(chosen), snapshot);
assert(text.includes('góc nhìn trên cao'));
assert(text.includes('làng quê'));
assert(text.includes('Ảnh tham chiếu 1 — áp dụng cho vùng 2:'));
assert(text.includes('không lấy bố cục'));
assert(!/4K|8K|miễn phí|Nano Render|Google|model|quota|đảm bảo/.test(text));
assert.equal(presets.compose({references: [{index: 0, role: 'material'}, {index: 5, role: 'material'}, {index: 2, role: 'unknown'}]}), '');
assert.equal(presets.compose({references: [{index: 1, role: 'style'}, {index: 1, role: 'object'}]}).split('\n').length, 1);
assert(presets.compose({references: [{index: 2, role: 'other'}]}).includes('Ảnh tham chiếu 2'));
assert(!presets.compose({references: [{index: 1, role: 'object', region: 'x\n'.repeat(200)}]}).includes('\nx'));
assert(presets.compose({references: Array.from({length: 500}, (_, i) => ({index: i % 4 + 1, role: 'style'}))}).length < 1200);
assert.equal(presets.getOptions('scene'), presets.scene);
assert.equal(presets.getOptions('__proto__').length, 0);
assert(Object.isFrozen(presets.getOptions('unknown')));
console.log('SiteCraft AI presets PASS: immutable options, explicit-only composition, bounded reference roles, unknown-input handling; no provider calls.');
