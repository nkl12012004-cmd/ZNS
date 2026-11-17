"""Bounded, optional OpenStreetMap tree data for the original model pipeline.

The original MVT fast path has no individual tree nodes. This independent
query supplements it without changing the recovered kernel or its geometry.
All feature coordinates use latitude, longitude order.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time

import certifi
import requests

from .net import PublicError


OVERPASS_ENDPOINTS = (
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)
MAX_RESPONSE_BYTES = 1_048_576
MAX_POINTS = 12_000
MAX_AREAS = 256
MAX_RING_POINTS = 2_000
MAX_TOTAL_AREA_POINTS = 12_000
CACHE_TTL_SECONDS = 24 * 60 * 60
TOTAL_TIMEOUT_SECONDS = 16
SOURCE = "OpenStreetMap / Overpass"


class _Unavailable(ValueError):
    pass


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise PublicError("Đã hủy tác vụ.")


def _finite(value, low, high):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and low <= value <= high)


def _bbox(value):
    if not isinstance(value, dict):
        raise PublicError("Vùng lấy dữ liệu cây không hợp lệ.")
    result={key:value.get(key) for key in ("south", "west", "north", "east")}
    if (not all(_finite(result[key], -80, 80) for key in ("south", "north"))
            or not all(_finite(result[key], -180, 180) for key in ("west", "east"))
            or not result["south"] < result["north"]
            or not result["west"] < result["east"]
            or result["north"]-result["south"] > 10
            or result["east"]-result["west"] > 10):
        raise PublicError("Vùng lấy dữ liệu cây không hợp lệ.")
    return {key:float(number) for key,number in result.items()}


def _height(value):
    if isinstance(value, str):
        match=re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(?:m|met(?:er|re)s?)?\s*",value,re.I)
        if not match:return None
        value=float(match[1].replace(",", "."))
    return float(value) if _finite(value,1,35) else None


def _identifier(value):
    if isinstance(value,int) and not isinstance(value,bool) and 0 < value < 2**63:
        return value
    return None


def _point(value,bbox):
    if not isinstance(value,dict):return None
    lat,lon=value.get("lat"),value.get("lon")
    if (not _finite(lat,-80,80) or not _finite(lon,-180,180)
            or not bbox["south"] <= lat <= bbox["north"]
            or not bbox["west"] <= lon <= bbox["east"]):return None
    result={"lat":float(lat),"lon":float(lon)}
    height=_height(value.get("height"))
    if height is not None:result["height"]=height
    identifier=_identifier(value.get("id"))
    if identifier is not None:result["id"]=identifier
    return result


def _area(value,bbox,cancel):
    if not isinstance(value,dict):return None
    kind=value.get("kind")
    coordinates=value.get("coordinates")
    if kind not in ("wood", "forest", "park", "tree_row"):
        return None
    if not isinstance(coordinates,list) or not 2 <= len(coordinates) <= MAX_RING_POINTS:
        return None
    result=[]
    for index,coordinate in enumerate(coordinates):
        if index % 64 == 0:_check_cancel(cancel)
        if (not isinstance(coordinate,(list,tuple)) or len(coordinate) != 2
                or not _finite(coordinate[0],-80,80) or not _finite(coordinate[1],-180,180)):
            return None
        pair=[float(coordinate[0]),float(coordinate[1])]
        if not result or pair != result[-1]:result.append(pair)
    unique=len({tuple(pair) for pair in result})
    if unique < (2 if kind == "tree_row" else 3):return None
    lats,lons=zip(*result)
    south,north,west,east=min(lats),max(lats),min(lons),max(lons)
    if (north-south > 10 or east-west > 10 or north < bbox["south"]
            or south > bbox["north"] or east < bbox["west"] or west > bbox["east"]):
        return None
    if kind != "tree_row" and result[-1] != result[0]:
        if len(result) == MAX_RING_POINTS:return None
        result.append(result[0][:])
    return {"kind":kind,"coordinates":result}


def _clean_features(points,areas,bbox,cancel):
    result_points,result_areas=[],[]
    positions,identifiers,seen_areas=set(),set(),set()
    for index,value in enumerate(points):
        if index % 64 == 0:_check_cancel(cancel)
        point=_point(value,bbox)
        if point is None:continue
        position=(round(point["lat"],7),round(point["lon"],7))
        identifier=point.get("id")
        if position in positions or identifier is not None and identifier in identifiers:
            continue
        positions.add(position)
        if identifier is not None:identifiers.add(identifier)
        result_points.append(point)
        if len(result_points) >= MAX_POINTS:break
    total_coordinates=0
    for index,value in enumerate(areas):
        if index % 16 == 0:_check_cancel(cancel)
        area=_area(value,bbox,cancel)
        if area is None:continue
        signature=(area["kind"],tuple(tuple(pair) for pair in area["coordinates"]))
        if signature in seen_areas:continue
        if total_coordinates+len(area["coordinates"]) > MAX_TOTAL_AREA_POINTS:continue
        seen_areas.add(signature)
        result_areas.append(area)
        total_coordinates+=len(area["coordinates"])
        if len(result_areas) >= MAX_AREAS:break
    _check_cancel(cancel)
    return {"points":result_points,"areas":result_areas}


def _parse_document(payload,bbox,cancel):
    document=json.loads(payload)
    if (not isinstance(document,dict) or not isinstance(document.get("elements"),list)
            or "remark" in document):
        raise _Unavailable("Invalid Overpass document")
    points,areas=[],[]
    for index,element in enumerate(document["elements"]):
        if index % 64 == 0:_check_cancel(cancel)
        if not isinstance(element,dict):continue
        tags=element.get("tags")
        if not isinstance(tags,dict):continue
        if element.get("type") == "node" and tags.get("natural") == "tree":
            points.append({"lat":element.get("lat"),"lon":element.get("lon"),
                           "id":element.get("id"),"height":tags.get("height")})
        elif element.get("type") == "way":
            if tags.get("natural") == "tree_row":kind="tree_row"
            elif tags.get("natural") == "wood":kind="wood"
            elif tags.get("landuse") == "forest":kind="forest"
            elif tags.get("leisure") in ("park", "garden"):kind="park"
            else:continue
            geometry=element.get("geometry")
            if not isinstance(geometry,list) or len(geometry) > MAX_RING_POINTS:continue
            areas.append({"kind":kind,"coordinates":[[point.get("lat"),point.get("lon")]
                         if isinstance(point,dict) else None for point in geometry]})
    return _clean_features(points,areas,bbox,cancel)


def _cache_path(cache_dir,bbox):
    key=json.dumps([1,bbox],sort_keys=True,separators=(",", ":"),allow_nan=False)
    digest=hashlib.sha256(key.encode()).hexdigest()
    return Path(cache_dir)/"tree_features"/("trees_v1_"+digest+".json")


def _read_cache(path,bbox,cancel):
    _check_cancel(cancel)
    try:
        if path.stat().st_size > MAX_RESPONSE_BYTES:return None
        with path.open("rb") as target:payload=target.read(MAX_RESPONSE_BYTES+1)
        if len(payload) > MAX_RESPONSE_BYTES:return None
        document=json.loads(payload)
        if (not isinstance(document,dict) or document.get("version") != 1
                or document.get("bbox") != bbox or document.get("source") not in OVERPASS_ENDPOINTS
                or not _finite(document.get("fetched_at"),0,time.time())
                or time.time()-document["fetched_at"] > CACHE_TTL_SECONDS
                or not isinstance(document.get("points"),list)
                or not isinstance(document.get("areas"),list)):
            return None
        cleaned=_clean_features(document["points"],document["areas"],bbox,cancel)
        # Treat modified/invalid cache records as misses, not false empty data.
        if cleaned["points"] != document["points"] or cleaned["areas"] != document["areas"]:
            return None
        return {**cleaned,"status":"cache","source":document["source"]}
    except (OSError,ValueError,UnicodeError,RecursionError):
        return None


def _write_cache(path,bbox,result,cancel):
    _check_cancel(cancel)
    temporary=None
    try:
        payload=json.dumps({"version":1,"bbox":bbox,"fetched_at":time.time(),
                            "points":result["points"],"areas":result["areas"],"source":result["source"]},
                           ensure_ascii=False,separators=(",", ":"),allow_nan=False).encode()
        if len(payload) > MAX_RESPONSE_BYTES:return
        path.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="wb",prefix=path.stem+"_",suffix=".tmp",
                                         dir=path.parent,delete=False) as target:
            temporary=Path(target.name)
            target.write(payload)
        _check_cancel(cancel)
        os.replace(temporary,path)
    except (OSError,ValueError):
        # An optional cache must not prevent an otherwise successful import.
        pass
    finally:
        if temporary is not None:
            try:temporary.unlink(missing_ok=True)
            except OSError:pass


def _query(bbox):
    bb=",".join(format(bbox[key],".8f") for key in ("south","west","north","east"))
    return ('[out:json][timeout:5];('
            'node["natural"="tree"]('+bb+');'
            'way["natural"="tree_row"]('+bb+');'
            'way["natural"="wood"]('+bb+');'
            'way["landuse"="forest"]('+bb+');'
            'way["leisure"="park"]('+bb+');'
            'way["leisure"="garden"]('+bb+'););out geom qt;')


def fetch_tree_features(bbox,cache_dir,cancel=None):
    """Fetch optional tree nodes, woodland masks and open tree-row lines.

    Provider failure is nonfatal (``status=unavailable``); valid empty responses
    are cached. Cancellation always raises PublicError. Rings may extend beyond
    bbox so the placement caller can clip a complete polygon without distortion.
    """
    _check_cancel(cancel)
    bbox=_bbox(bbox)
    path=_cache_path(cache_dir,bbox)
    cached=_read_cache(path,bbox,cancel)
    if cached is not None:return cached
    deadline=time.monotonic()+TOTAL_TIMEOUT_SECONDS
    query=_query(bbox)
    for endpoint in OVERPASS_ENDPOINTS:
        _check_cancel(cancel)
        remaining=deadline-time.monotonic()
        if remaining <= 0:break
        response=None
        try:
            response=requests.get(endpoint,params={"data":query},stream=True,allow_redirects=False,
                                  timeout=(min(3,remaining),min(5,remaining)),verify=certifi.where(),
                                  headers={"User-Agent":"SiteCraft/0.4 (OpenStreetMap tree supplement)",
                                           "Accept":"application/json","Accept-Encoding":"identity"})
            _check_cancel(cancel)
            if time.monotonic() >= deadline:raise _Unavailable("Tree request time budget exceeded")
            if response.status_code != 200:continue
            declared=response.headers.get("Content-Length","")
            if str(declared).isdigit() and int(declared) > MAX_RESPONSE_BYTES:
                raise _Unavailable("Oversized tree response")
            payload=bytearray()
            # A single-byte streaming read returns control even when a provider
            # trickles data too slowly to fill an ordinary 8KB chunk. This keeps
            # cancellation and the overall budget observable between reads.
            for chunk in response.iter_content(chunk_size=1):
                _check_cancel(cancel)
                if time.monotonic() >= deadline:raise _Unavailable("Tree request time budget exceeded")
                if not chunk:continue
                if len(payload)+len(chunk) > MAX_RESPONSE_BYTES:raise _Unavailable("Oversized tree response")
                payload.extend(chunk)
            _check_cancel(cancel)
            features=_parse_document(payload,bbox,cancel)
            result={**features,"status":"ok" if features["points"] or features["areas"] else "empty",
                    "source":endpoint}
            _write_cache(path,bbox,result,cancel)
            return result
        except (requests.RequestException,OSError,ValueError,UnicodeError,RecursionError):
            continue
        finally:
            if response is not None:
                try:response.close()
                except (requests.RequestException,OSError):pass
    _check_cancel(cancel)
    return {"points":[],"areas":[],"status":"unavailable","source":SOURCE}
