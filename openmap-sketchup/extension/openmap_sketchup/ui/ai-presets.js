/* SPDX-License-Identifier: MIT
 * Original SiteCraft prompt presets. These are explicit user choices, not a
 * hidden provider prompt or a claim about any model's supported capabilities.
 */
(function (scope) {
  'use strict';

  function options(rows) {
    return Object.freeze(rows.map(function (row) {
      return Object.freeze({ id: row[0], label: row[1], prompt: row[2] });
    }));
  }

  var groups = {
    scene: options([
      ['auto', 'Theo ảnh nguồn', ''],
      ['architecture', 'Ngoại thất kiến trúc', 'Thể hiện ngoại thất công trình với tỷ lệ kiến trúc hợp lý và vật liệu rõ ràng.'],
      ['interior', 'Nội thất', 'Thể hiện không gian nội thất, chú ý tỷ lệ đồ đạc, bề mặt vật liệu và sự chuyển tiếp ánh sáng trong phòng.'],
      ['landscape', 'Cảnh quan', 'Thể hiện cảnh quan với cây cối, mặt đất và không gian ngoài trời có tỷ lệ phù hợp với công trình.'],
      ['aerial', 'Góc nhìn trên cao', 'Thể hiện góc nhìn trên cao, làm rõ tổ chức không gian, tương quan các khối và kết nối cảnh quan.'],
      ['custom', 'Tự mô tả', '']
    ]),
    style: options([
      ['original', 'Theo mô tả và ảnh nguồn', ''],
      ['photoreal', 'Ảnh kiến trúc chân thực', 'Phong cách ảnh kiến trúc chân thực: vật liệu có chi tiết vừa phải, ánh sáng có chiều sâu và màu sắc tự nhiên.'],
      ['editorial', 'Ảnh nội thất tạp chí', 'Bố cục và sắc độ theo ảnh nội thất tạp chí: thanh thoát, cân bằng, nhấn vào chất liệu và khoảng sáng.'],
      ['casual', 'Ảnh chụp đời thường', 'Cảm giác ảnh chụp đời thường với màu sắc tự nhiên, độ tương phản vừa và chi tiết không quá trau chuốt.'],
      ['film', 'Sắc độ ảnh phim', 'Sắc độ gợi ảnh phim: chuyển màu mềm, tương phản dịu và hạt ảnh rất nhẹ, tránh làm mất chi tiết kiến trúc.'],
      ['maquette', 'Mô hình kiến trúc', 'Thể hiện như một mô hình kiến trúc thu nhỏ, giữ hình khối rõ và dùng ánh sáng mềm để đọc được cấu trúc.'],
      ['concept', 'Phối cảnh ý tưởng', 'Thể hiện phối cảnh ý tưởng kiến trúc, hình khối dễ đọc, sắc độ có chủ đích và chi tiết được tiết chế.'],
      ['material', 'Nghiên cứu vật liệu', 'Ưu tiên thể hiện bề mặt và sự phối hợp vật liệu, giữ kích thước vân và độ nhám phù hợp tỷ lệ công trình.'],
      ['custom', 'Tự mô tả', '']
    ]),
    context: options([
      ['original', 'Giữ bối cảnh ảnh nguồn', ''],
      ['neutral', 'Bối cảnh trung tính', 'Dùng bối cảnh trung tính, ít chi tiết gây phân tán và không che khuất công trình chính.'],
      ['vietnam_street', 'Đường phố Việt Nam', 'Bối cảnh đường phố Việt Nam có tỷ lệ và chi tiết sinh hoạt hợp lý; giữ công trình chính là trọng tâm.'],
      ['urban', 'Khu đô thị', 'Bối cảnh đô thị với vỉa hè, không gian công cộng và các khối xung quanh có tỷ lệ phù hợp.'],
      ['garden', 'Vườn nhà ở', 'Bối cảnh vườn nhà ở với lối đi và các lớp cây được tổ chức gọn, không che các phần kiến trúc cần thấy.'],
      ['tropical', 'Vườn nhiệt đới', 'Bối cảnh vườn nhiệt đới với cây lá phù hợp khí hậu, mật độ vừa và khoảng trống đủ để đọc công trình.'],
      ['resort', 'Không gian nghỉ dưỡng', 'Bối cảnh nghỉ dưỡng thoáng, yên tĩnh, với cảnh quan được tổ chức phù hợp kiến trúc và địa hình.'],
      ['coast', 'Ven biển', 'Bối cảnh ven biển với đường chân trời, ánh sáng và thảm thực vật hợp lý; tránh các yếu tố che công trình.'],
      ['mountain', 'Núi và rừng', 'Bối cảnh đồi núi hoặc rừng với lớp xa gần rõ, giữ tỷ lệ địa hình và công trình nhất quán.'],
      ['river', 'Ven sông hoặc hồ', 'Bối cảnh ven sông hoặc hồ, mặt nước và đường bờ có tỷ lệ phù hợp với không gian kiến trúc.'],
      ['rural', 'Làng quê', 'Bối cảnh làng quê với thảm thực vật và chi tiết sinh hoạt thưa, phù hợp tỷ lệ công trình.'],
      ['window_city', 'Ngoài cửa sổ là đô thị', 'Phần nhìn qua cửa sổ là bối cảnh đô thị có độ xa gần hợp lý, cân bằng độ sáng trong và ngoài phòng.'],
      ['window_garden', 'Ngoài cửa sổ là vườn', 'Phần nhìn qua cửa sổ là vườn xanh có chiều sâu, không che khuất hoặc làm thay đổi hình dạng khung cửa.'],
      ['custom', 'Tự mô tả', '']
    ]),
    lighting: options([
      ['original', 'Theo ảnh nguồn', ''],
      ['neutral', 'Ánh sáng cân bằng', 'Ánh sáng cân bằng, đọc rõ các bề mặt, tránh vùng tối bệt và vùng sáng mất chi tiết.'],
      ['daylight', 'Ban ngày dịu', 'Ánh sáng ban ngày dịu với cân bằng trắng tự nhiên và bóng đổ mềm, có hướng hợp lý.'],
      ['sunrise', 'Bình minh', 'Ánh sáng bình minh dịu, hơi ấm, bóng đổ có hướng và sắc độ không quá rực.'],
      ['noon', 'Giữa trưa', 'Ánh sáng giữa trưa rõ và trung tính, tương phản phù hợp, giữ được chi tiết cả vùng nắng lẫn vùng râm.'],
      ['golden', 'Nắng chiều', 'Ánh sáng nắng chiều ấm, có hướng và bóng đổ kéo dài tự nhiên.'],
      ['blue', 'Chạng vạng', 'Ánh sáng chạng vạng với bầu trời dịu và đèn kiến trúc có độ sáng vừa phải.'],
      ['night', 'Ban đêm', 'Không gian ban đêm với chiếu sáng kiến trúc có chủ đích, tránh đèn cháy sáng và màu sắc quá gắt.'],
      ['interior_day', 'Nội thất ban ngày', 'Ánh sáng tự nhiên đi qua các ô cửa của căn phòng, có chuyển tiếp mềm và cân bằng với ánh sáng nội thất.'],
      ['interior_night', 'Nội thất buổi tối', 'Ánh sáng nội thất buổi tối ấm và có phân lớp, nguồn sáng đặt hợp lý và đủ đọc chất liệu.'],
      ['studio', 'Ánh sáng studio', 'Ánh sáng studio mềm, làm rõ hình khối và chất liệu mà không tạo bóng gắt hoặc phản xạ mất chi tiết.'],
      ['custom', 'Tự mô tả', '']
    ]),
    extras: options([
      ['people', 'Một ít người', 'Có thể bổ sung một ít người đúng tỷ lệ để diễn tả quy mô và hoạt động, không che công trình chính.'],
      ['plants', 'Bổ sung cây xanh', 'Có thể bổ sung cây xanh có tỷ lệ và mật độ vừa, đặt phù hợp không gian và giữ lối đi thông thoáng.'],
      ['cars', 'Một ít xe', 'Có thể bổ sung một ít xe đúng tỷ lệ tại vị trí giao thông hoặc chỗ đỗ hợp lý, không lấn các không gian khác.'],
      ['sky', 'Bầu trời dịu', 'Bầu trời tự nhiên, sắc độ vừa phải và phù hợp hướng sáng của cảnh.'],
      ['decor', 'Đồ trang trí vừa phải', 'Có thể bổ sung một ít đồ trang trí phù hợp công năng và tỷ lệ, tránh làm không gian chật hoặc rối.'],
      ['tidy', 'Gọn và tiết chế', 'Tiết chế các chi tiết phụ, tổ chức bối cảnh gọn và giữ các vùng đọc kiến trúc thông thoáng.']
    ]),
    referenceRoles: options([
      ['general', 'Tham khảo chung', 'tham khảo các đặc điểm liên quan đến yêu cầu mô tả, không tự sao chép toàn bộ bố cục'],
      ['material', 'Vật liệu', 'chỉ tham khảo màu sắc, vân và đặc tính bề mặt vật liệu; không lấy bố cục hoặc hình dạng công trình'],
      ['style', 'Phong cách ảnh', 'tham khảo phong cách thể hiện, sắc độ và cảm giác hình ảnh; không tự thay đổi hình khối theo ảnh này'],
      ['lighting', 'Ánh sáng', 'chỉ tham khảo hướng sáng, độ mềm bóng và sắc độ ánh sáng'],
      ['object', 'Đồ vật', 'tham khảo đồ vật được yêu cầu, giữ tỷ lệ và vị trí phù hợp với ảnh nguồn'],
      ['layout', 'Bố cục không gian', 'tham khảo cách tổ chức không gian khi yêu cầu mô tả cho phép; các yêu cầu giữ thiết kế và camera vẫn được ưu tiên'],
      ['surroundings', 'Bối cảnh', 'tham khảo đặc điểm bối cảnh xung quanh, không sao chép công trình chính từ ảnh tham chiếu']
    ])
  };
  Object.freeze(groups);
  var empty = Object.freeze([]);
  var tables = Object.create(null);
  Object.keys(groups).forEach(function (group) {
    tables[group] = Object.create(null);
    groups[group].forEach(function (item) { tables[group][item.id] = item; });
    Object.freeze(tables[group]);
  });
  Object.freeze(tables);

  function selected(group, id) {
    if (typeof id !== 'string' || id.length > 40) return null;
    if (group === 'scene' && id === 'exterior') id = 'architecture';
    if (group === 'referenceRoles' && id === 'other') id = 'general';
    return tables[group][id] || null;
  }
  function regionLabel(value) {
    if (typeof value === 'number') return Number.isInteger(value) && value >= 1 && value <= 12 ? 'vùng ' + value : '';
    if (typeof value !== 'string') return '';
    return value.replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80);
  }
  function compose(input) {
    if (!input || typeof input !== 'object' || Array.isArray(input)) return '';
    var parts = [];
    ['scene', 'style', 'context', 'lighting'].forEach(function (group) {
      var item = selected(group, input[group]);
      if (item && item.prompt) parts.push(item.prompt);
    });
    if (Array.isArray(input.extras)) {
      var used = Object.create(null);
      input.extras.slice(0, 32).forEach(function (id) {
        var item = selected('extras', id);
        if (item && !used[item.id]) { parts.push(item.prompt); used[item.id] = true; }
      });
    }
    if (Array.isArray(input.references)) {
      var seen = Object.create(null);
      input.references.slice(0, 4).forEach(function (reference) {
        if (!reference || typeof reference !== 'object' || !Number.isInteger(reference.index) || reference.index < 1 || reference.index > 4 || seen[reference.index]) return;
        var role = selected('referenceRoles', reference.role);
        if (!role) return;
        seen[reference.index] = true;
        var region = regionLabel(reference.region);
        parts.push('Ảnh tham chiếu ' + reference.index + (region ? ' — áp dụng cho ' + region : '') + ': ' + role.prompt + '.');
      });
    }
    return parts.join('\n');
  }

  var api = {
    version: 1,
    scene: groups.scene,
    style: groups.style,
    context: groups.context,
    lighting: groups.lighting,
    extras: groups.extras,
    referenceRoles: groups.referenceRoles,
    getOptions: function (group) { return Object.prototype.hasOwnProperty.call(groups, group) ? groups[group] : empty; },
    compose: compose
  };
  Object.freeze(api);
  scope.SiteCraftAIPresets = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : (typeof self !== 'undefined' ? self : globalThis));
