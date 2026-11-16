/* SPDX-License-Identifier: MIT — dependency-free mesh preview, WebGL 1.0 */
(function () {
  'use strict';
  var canvas = document.getElementById('preview3d'), gl = null, program, draws = [], textures = [];
  var radius = 200, distance = 500, yaw = -.65, pitch = .65, pan = [0, 0, 0], drag = null;
  function multiply(a, b) {
    var out = new Float32Array(16);
    for (var c = 0; c < 4; c++) for (var r = 0; r < 4; r++) for (var k = 0; k < 4; k++) out[c * 4 + r] += a[k * 4 + r] * b[c * 4 + k];
    return out;
  }
  function normalized(v) { var n = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) || 1; return v.map(function (x) { return x / n; }); }
  function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function initialize() {
    if (gl) return;
    gl = canvas.getContext('webgl', { antialias: true, alpha: false });
    if (!gl) throw new Error('Máy chưa hỗ trợ WebGL trong HtmlDialog. Vẫn có thể nạp trực tiếp vào SketchUp.');
    if (!gl.getExtension('OES_element_index_uint')) throw new Error('WebGL thiếu hỗ trợ chỉ số lưới 32-bit.');
    function shader(type, source) {
      var value = gl.createShader(type); gl.shaderSource(value, source); gl.compileShader(value);
      if (!gl.getShaderParameter(value, gl.COMPILE_STATUS)) throw new Error('Không biên dịch được shader xem trước.');
      return value;
    }
    program = gl.createProgram();
    var vs = shader(gl.VERTEX_SHADER, 'attribute vec3 p;attribute vec3 n;attribute vec2 uv;uniform mat4 mvp;varying vec3 normal;varying vec2 tex;void main(){normal=n;tex=uv;gl_Position=mvp*vec4(p,1.0);}');
    var fs = shader(gl.FRAGMENT_SHADER, 'precision mediump float;varying vec3 normal;varying vec2 tex;uniform vec4 color;uniform sampler2D image;uniform int textured;uniform int wire;void main(){vec4 b=color;if(textured==1)b*=texture2D(image,tex);float light=.4+.6*abs(dot(normalize(normal),normalize(vec3(.4,.9,.3))));gl_FragColor=wire==1?vec4(.1,.45,.85,1.):vec4(b.rgb*light,b.a);}');
    gl.attachShader(program, vs); gl.attachShader(program, fs); gl.linkProgram(program);
    gl.deleteShader(vs); gl.deleteShader(fs);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('Không khởi tạo được trình xem 3D.');
  }
  function buffer(values, target) { var b = gl.createBuffer(); gl.bindBuffer(target, b); gl.bufferData(target, values, gl.STATIC_DRAW); return b; }
  function clear() {
    if (!gl) return;
    draws.forEach(function (d) { [d.p, d.n, d.uv, d.faces, d.lines].forEach(function (b) { gl.deleteBuffer(b); }); });
    textures.forEach(function (t) { gl.deleteTexture(t); }); draws = []; textures = [];
  }
  function imageTexture(source, ground) {
    var encoded = source.texture_png || source.texture_jpeg;
    if (!encoded) return Promise.resolve(null);
    return new Promise(function (resolve) {
      var image = new Image();
      image.onload = function () {
        var t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t); gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
        var pot = (image.width & (image.width - 1)) === 0 && (image.height & (image.height - 1)) === 0;
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, !ground && pot ? gl.REPEAT : gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, !ground && pot ? gl.REPEAT : gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        textures.push(t); resolve(t);
      };
      image.onerror = function () { resolve(null); };
      image.src = 'data:image/' + (source.texture_jpeg ? 'jpeg' : 'png') + ';base64,' + encoded;
    });
  }
  function load(model) {
    try { initialize(); } catch (error) { gl = null; throw error; }
    clear();
    var minimum = [Infinity, Infinity, Infinity], maximum = [-Infinity, -Infinity, -Infinity];
    model.meshes.forEach(function (m) { m.vertices.forEach(function (v) { for (var a = 0; a < 3; a++) { minimum[a] = Math.min(minimum[a], v[a]); maximum[a] = Math.max(maximum[a], v[a]); } }); });
    var center = minimum.map(function (v, i) { return (v + maximum[i]) / 2; });
    radius = Math.max(1, maximum[0] - minimum[0], maximum[1] - minimum[1], maximum[2] - minimum[2]) * .65;
    return Promise.all(model.materials.map(function (m, i) { return imageTexture(m, i === 0); })).then(function (images) {
      model.meshes.forEach(function (m) {
        var vertices = m.vertices, uv = m.uv, triangles = m.triangles;
        if (!m.smooth) {
          var expanded = [], expandedUV = [], indices = [];
          triangles.forEach(function (t) { var start = expanded.length; t.forEach(function (i) { expanded.push(vertices[i]); if (uv.length) expandedUV.push(uv[i]); }); indices.push([start, start + 1, start + 2]); });
          vertices = expanded; uv = expandedUV; triangles = indices;
        }
        var positions = [], normals = new Float32Array(vertices.length * 3), uvs = [], indices = [], lines = [];
        vertices.forEach(function (v, i) { positions.push(v[0] - center[0], v[2] - center[2], -(v[1] - center[1])); uvs.push(uv.length ? uv[i][0] : 0, uv.length ? uv[i][1] : 0); });
        triangles.forEach(function (t) {
          var p = t.map(function (index) { return positions.slice(index * 3, index * 3 + 3); });
          var n = cross(p[1].map(function (v, i) { return v - p[0][i]; }), p[2].map(function (v, i) { return v - p[0][i]; }));
          t.forEach(function (index) { for (var a = 0; a < 3; a++) normals[index * 3 + a] += n[a]; });
          indices.push(t[0], t[1], t[2]); lines.push(t[0], t[1], t[1], t[2], t[2], t[0]);
        });
        for (var i = 0; i < normals.length; i += 3) { var n = normalized([normals[i], normals[i + 1], normals[i + 2]]); normals[i] = n[0]; normals[i + 1] = n[1]; normals[i + 2] = n[2]; }
        var material = model.materials[m.material];
        draws.push({ p: buffer(new Float32Array(positions), gl.ARRAY_BUFFER), n: buffer(normals, gl.ARRAY_BUFFER), uv: buffer(new Float32Array(uvs), gl.ARRAY_BUFFER), faces: buffer(new Uint32Array(indices), gl.ELEMENT_ARRAY_BUFFER), lines: buffer(new Uint32Array(lines), gl.ELEMENT_ARRAY_BUFFER), count: indices.length, lineCount: lines.length, texture: images[m.material], color: material.color.map(function (v) { return v / 255; }).concat([material.alpha === undefined ? 1 : material.alpha]) });
      });
      reset();
    });
  }
  function render() {
    if (!gl || !program || canvas.hidden) return;
    var scale = Math.min(2, window.devicePixelRatio || 1), w = Math.max(1, Math.round(canvas.clientWidth * scale)), h = Math.max(1, Math.round(canvas.clientHeight * scale));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    gl.viewport(0, 0, w, h); gl.clearColor(.85, .9, .93, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST); gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.useProgram(program);
    var eye = [pan[0] + distance * Math.sin(yaw) * Math.cos(pitch), pan[1] + distance * Math.sin(pitch), pan[2] + distance * Math.cos(yaw) * Math.cos(pitch)];
    var z = normalized(eye.map(function (v, i) { return v - pan[i]; })), x = normalized(cross([0, 1, 0], z)), y = cross(z, x);
    var view = [x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, eye), -dot(y, eye), -dot(z, eye), 1];
    var f = 1 / Math.tan(Math.PI / 8), near = Math.max(.05, distance / 10000), far = distance + radius * 15;
    var projection = [f / (w / h), 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) / (near - far), -1, 0, 0, 2 * far * near / (near - far), 0];
    gl.uniformMatrix4fv(gl.getUniformLocation(program, 'mvp'), false, multiply(projection, view));
    function attribute(name, b, size) { var location = gl.getAttribLocation(program, name); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.enableVertexAttribArray(location); gl.vertexAttribPointer(location, size, gl.FLOAT, false, 0, 0); }
    draws.forEach(function (d) {
      attribute('p', d.p, 3); attribute('n', d.n, 3); attribute('uv', d.uv, 2);
      gl.uniform4fv(gl.getUniformLocation(program, 'color'), d.color); gl.uniform1i(gl.getUniformLocation(program, 'textured'), d.texture ? 1 : 0); gl.uniform1i(gl.getUniformLocation(program, 'wire'), api.wireframe ? 1 : 0);
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, d.texture); gl.uniform1i(gl.getUniformLocation(program, 'image'), 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, api.wireframe ? d.lines : d.faces); gl.drawElements(api.wireframe ? gl.LINES : gl.TRIANGLES, api.wireframe ? d.lineCount : d.count, gl.UNSIGNED_INT, 0);
    });
  }
  function reset() { yaw = -.65; pitch = .65; distance = radius * 2.7; pan = [0, 0, 0]; render(); }
  canvas.oncontextmenu = function (event) { event.preventDefault(); };
  canvas.onpointerdown = function (event) { drag = { x: event.clientX, y: event.clientY, right: event.button === 2 }; canvas.setPointerCapture(event.pointerId); };
  canvas.onpointermove = function (event) {
    if (!drag) return; var dx = event.clientX - drag.x, dy = event.clientY - drag.y; drag.x = event.clientX; drag.y = event.clientY;
    if (drag.right) { pan[0] -= dx * distance / 1000; pan[1] += dy * distance / 1000; }
    else { yaw += dx * .007; pitch = Math.max(.04, Math.min(1.5, pitch + dy * .007)); } render();
  };
  canvas.onpointerup = canvas.onpointercancel = function () { drag = null; };
  canvas.addEventListener('wheel', function (event) { event.preventDefault(); distance = Math.max(radius * .1, Math.min(radius * 20, distance * (event.deltaY > 0 ? 1.12 : .89))); render(); }, { passive: false });
  window.addEventListener('resize', render);
  var api = { load: load, render: render, reset: reset, clear: clear, wireframe: false };
  window.OpenMapViewer = api;
}());
