"""Editable recovery of the six original MapSKP coordinate/OCR functions.

Recovered locally from the user-provided original. Original rights apply.
No opaque code objects or marshal loader are used in this source.
"""
from __future__ import annotations
import base64
import io
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image, ImageOps

_PS_OCR_TEMPLATE = r"""
$ErrorActionPreference = 'Stop'
try {
  [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime] | Out-Null
  [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] | Out-Null
  [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType=WindowsRuntime] | Out-Null
  [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime] | Out-Null
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
  })[0]
  function Await($op, $rt) {
    $m = $asTaskGeneric.MakeGenericMethod($rt)
    $t = $m.Invoke($null, @($op))
    $t.Wait(-1) | Out-Null
    return $t.Result
  }
  $imgPath = '__IMG_PATH__'
  $outPath = '__OUT_PATH__'
  $sf = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($imgPath)) ([Windows.Storage.StorageFile])
  $st = Await ($sf.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($st)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $eng = $null
  try { $eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('en-US')) } catch {}
  if (-not $eng) { $eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
  if (-not $eng) { throw 'Windows chua cai goi ngon ngu OCR' }
  $res = Await ($eng.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
  $lines = @()
  foreach ($ln in $res.Lines) {
    $lines += $ln.Text
  }
  $payload = @{ ok = $true; text = ($res.Text); lines = $lines } | ConvertTo-Json -Depth 4 -Compress
} catch {
  $payload = @{ ok = $false; error = ('' + $_.Exception.Message) } | ConvertTo-Json -Compress
}
[IO.File]::WriteAllText($outPath, $payload, (New-Object Text.UTF8Encoding $false))
"""

URL_PIN_PATTERN = '!3d([+-]?\\d{1,2}(?:\\.\\d+)?)!4d([+-]?\\d{1,3}(?:\\.\\d+)?)'
URL_QUERY_PATTERN = '[?&](?:q|query|ll|sll|destination|center|viewpoint)=(?:loc:)?\\s*([+-]?\\d{1,3}(?:\\.\\d+)?)\\s*[,;\\s+]+\\s*([+-]?\\d{1,3}(?:\\.\\d+)?)'
URL_PATH_PATTERN = '/(?:search|place|dir)/([+-]?\\d{1,2}(?:\\.\\d+)?)\\s*[,+]+\\s*([+-]?\\d{1,3}(?:\\.\\d+)?)'
URL_CENTER_PATTERN = '@([+-]?\\d{1,2}(?:\\.\\d+)?),([+-]?\\d{1,3}(?:\\.\\d+)?)'
DMS_SUFFIX_PATTERN = '(\\d{1,3})\\s*[°ºo]\\s*(\\d{1,2})\\s*[\'’′]\\s*(\\d{1,2}(?:[.,]\\d+)?)\\s*[\\"”″]?\\s*([NSBnsb])[\\s,;:/|-]+(\\d{1,3})\\s*[°ºo]\\s*(\\d{1,2})\\s*[\'’′]\\s*(\\d{1,2}(?:[.,]\\d+)?)\\s*[\\"”″]?\\s*([EWDĐTWewdđtw])'
DMS_PREFIX_PATTERN = '([NSBnsb])\\s*(\\d{1,2})\\s*[°ºo]\\s*(\\d{1,2})\\s*[\'’′]\\s*(\\d{1,2}(?:[.,]\\d+)?)\\s*[\\"”″]?[\\s,;:/|-]+([EWDĐTWewdđtw])\\s*(\\d{1,3})\\s*[°ºo]\\s*(\\d{1,2})\\s*[\'’′]\\s*(\\d{1,2}(?:[.,]\\d+)?)\\s*[\\"”″]?'
DECIMAL_PATTERN = '([+-]?\\d{1,3}\\.\\d{3,12})\\s*[°º]?\\s*([NSns])?\\s*[,;/|\\s]+\\s*([+-]?\\d{1,3}\\.\\d{3,12})\\s*[°º]?\\s*([EWew])?'
COORD_LABEL_PATTERN = '(?i)\\b(?:lat(?:itude)?|lon(?:gitude)?|lng|vĩ\\s*độ|kinh\\s*độ|tọa\\s*độ|coords?)\\s*[:=]?\\s*'
DIRECT_PAIR_PATTERN = '^([+-]?\\d{1,3}(?:\\.\\d{1,12})?)\\s*[°º]?\\s*([NSBnsb])?\\s*(?:[,;/|]+|\\s+)\\s*([+-]?\\d{1,3}(?:\\.\\d{1,12})?)\\s*[°º]?\\s*([EWDĐTWewdđtw])?$'

NO_COORDINATE_ERROR = 'Không tìm thấy dòng tọa độ (ví dụ \'21.0285, 105.8544\' hoặc \'21°01\'42"N 105°51\'16"E\') trong ảnh.'


def _valid_lat_lon(lat: float, lon: float) -> bool:
    return -85.05113 <= lat <= 85.05113 and -180.0 <= lon <= 180.0


def _parse_google_maps_url_coords(raw_url: str) -> Optional[Tuple[float, float, str]]:
    if not raw_url:
        return None
    unquoted = urllib.parse.unquote(raw_url.strip())
    pin_matches = list(re.finditer(URL_PIN_PATTERN, unquoted))
    if pin_matches:
        m_last = pin_matches[-1]
        lat, lon = float(m_last.group(1)), float(m_last.group(2))
        if _valid_lat_lon(lat, lon):
            return round(lat, 7), round(lon, 7), f'Ghim Google Maps ({lat:.6f}, {lon:.6f})'
    q_match = re.search(URL_QUERY_PATTERN, unquoted, flags=re.IGNORECASE)
    if q_match:
        v1, v2 = float(q_match.group(1)), float(q_match.group(2))
        if _valid_lat_lon(v1, v2):
            return round(v1, 7), round(v2, 7), f'Link Google Maps ({v1:.6f}, {v2:.6f})'
    p_match = re.search(URL_PATH_PATTERN, unquoted, flags=re.IGNORECASE)
    if p_match:
        lat, lon = float(p_match.group(1)), float(p_match.group(2))
        if _valid_lat_lon(lat, lon):
            return round(lat, 7), round(lon, 7), f'Link Google Maps ({lat:.6f}, {lon:.6f})'
    at_match = re.search(URL_CENTER_PATTERN, unquoted)
    if at_match:
        lat, lon = float(at_match.group(1)), float(at_match.group(2))
        if _valid_lat_lon(lat, lon):
            return round(lat, 7), round(lon, 7), f'Tâm Google Maps ({lat:.6f}, {lon:.6f})'
    return None


def parse_coordinates_from_text(text: str) -> Optional[Tuple[float, float, str]]:
    if not text:
        return None
    if 'google.' in text.lower() or '!3d' in text or '/@' in text:
        url_hit = _parse_google_maps_url_coords(text)
        if url_hit:
            return url_hit
    cleaned = text.replace('—', '-').replace('–', '-').replace('−', '-')
    ocr_norm = cleaned.replace('O', '0')
    dms_pat = re.compile(DMS_SUFFIX_PATTERN)
    m_dms = dms_pat.search(ocr_norm)
    if m_dms:
        d1, m1, s1, h1, d2, m2, s2, h2 = m_dms.groups()
        lat = float(d1) + float(m1) / 60.0 + float(s1.replace(',', '.')) / 3600.0
        lon = float(d2) + float(m2) / 60.0 + float(s2.replace(',', '.')) / 3600.0
        if h1.upper() == 'S':
            lat = -lat
        if h2.upper() in ('W', 'T'):
            lon = -lon
        if _valid_lat_lon(lat, lon):
            return round(lat, 7), round(lon, 7), m_dms.group(0).strip()
    dms_pre_pat = re.compile(DMS_PREFIX_PATTERN)
    m_pre = dms_pre_pat.search(ocr_norm)
    if m_pre:
        h1, d1, m1, s1, h2, d2, m2, s2 = m_pre.groups()
        lat = float(d1) + float(m1) / 60.0 + float(s1.replace(',', '.')) / 3600.0
        lon = float(d2) + float(m2) / 60.0 + float(s2.replace(',', '.')) / 3600.0
        if h1.upper() == 'S':
            lat = -lat
        if h2.upper() in ('W', 'T'):
            lon = -lon
        if _valid_lat_lon(lat, lon):
            return round(lat, 7), round(lon, 7), m_pre.group(0).strip()
    dec_pat = re.compile(DECIMAL_PATTERN)
    for m in dec_pat.finditer(cleaned):
        v1_s, h1_s, v2_s, h2_s = m.groups()
        lat, lon = float(v1_s), float(v2_s)
        if h1_s and h1_s.upper() == 'S':
            lat = -abs(lat)
        if h2_s and h2_s.upper() == 'W':
            lon = -abs(lon)
        if _valid_lat_lon(lat, lon):
            return round(lat, 7), round(lon, 7), m.group(0).strip()
        if not h1_s and not h2_s and abs(lat) > 90.0 and _valid_lat_lon(lon, lat):
            return round(lon, 7), round(lat, 7), f'{lon:.6f}, {lat:.6f} (đảo từ CAD)'
    return None


def parse_direct_search_coordinates(query: str) -> Optional[Tuple[float, float, str]]:
    q = (query or '').strip()
    if not q:
        return None
    url_hit = _parse_google_maps_url_coords(q)
    if url_hit:
        return url_hit
    std_hit = parse_coordinates_from_text(q)
    if std_hit:
        return std_hit
    stripped = re.sub(COORD_LABEL_PATTERN, ' ', q)
    stripped = stripped.strip().strip('()[]{}').strip()
    stripped = stripped.replace('—', '-').replace('–', '-').replace('−', '-')
    m_pair = re.match(DIRECT_PAIR_PATTERN, stripped)
    if m_pair:
        v1_s, h1_s, v2_s, h2_s = m_pair.groups()
        if '.' not in v1_s and '.' not in v2_s and not h1_s and not h2_s and '°' not in q:
            return None
        v1, v2 = float(v1_s), float(v2_s)
        if h1_s and h1_s.upper() == 'S':
            v1 = -abs(v1)
        if h2_s and h2_s.upper() in ('W', 'T'):
            v2 = -abs(v2)
        if _valid_lat_lon(v1, v2):
            return round(v1, 7), round(v2, 7), f'{v1:.6f}, {v2:.6f}'
        if not h1_s and not h2_s and abs(v1) > 90.0 and _valid_lat_lon(v2, v1):
            return round(v2, 7), round(v1, 7), f'{v2:.6f}, {v1:.6f} (đảo Kinh/Vĩ)'
    return None


def _run_windows_ocr_on_file(img_path: Path, out_json: Path) -> Dict[str, Any]:
    ps_script = _PS_OCR_TEMPLATE.replace('__IMG_PATH__', str(img_path).replace("'", "''")).replace(
        '__OUT_PATH__', str(out_json).replace("'", "''"))
    enc = base64.b64encode(ps_script.encode('utf-16-le')).decode('ascii')
    ps_exe = os.path.join(os.environ.get('SystemRoot', 'C:\\Windows'), 'System32',
                          'WindowsPowerShell', 'v1.0', 'powershell.exe')
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    subprocess.run([ps_exe, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                    '-EncodedCommand', enc], capture_output=True, timeout=25, creationflags=flags)
    if out_json.exists():
        return json.loads(out_json.read_text(encoding='utf-8'))
    return {'ok': False, 'error': 'Windows OCR không tạo được file kết quả'}


def extract_coords_from_image_b64(image_b64: str) -> Dict[str, Any]:
    if not image_b64:
        return {'ok': False, 'error': 'Chưa có dữ liệu ảnh'}
    raw_str = image_b64.split(',', 1)[-1].strip()
    img_bytes = base64.b64decode(raw_str)
    stamp = f'{os.getpid()}_{int(time.time() * 1000)}'
    tmp_dir = Path(tempfile.gettempdir())
    p_orig = tmp_dir / f'mapskp_ocr_raw_{stamp}.png'
    p_hi = tmp_dir / f'mapskp_ocr_hi_{stamp}.png'
    p_json = tmp_dir / f'mapskp_ocr_out_{stamp}.json'
    try:
        im = Image.open(io.BytesIO(img_bytes)).convert('RGB')
        w, h = im.size
        scale = 2 if max(w, h) < 1600 else 1
        if scale > 1:
            im_up = im.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
        else:
            im_up = im
        im_up.save(p_orig, format='PNG')
        res1 = _run_windows_ocr_on_file(p_orig, p_json)
        lines_all = list(res1.get('lines') or [])
        joined_1 = '\n'.join(lines_all) + '\n' + str(res1.get('text') or '')
        found = parse_coordinates_from_text(joined_1)
        if found:
            return {'ok': True, 'lat': found[0], 'lon': found[1], 'matched_text': found[2], 'lines': lines_all[:12]}
        gray = ImageOps.grayscale(im_up)
        bw = gray.point(lambda px: 0 if px >= 185 else 255)
        bw.save(p_hi, format='PNG')
        if p_json.exists():
            p_json.unlink()
        res2 = _run_windows_ocr_on_file(p_hi, p_json)
        lines_2 = list(res2.get('lines') or [])
        joined_2 = '\n'.join(lines_2) + '\n' + str(res2.get('text') or '')
        found2 = parse_coordinates_from_text(joined_2)
        if found2:
            return {'ok': True, 'lat': found2[0], 'lon': found2[1], 'matched_text': found2[2],
                    'lines': (lines_all + lines_2)[:12]}
        return {'ok': False, 'error': NO_COORDINATE_ERROR, 'lines': (lines_all + lines_2)[:10]}
    except Exception as exc:
        return {'ok': False, 'error': f'Lỗi OCR: {exc}'}
    finally:
        for p in (p_orig, p_hi, p_json):
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
