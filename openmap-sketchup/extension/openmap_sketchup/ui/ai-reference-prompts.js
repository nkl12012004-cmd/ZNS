/* SiteCraft adapter logic: MIT. Embedded prompt TEXT retains original rights.
 * Readable text reproduced from the user's Nano Banana Render 2.6.14 archive
 * at their explicit request. No vendor JavaScript, keys or native code runs.
 * Full source/provenance/limits: reference/nano_render_prompts.json.
 */
(function (scope) {
  'use strict';
  var data = {"provenance":{"source_product":"Nano Banana Render 2.6.14 (user-supplied installer)","source_archive_sha256":"ce758f9c9bfa46c8f155e374868ee360b8467e125388e0a1c431d2c66b6348d5","source_app_sha256":"19b6bad6f0fea0b9f48bde8204e41dffd12796e80e0b79e8739a0549bfd38b64","rights":{"license":"NOASSERTION","notice":"Original prompt text rights are retained. Reproduced from the user-supplied installer at the user’s explicit request. No license for all Nano Render code/text is inferred.","implementation_separate":"SiteCraft adapter logic is independently written. Vendor code, authentication, keys and binary modules are excluded."},"base":"Readable browser-preview fixture only; production encrypted Ruby defaults are unverified.","records":94},"groups":{"lighting":[{"id":"none","label":"Theo ảnh gốc","prompt":"","record_id":"lighting.none"},{"id":"day","label":"Ban ngày tự nhiên","prompt":"ánh sáng ban ngày tự nhiên, trời trong, nắng dịu, bóng đổ mềm và chân thực","record_id":"lighting.day"},{"id":"morning","label":"Bình minh","prompt":"nắng sớm bình minh, ánh sáng vàng nhạt dịu, bóng đổ dài, không khí trong lành","record_id":"lighting.morning"},{"id":"noon","label":"Trưa nắng gắt","prompt":"nắng trưa gay gắt, bầu trời xanh, bóng đổ sắc nét, tương phản cao","record_id":"lighting.noon"},{"id":"golden","label":"Hoàng hôn – giờ vàng","prompt":"giờ vàng lúc hoàng hôn, nắng vàng cam ấm áp chiếu xiên, bóng đổ dài, bầu trời ráng chiều","record_id":"lighting.golden"},{"id":"blue","label":"Chạng vạng – blue hour","prompt":"giờ xanh lúc chạng vạng, bầu trời xanh thẫm, đèn trong nhà và đèn ngoại thất đã bật sáng ấm, tương phản nóng lạnh đẹp","record_id":"lighting.blue"},{"id":"night","label":"Ban đêm","prompt":"ban đêm, chiếu sáng nhân tạo ấm áp từ đèn trong nhà, đèn hắt tường, đèn sân vườn, có phản chiếu ánh đèn","record_id":"lighting.night"},{"id":"overcast","label":"Trời âm u","prompt":"trời nhiều mây, ánh sáng khuếch tán mềm và đều, gần như không có bóng đổ gắt","record_id":"lighting.overcast"},{"id":"rain","label":"Sau mưa","prompt":"vừa tạnh mưa, mặt đất và các bề mặt ướt phản chiếu ánh sáng, không khí ẩm mát","record_id":"lighting.rain"},{"id":"int_day","label":"Nội thất – nắng qua cửa","prompt":"ánh sáng tự nhiên tràn vào qua cửa sổ, vệt nắng trên sàn, ánh sáng mềm, cân bằng với đèn nội thất ấm","record_id":"lighting.int_day"},{"id":"int_night","label":"Nội thất – tối ấm cúng","prompt":"buổi tối, bật toàn bộ đèn nội thất: đèn hắt trần, đèn thả, đèn bàn; ánh sáng vàng ấm cúng, tương phản sáng tối nhẹ nhàng","record_id":"lighting.int_night"},{"id":"studio","label":"Studio mềm","prompt":"ánh sáng studio mềm, đều và trung tính, bóng rất nhẹ","record_id":"lighting.studio"},{"id":"custom","label":"Tuỳ chỉnh…","prompt":"","record_id":"lighting.custom"}],"context":[{"id":"none","label":"Giữ nguyên","prompt":"","record_id":"context.none"},{"id":"vn_street","label":"Phố đô thị Việt Nam","prompt":"đường phố đô thị Việt Nam hiện đại: vỉa hè lát gạch, cây xanh đường phố, các nhà phố lân cận, vài xe máy và người đi đường","record_id":"context.vn_street"},{"id":"residential","label":"Khu dân cư sân vườn","prompt":"khu dân cư yên tĩnh với sân vườn cỏ xanh, cây bụi, cây bóng mát, lối đi lát đá tự nhiên","record_id":"context.residential"},{"id":"villa","label":"Biệt thự nhiệt đới","prompt":"cảnh quan nhiệt đới sang trọng: hồ bơi, cây cau, cây dừa, thảm cỏ, tiểu cảnh xanh mướt","record_id":"context.villa"},{"id":"urban","label":"Trung tâm thành phố","prompt":"trung tâm thành phố với các toà nhà cao tầng phía xa, đường phố sầm uất","record_id":"context.urban"},{"id":"sea","label":"Ven biển","prompt":"ven biển, bãi cát, mặt biển xanh và đường chân trời rộng","record_id":"context.sea"},{"id":"mountain","label":"Đồi núi, rừng thông","prompt":"đồi núi và rừng thông, sương mù nhẹ phía xa, không khí cao nguyên","record_id":"context.mountain"},{"id":"lake","label":"Ven sông hồ","prompt":"ven sông hồ, mặt nước phản chiếu công trình, cây xanh bờ nước","record_id":"context.lake"},{"id":"country","label":"Làng quê Việt Nam","prompt":"làng quê Việt Nam với cánh đồng lúa, luỹ tre, đường làng","record_id":"context.country"},{"id":"win_city","label":"Nội thất – view thành phố","prompt":"qua cửa kính nhìn ra toàn cảnh thành phố từ trên cao","record_id":"context.win_city"},{"id":"win_garden","label":"Nội thất – view sân vườn","prompt":"qua cửa kính nhìn ra sân vườn cây xanh mát mắt","record_id":"context.win_garden"},{"id":"custom","label":"Tuỳ chỉnh…","prompt":"","record_id":"context.custom"}],"style":[{"id":"none","label":"Mặc định","prompt":"","record_id":"style.none"},{"id":"arch","label":"Ảnh kiến trúc chuyên nghiệp","prompt":"ảnh chụp kiến trúc chuyên nghiệp bằng máy ảnh full-frame, ống kính góc rộng, đường thẳng đứng không méo, độ nét cao, dải tương phản rộng, màu sắc trung thực","record_id":"style.arch"},{"id":"editorial","label":"Tạp chí nội thất","prompt":"ảnh nội thất phong cách tạp chí (editorial), bố cục sạch sẽ, ánh sáng mềm, chi tiết vật liệu sắc nét, tông màu tinh tế","record_id":"style.editorial"},{"id":"phone","label":"Ảnh điện thoại đời thường","prompt":"ảnh chụp bằng điện thoại thông thường, cảm giác chân thực đời thường, không quá hoàn hảo","record_id":"style.phone"},{"id":"film","label":"Phim analog","prompt":"ảnh phim analog, hạt phim nhẹ, màu ấm hoài cổ","record_id":"style.film"},{"id":"drone","label":"Flycam","prompt":"ảnh chụp bằng flycam (drone) từ trên cao, rõ nét","record_id":"style.drone"},{"id":"custom","label":"Tuỳ chỉnh…","prompt":"","record_id":"style.custom"}],"extras":[{"id":"people","label":"Thêm người","prompt":"thêm vài người sinh hoạt tự nhiên, đúng tỉ lệ","record_id":"extras.people"},{"id":"plants","label":"Thêm cây xanh","prompt":"thêm cây xanh, chậu cây phù hợp","record_id":"extras.plants"},{"id":"cars","label":"Thêm xe cộ","prompt":"thêm xe ô tô, xe máy đỗ hoặc di chuyển hợp lý","record_id":"extras.cars"},{"id":"sky","label":"Bầu trời đẹp","prompt":"bầu trời có mây đẹp, tự nhiên","record_id":"extras.sky"},{"id":"decor","label":"Đồ trang trí","prompt":"thêm đồ trang trí, vật dụng sinh hoạt hợp phong cách","record_id":"extras.decor"},{"id":"clean","label":"Gọn gàng tối giản","prompt":"không gian gọn gàng, tối giản, không bày biện thừa","record_id":"extras.clean"}],"scene":[{"id":"auto","label":"Tự nhận diện","prompt":"","record_id":"scene.auto"},{"id":"interior","label":"Nội thất","prompt":"Đây là không gian nội thất.","record_id":"scene.interior"},{"id":"exterior","label":"Ngoại thất","prompt":"Đây là công trình kiến trúc ngoại thất.","record_id":"scene.exterior"},{"id":"landscape","label":"Cảnh quan","prompt":"Đây là thiết kế cảnh quan.","record_id":"scene.landscape"},{"id":"aerial","label":"Phối cảnh tổng thể","prompt":"Đây là phối cảnh tổng thể nhìn từ trên cao.","record_id":"scene.aerial"}],"referenceRoles":[{"id":"style","label":"Phong cách","prompt":"lấy phong cách, tông màu và cảm giác tổng thể từ ảnh này","record_id":"referenceRoles.style"},{"id":"material","label":"Vật liệu","prompt":"áp dụng vật liệu / hoàn thiện trong ảnh này cho các bề mặt tương ứng","record_id":"referenceRoles.material"},{"id":"light","label":"Ánh sáng","prompt":"lấy cách chiếu sáng và không khí ánh sáng từ ảnh này","record_id":"referenceRoles.light"},{"id":"object","label":"Đồ vật","prompt":"đưa đồ vật / nội thất trong ảnh này vào vị trí phù hợp","record_id":"referenceRoles.object"},{"id":"context","label":"Bao cảnh","prompt":"dùng cảnh quan / bối cảnh xung quanh giống ảnh này","record_id":"referenceRoles.context"},{"id":"other","label":"Khác","prompt":"tham khảo ảnh này","record_id":"referenceRoles.other"}],"regionQuickActions":[{"id":"1","label":"Thay vật liệu","prompt":"Thay vật liệu trong vùng khoanh bằng texture ở ảnh vật liệu 1, giữ nguyên hình dáng đồ vật","record_id":"regionQuickActions.1"},{"id":"2","label":"Đổi màu","prompt":"Đổi màu đồ vật trong vùng khoanh sang ","record_id":"regionQuickActions.2"},{"id":"3","label":"Xoá vật thể","prompt":"Xoá đồ vật trong vùng khoanh, lấp lại nền tự nhiên","record_id":"regionQuickActions.3"},{"id":"4","label":"Thêm đồ vật","prompt":"Thêm vào vùng khoanh: ","record_id":"regionQuickActions.4"},{"id":"5","label":"Sáng hơn","prompt":"Làm vùng khoanh sáng và rõ hơn, ánh sáng tự nhiên","record_id":"regionQuickActions.5"}]},"assembly":{"edit_preserve":"Giữ nguyên bố cục và mọi chi tiết không được yêu cầu thay đổi.","keep_design":"Bám sát thiết kế: giữ nguyên chính xác hình khối kiến trúc, bố cục, tỉ lệ, kích thước, vị trí đồ vật, vật liệu và màu sắc như trong ảnh gốc; không tự thêm, bớt hay thay đổi chi tiết thiết kế nào ngoài những gì tôi yêu cầu bên dưới. Chỉ nâng cấp thành chất lượng ảnh chụp thật: vật liệu chân thực, ánh sáng tự nhiên, bóng đổ, phản xạ và chi tiết bề mặt.","keep_camera":"Không thay đổi góc camera: giữ nguyên chính xác vị trí đặt máy, hướng nhìn, độ cao, tiêu cự và phối cảnh như ảnh gốc; không xoay, không đổi góc, không phóng to hay thu nhỏ.","prefix.lighting":"Ánh sáng: ","prefix.context":"Bao cảnh xung quanh: ","prefix.style":"Phong cách ảnh: ","prefix.extras":"Bổ sung: ","prefix.user":"Yêu cầu thêm của tôi: ","annotation.intro":"Trên ảnh chính có các vùng được khoanh bằng nét màu kèm ghi chú – làm đúng ghi chú ở từng vùng (mỗi màu là một vùng riêng), các phần khác theo yêu cầu chung:","annotation.default_note":"chú ý xử lý vùng này đúng yêu cầu chung","annotation.additional":"Ghi chú thêm: ","references.intro":"Ảnh chính là ảnh khung nhìn SketchUp (01_khung_sketchup). Các ảnh còn lại là ảnh tham chiếu:","references.marked_intro":"Trên ảnh này có vùng khoanh: ","references.default_mark":"phần cần lấy theo","references.marked_suffix":" (nét khoanh chỉ để chỉ chỗ, không đưa nét vẽ vào ảnh kết quả).","references.note_prefix":"Ghi chú: ","output_constraints":"Không thêm chữ, logo, watermark hay khung viền. Kết quả là một bức ảnh chụp chân thực duy nhất, đúng tỉ lệ khung hình yêu cầu.","annotation.erase":"Các nét khoanh màu chỉ là đánh dấu vị trí: xoá hoàn toàn, ảnh kết quả không còn bất kỳ nét vẽ hay đường viền màu nào."},"dynamic":{"reference":["- Ảnh tham chiếu "," (","): ",".",""],"aspect":["Tỉ lệ khung hình ảnh kết quả: ","."]},"region":{"one_region":["vùng được khoanh màu ",""],"many_regions":["các vùng được khoanh màu "," (mỗi màu là một vùng riêng)"],"marked_request":["Chỉnh sửa ảnh đính kèm. Chỉ thay đổi bên trong ",": ",""],"request":["Chỉnh sửa ảnh đính kèm: ",""],"texture_intro":" Ảnh vật liệu / texture gửi kèm: ","texture_item":["ảnh ","",""],"texture_match":" Áp đúng màu sắc, hoa văn, chất liệu và độ bóng của texture lên bề mặt cần sửa; kích thước vân theo tỉ lệ thật và phối cảnh; ánh sáng, bóng đổ, nếp vải khớp với cảnh.","preserve":" Giữ nguyên tuyệt đối mọi phần còn lại: bố cục, góc máy, phối cảnh, hình khối, ánh sáng và các đồ vật khác.","erase":" Các nét khoanh màu chỉ là đánh dấu: xoá hoàn toàn, ảnh kết quả không còn bất kỳ nét vẽ hay đường viền màu nào.","default_texture_request":"áp vật liệu theo ảnh texture gửi kèm"},"preview":{"hidden_prompt":"Biến ảnh tôi gửi thành ảnh chụp thực tế.","edit_prompt":"Chỉnh sửa ảnh tôi gửi theo yêu cầu bên dưới, giữ nguyên những phần không được nhắc tới."}};
  function freeze(value) {
    if (value && typeof value === 'object') {
      Object.keys(value).forEach(function (key) { freeze(value[key]); });
      Object.freeze(value);
    }
    return value;
  }
  freeze(data);
  var mappings = {
    scene: { exterior: 'architecture' },
    lighting: { none: 'original', day: 'daylight', morning: 'sunrise', int_day: 'interior_day', int_night: 'interior_night' },
    context: { none: 'original', vn_street: 'vietnam_street', residential: 'garden', villa: 'tropical', sea: 'coast', lake: 'river', country: 'rural', win_city: 'window_city', win_garden: 'window_garden' },
    style: { none: 'original', arch: 'photoreal', phone: 'casual' },
    extras: { clean: 'tidy' },
    referenceRoles: { light: 'lighting', context: 'surroundings', other: 'general' }
  };
  var groups = Object.create(null), lookup = Object.create(null), empty = Object.freeze([]);
  Object.keys(data.groups).forEach(function (name) {
    var map = mappings[name] || {}, table = Object.create(null);
    groups[name] = data.groups[name].map(function (item) {
      var row = Object.freeze({ id: map[item.id] || item.id, source_id: item.id, label: item.label, prompt: item.prompt, record_id: item.record_id });
      table[row.id] = table[item.id] = row;
      return row;
    });
    Object.freeze(groups[name]); lookup[name] = Object.freeze(table);
  });
  freeze(groups); freeze(lookup);
  function choose(group, id) {
    return typeof id === 'string' && id.length <= 64 && lookup[group] ? lookup[group][id] || null : null;
  }
  function bounded(value, limit, label) {
    if (value == null) return '';
    if (typeof value !== 'string' || value.length > limit || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value)) throw new Error(label + ' quá dài hoặc không hợp lệ.');
    return value;
  }
  function fill(parts, values) {
    return parts.map(function (part, index) { return part + (index < values.length ? values[index] : ''); }).join('');
  }
  function pushChoices(parts, input) {
    var scene = choose('scene', input.scene);
    if (scene && scene.prompt) parts.push(scene.prompt);
    [['lighting', 'prefix.lighting'], ['context', 'prefix.context'], ['style', 'prefix.style']].forEach(function (entry) {
      var selected = choose(entry[0], input[entry[0]]), text = selected && selected.prompt || '';
      if (selected && selected.source_id === 'custom') text = bounded(input[entry[0] + 'Custom'], 1000, 'Mô tả tùy chỉnh').trim();
      if (text) parts.push(data.assembly[entry[1]] + text + '.');
    });
    var extras = [], seen = Object.create(null);
    if (Array.isArray(input.extras)) input.extras.slice(0, 32).forEach(function (id) {
      var selected = choose('extras', id);
      if (selected && !seen[selected.id]) { extras.push(selected.prompt); seen[selected.id] = true; }
    });
    if (extras.length) parts.push(data.assembly['prefix.extras'] + extras.join('; ') + '.');
  }
  function pushReferences(parts, input) {
    if (!Array.isArray(input.references) || !input.references.length) return;
    var rows = [], seen = Object.create(null);
    input.references.slice(0, 13).forEach(function (reference) {
      if (!reference || !Number.isInteger(reference.index) || reference.index < 1 || reference.index > 13 || seen[reference.index]) return;
      var selected = choose('referenceRoles', reference.role) || choose('referenceRoles', 'style');
      var note = bounded(reference.note, 1000, 'Ghi chú ảnh tham chiếu').trim() || selected.prompt;
      rows.push(fill(data.dynamic.reference, [reference.index, selected.label, note.replace(/[.\s]+$/, ''), '']));
      seen[reference.index] = true;
    });
    if (rows.length) parts.push(data.assembly['references.intro'], rows.join('\n'));
  }
  function compose(input) {
    input = input && typeof input === 'object' && !Array.isArray(input) ? input : {};
    var parts = [];
    pushChoices(parts, input); pushReferences(parts, input);
    return parts.join('\n');
  }
  function composeAnnotationNotes(notes) {
    notes = bounded(notes, 4000, 'Ghi chú vùng');
    if (!notes.trim()) return '';
    var parts = [];
    if (notes.indexOf(data.assembly['annotation.intro']) < 0) parts.push(data.assembly['annotation.intro']);
    parts.push(notes); // Preserve the caller's bounds, labels and notes verbatim.
    if (notes.indexOf(data.assembly['annotation.erase']) < 0) parts.push(data.assembly['annotation.erase']);
    return parts.join('\n');
  }
  function composeFull(input) {
    input = input && typeof input === 'object' && !Array.isArray(input) ? input : {};
    if (input.operation === 'upscale') return '';
    var editing = input.operation === 'edit', parts = [];
    // These defaults are VERIFIED READABLE PREVIEW FIXTURES. Their production
    // encrypted Ruby equivalents remain unknown; callers may override/omit.
    var base = Object.prototype.hasOwnProperty.call(input, 'basePrompt') ? bounded(input.basePrompt, 4000, 'Câu lệnh cơ sở') : editing ? data.preview.edit_prompt : data.preview.hidden_prompt;
    if (base.trim()) parts.push(base.trim());
    if (editing) parts.push(data.assembly.edit_preserve);
    else if (input.keepDesign !== false) parts.push(data.assembly.keep_design);
    if (input.keepCamera !== false) parts.push(data.assembly.keep_camera);
    pushChoices(parts, input);
    var request = bounded(input.userText, 8000, 'Yêu cầu').trim();
    if (request) parts.push(data.assembly['prefix.user'] + request);
    var marks = composeAnnotationNotes(input.annotationNotes);
    if (marks) parts.push(marks);
    pushReferences(parts, input);
    var aspect = typeof input.aspect === 'string' ? input.aspect : '';
    if (/^[1-9][0-9]{0,3}:[1-9][0-9]{0,3}$/.test(aspect)) {
      var pair = aspect.split(':'), ratio = Number(pair[0]) / Number(pair[1]);
      if (ratio >= .05 && ratio <= 20) parts.push(fill(data.dynamic.aspect, [aspect]));
    }
    parts.push(data.assembly.output_constraints);
    return parts.filter(Boolean).join('\n');
  }
  function composeRegionEdit(input) {
    input = input && typeof input === 'object' ? input : {};
    var colors = Array.isArray(input.colors) ? input.colors.slice(0, 12).map(function (value) { return bounded(value, 40, 'Tên màu').trim(); }).filter(Boolean) : [];
    var request = bounded(input.userText, 8000, 'Yêu cầu').trim() || data.region.default_texture_request;
    var where = colors.length === 1 ? fill(data.region.one_region, [colors[0]]) : fill(data.region.many_regions, [colors.join(', ')]);
    var result = colors.length ? fill(data.region.marked_request, [where, request]) : fill(data.region.request, [request]);
    if (!/[.!?]$/.test(result)) result += '.';
    if (Array.isArray(input.textureLabels) && input.textureLabels.length) {
      var labels = input.textureLabels.slice(0, 13).map(function (label, index) {
        label = bounded(label, 120, 'Tên vật liệu').trim();
        return fill(data.region.texture_item, [index + 1, label ? ' (' + label + ')' : '']);
      });
      result += data.region.texture_intro + labels.join(', ') + '.' + data.region.texture_match;
    }
    result += data.region.preserve;
    if (colors.length) result += data.region.erase;
    return result;
  }
  var api = {
    version: 1,
    provenance: data.provenance,
    usage: Object.freeze({ catalogRecords: 94, mainUIPresetRoleRecords: 49, mainUIAssemblyLiteralAndTemplateRecords: 14,
      selectablePreviewBaseFixtures: 2, mainUIAvailableRecords: 65, optionalQuickActionRecords: 5,
      optionalRegionEditHelperRecords: 10, catalogOnlyRecords: 14,
      note: 'Available records across code paths, not the number of instructions added to each request. Only selected options are composed.' }),
    productionBaseUnavailable: true,
    basePreviewFixture: Object.freeze({ render: data.preview.hidden_prompt, edit: data.preview.edit_prompt }),
    scene: groups.scene, style: groups.style, context: groups.context, lighting: groups.lighting,
    extras: groups.extras, referenceRoles: groups.referenceRoles, regionQuickActions: groups.regionQuickActions,
    getOptions: function (group) { return groups[group] || empty; },
    compose: compose, composeFull: composeFull, composeAnnotationNotes: composeAnnotationNotes, composeRegionEdit: composeRegionEdit
  };
  Object.freeze(api);
  scope.SiteCraftAIReferencePrompts = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : (typeof self !== 'undefined' ? self : globalThis));
