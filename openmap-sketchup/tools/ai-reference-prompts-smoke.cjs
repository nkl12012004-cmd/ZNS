/* Adapter tests only; supplied vendor JavaScript is never evaluated. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const prompts = require('../extension/openmap_sketchup/ui/ai-reference-prompts.js');
const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, '../reference/nano_render_prompts.json'), 'utf8'));
const records = Object.fromEntries(catalog.records.map(record => [record.id, record]));

assert.equal(catalog.records.length, 94);
assert.equal(prompts.version, 1);
assert.equal(prompts.productionBaseUnavailable, true);
assert.equal(prompts.usage.mainUIAvailableRecords + prompts.usage.optionalQuickActionRecords + prompts.usage.optionalRegionEditHelperRecords + prompts.usage.catalogOnlyRecords, catalog.records.length);
assert.match(prompts.provenance.base, /preview fixture.*unverified/i);
assert.equal(catalog.rights.license, 'NOASSERTION');
assert(catalog.records.every(record => record.source.source_sha256 && record.source.original_line >= 1));
assert.equal(prompts.basePreviewFixture.render, records['preview_fixture.hidden_prompt'].exact_decoded_text);
assert.equal(prompts.basePreviewFixture.edit, records['preview_fixture.edit_prompt'].exact_decoded_text);
assert.equal(records['preview_fixture.hidden_prompt'].scope, 'browser_preview_fixture_only');
assert.equal(records['preview_fixture.edit_prompt'].scope, 'browser_preview_fixture_only');

for (const category of ['scene', 'style', 'context', 'lighting', 'extras', 'referenceRoles', 'regionQuickActions']) {
  assert.equal(prompts[category].length, catalog.groups[category].length);
  assert(Object.isFrozen(prompts[category]));
  for (const row of prompts[category]) {
    assert(Object.isFrozen(row));
    const source = records[row.record_id];
    assert.equal(row.prompt, source.exact_decoded_text);
    assert.equal(row.label, source.label);
  }
}
assert.equal(prompts.getOptions('__proto__').length, 0);
assert.throws(() => { prompts.scene[0].prompt = 'mutated'; }, TypeError);
assert.equal(prompts.composeFull({operation: 'upscale', userText: 'must not send'}), '');

const input = {basePrompt: '', operation: 'render', userText: 'Tường sơn màu kem.', keepDesign: true, keepCamera: true,
  scene: 'architecture', style: 'photoreal', context: 'garden', lighting: 'golden', extras: ['plants', 'plants'],
  references: [{index: 1, role: 'material'}], aspect: '16:9', annotationNotes: 'Vùng 1 (đỏ, 10%, 20%, 50%, 70%): thay bề mặt gỗ.'};
const snapshot = JSON.stringify(input), full = prompts.composeFull(input);
assert.equal(JSON.stringify(input), snapshot);
assert(full.includes(records['assembly.keep_design'].exact_decoded_text));
assert(full.includes(records['assembly.keep_camera'].exact_decoded_text));
assert(full.includes(records['scene.exterior'].exact_decoded_text));
assert(full.includes(records['style.arch'].exact_decoded_text));
assert(full.includes(records['context.residential'].exact_decoded_text));
assert(full.includes(records['lighting.golden'].exact_decoded_text));
assert(full.includes(records['extras.plants'].exact_decoded_text));
assert.equal(full.split(records['extras.plants'].exact_decoded_text).length - 1, 1);
assert(full.includes('- Ảnh tham chiếu 1 (Vật liệu): ' + records['referenceRoles.material'].exact_decoded_text + '.'));
assert(full.includes('Tỉ lệ khung hình ảnh kết quả: 16:9.'));
assert.equal(full.split(input.annotationNotes).length - 1, 1);
assert.equal(full.split(records['assembly.annotation.erase'].exact_decoded_text).length - 1, 1);
assert(full.endsWith(records['assembly.output_constraints'].exact_decoded_text));
assert(!full.includes(prompts.basePreviewFixture.render), 'Explicit empty base must not silently add a preview fixture');

const edit = prompts.composeFull({basePrompt:'', operation:'edit', keepCamera:false, keepDesign:true, userText:'Đổi sofa.'});
assert(edit.includes(records['assembly.edit_preserve'].exact_decoded_text));
assert(!edit.includes(records['assembly.keep_design'].exact_decoded_text));
assert(!edit.includes(records['assembly.keep_camera'].exact_decoded_text));
const notes = '  Vùng 2: ghi chú nguyên văn.\nKhông thay bên ngoài.  ';
assert(prompts.composeAnnotationNotes(notes).includes(notes));
assert.equal(prompts.composeAnnotationNotes(''), '');
assert.equal(prompts.composeAnnotationNotes(prompts.composeAnnotationNotes(notes)).split(records['assembly.annotation.erase'].exact_decoded_text).length-1,1);
assert.throws(() => prompts.composeAnnotationNotes('x'.repeat(4001)), /quá dài/);
assert(!prompts.composeFull({basePrompt:'',keepDesign:false,keepCamera:false,aspect:'javascript:alert(1)'}).includes('javascript'));

const retouch = prompts.composeRegionEdit({userText:'Thay vải sofa',colors:['đỏ'],textureLabels:['linen màu kem']});
assert(retouch.startsWith('Chỉnh sửa ảnh đính kèm. Chỉ thay đổi bên trong vùng được khoanh màu đỏ: Thay vải sofa.'));
assert(retouch.includes('ảnh 1 (linen màu kem)'));
assert(retouch.includes(records['region_edit.7'].exact_decoded_text));
assert(retouch.includes(records['region_edit.8'].exact_decoded_text));
assert(retouch.endsWith(records['region_edit.9'].exact_decoded_text));
assert(prompts.composeRegionEdit({}).includes(records['region_edit.default_texture_request'].exact_decoded_text));
console.log('SiteCraft exact reference prompts PASS: 94 provenance records; exact option/assembly/region text, explicit preview-fixture scope, bounded notes and no vendor code execution.');
