"""天地图 CGCS2000 坐标 → 高德 API 集成

坐标转换链：CGCS2000 → WGS84 → GCJ02（高德）
反向链：GCJ02 → WGS84 → CGCS2000（高德返回转回）

纯 API 调用模块，坐标转换依赖 backend.util.coord 纯函数。"""

import asyncio
import json
import aiohttp
from typing import Any
from loguru import logger
from geopy.distance import geodesic

from backend.api.config import AMAP_KEY, AMAP_RADIUS, AMAP_MAX_RETRIES
from backend.util.coord import GCJ_LON_MIN, GCJ_LON_MAX, GCJ_LAT_MIN, GCJ_LAT_MAX, cgcs2000_to_gcj02, gcj02_to_cgcs2000
from backend.util.amap_codes import code_to_name

AMAP_NAME = False # 每月5000次限额很坑

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://lbs.amap.com/",
}


def _out_of_china(lon: float, lat: float) -> bool:
    return not (GCJ_LON_MIN < lon < GCJ_LON_MAX and GCJ_LAT_MIN < lat < GCJ_LAT_MAX)


def _strip_addr(formatted: str, ac: dict) -> str:
    """从 formatted_address 从头去掉省/市/区/县/街道段。"""
    for seg in (ac.get("province", ""), ac.get("city", ""), ac.get("district", ""), ac.get("township", "")):
        if seg and formatted.startswith(seg):
            formatted = formatted[len(seg):]
    return formatted.strip("/\\ -\t")


# ===================== 距离计算 =====================


def get_distance_meters(lon1: float, lat1: float, lon2: float, lat2: float) -> float | None:
    """计算两点距离（米），自动修正经纬度写反的情况。"""
    def _fix(lon: float, lat: float):
        if abs(lat) > 70 and abs(lon) < 60:
            return lat, lon
        return lon, lat

    lon1, lat1 = _fix(lon1, lat1)
    lon2, lat2 = _fix(lon2, lat2)

    if _out_of_china(lon1, lat1) or _out_of_china(lon2, lat2):
        return None
    return geodesic((lat1, lon1), (lat2, lon2)).meters


# ===================== 数据解析 =====================


def _parse_amap_item(item: dict) -> dict:
    """将高德返回的一项解析为统一结构（POI 和 AOI 通用）。"""
    loc = item.get("location", "")
    try:
        lon_a, lat_a = map(float, loc.split(","))
        # 如果传入方已提供 cgcs_lon/cgcs_lat，跳过重复转换
        if "cgcs_lon" in item and "cgcs_lat" in item:
            cgcs_lon, cgcs_lat = item["cgcs_lon"], item["cgcs_lat"]
        else:
            cgcs_lon, cgcs_lat = gcj02_to_cgcs2000(lon_a, lat_a)
    except (ValueError, TypeError):
        cgcs_lon = cgcs_lat = lon_a = lat_a = 0.0

    distance_raw = item.get("distance", 0)
    try:
        distance = round(float(distance_raw), 2)
    except (ValueError, TypeError):
        distance = 9999.0

    ba = item.get("businessarea", item.get("business", ""))
    if isinstance(ba, list):
        ba = json.dumps(ba, ensure_ascii=False) if ba else ""
    elif ba is None:
        ba = ""

    raw_type = item.get("type", "")
    type_str = raw_type
    if raw_type:
        # 含竖线 → 每项查编码表，用 | 拼接编码段
        if "|" in raw_type:
            segments = [code_to_name(p.strip()) for p in raw_type.split("|") if p.strip()]
            type_str = "|".join(segments) or raw_type
        # 纯 6 位数字 → 直接查编码表
        elif len(raw_type) == 6 and raw_type.isdigit():
            type_str = code_to_name(raw_type) or raw_type

    return {
        "amap_id": item.get("id", ""),
        "amap_name": item.get("name", ""),
        "amap_address": item.get("address", ""),
        "amap_area": item.get("area", ""),
        "amap_type": type_str,
        "amap_distance": distance,
        "amap_businessarea": ba,
        "cgcs_lon": cgcs_lon, "cgcs_lat": cgcs_lat,
        "amap_lon": lon_a, "amap_lat": lat_a,
    }


# ===================== 逆地理编码 =====================


async def _geo_to_address_once(lon: float, lat: float, radius: int | None = None) -> dict[str, Any]:
    """单次逆地理请求"""
    if radius is None:
        radius = AMAP_RADIUS
    if not AMAP_KEY:
        logger.error("[高德] AMAP_KEY 未配置")
        return {"success": False, "geo": {}, "pois": [], "aois": [], "raw": None}
    if not all([lon, lat]):
        logger.warning("[高德] 参数不完整：lon/lat 必须全部提供")
        return {"success": False, "geo": {}, "pois": [], "aois": [], "raw": None}

    try:
        gcj_lon, gcj_lat = cgcs2000_to_gcj02(lon, lat)
    except Exception as e:
        logger.error(f"[高德] 坐标转换失败: {e}")
        return {"success": False, "geo": {}, "pois": [], "aois": [], "raw": None}

    url = "https://restapi.amap.com/v3/geocode/regeo"
    params = {
        "key": AMAP_KEY,
        "location": f"{gcj_lon:.6f},{gcj_lat:.6f}",
        "radius": radius,
        "extensions": "all",
        "roadlevel": 0,
        "homeorcorp": 0,
        "output": "json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                data = await resp.json()
    except asyncio.TimeoutError:
        logger.error(f"[高德] 逆地理请求超时")
        return {"success": False, "geo": {}, "pois": [], "aois": [], "raw": None}
    except aiohttp.ClientError as e:
        logger.error(f"[高德] 逆地理请求异常: {e}")
        return {"success": False, "geo": {}, "pois": [], "aois": [], "raw": None}
    except json.JSONDecodeError as e:
        logger.error(f"[高德] 响应解析失败: {e}")
        return {"success": False, "geo": {}, "pois": [], "aois": [], "raw": None}

    if data.get("status") != "1" or data.get("infocode") != "10000":
        logger.error(f"[高德] 逆地理失败: {data.get('info')}")
        return {"success": False, "geo": {}, "pois": [], "aois": [], "raw": data}

    regeocode = data.get("regeocode", {})
    ac = regeocode.get("addressComponent", {})

    pois = [_parse_amap_item(p) for p in regeocode.get("pois", []) if p.get("location")]
    aois = [_parse_amap_item(a) for a in regeocode.get("aois", [])]
    pois.sort(key=lambda x: x["amap_distance"])
    aois.sort(key=lambda x: x["amap_distance"])

    logger.debug(f"[高德] 逆地理完成，返回 {len(pois[:5])} 个POI, {len(aois[:5])} 个AOI")
    return {
        "success": True,
        "geo":{
            "province": ac.get("province", ""),
            "city": ac.get("city", ""),
            "district": ac.get("district", ""),
            "township": ac.get("township", ""),
            "geo_detail": _strip_addr(regeocode.get("formatted_address", ""), ac),},
        "pois": pois[:5],
        "aois": aois[:5],
        "raw": data,
    }


async def geo_to_address(lon: float, lat: float, radius: int | None = None, retries: int | None = None) -> dict[str, Any]:
    """经纬度 → 逆地理编码"""
    if retries is None:
        retries = AMAP_MAX_RETRIES
    if radius is None:
        radius = AMAP_RADIUS
    for attempt in range(1, retries + 1):
        result = await _geo_to_address_once(lon, lat, radius)
        if result.get("success"):
            return result
        logger.warning(f"[高德] 逆地理第 {attempt} 次返回失败")
        if attempt < retries:
            await asyncio.sleep(0.5 * attempt)
    return {"success": False, "geo": {}, "pois": [], "aois": [], "raw": None}


# ===================== 名称搜索 =====================


async def _name_to_poi_once(name: str, city: str, ref_lon: float, ref_lat: float) -> dict[str, Any]:
    """单次名称搜索"""
    if not AMAP_KEY:
        logger.error("[高德] AMAP_KEY 未配置")
        return {"success": False, "raw": None, "pois": []}
    if not all([name, city, ref_lon, ref_lat]):
        logger.warning(f"[高德] 参数不完整: name={name} city={city}")
        return {"success": False, "raw": None, "pois": []}

    url = "https://restapi.amap.com/v5/place/text"
    params = {
        "key": AMAP_KEY,
        "keywords": name,
        "region": city,
        "city_limit": "true",
        "page_size": 20,
        "page_num": 1,
        "show_fields": "base,address,poi,type,business",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                resp.raise_for_status()
                data = await resp.json()
    except asyncio.TimeoutError:
        logger.error(f"[高德] 名称搜索请求超时")
        return {"success": False, "raw": None, "pois": []}
    except aiohttp.ClientError as e:
        logger.error(f"[高德] 名称搜索请求异常: {e}")
        return {"success": False, "raw": None, "pois": []}
    except json.JSONDecodeError as e:
        logger.error(f"[高德] 名称搜索响应解析失败: {e}")
        return {"success": False, "raw": None, "pois": []}

    if data.get("status") != "1" or data.get("infocode") != "10000":
        logger.error(f"[高德] 名称搜索失败: {data.get('info')}")
        return {"success": False, "raw": data, "pois": []}

    pois = data.get("pois", [])
    if not pois:
        logger.warning(f"[高德] 未搜索到POI: {name}")
        return {"success": True, "raw": data, "pois": []}

    parsed = []
    for poi in pois:
        location = poi.get("location", "")
        if not location or "," not in location:
            continue
        try:
            lon_amap, lat_amap = map(float, location.split(",", 1))
        except ValueError:
            continue

        cgcs_lon, cgcs_lat = gcj02_to_cgcs2000(lon_amap, lat_amap)

        distance = get_distance_meters(ref_lon, ref_lat, cgcs_lon, cgcs_lat)
        if distance is None:
            continue

        parsed.append(_parse_amap_item({
            **poi,
            "location": f"{lon_amap},{lat_amap}",
            "distance": distance,
            "cgcs_lon": cgcs_lon,
            "cgcs_lat": cgcs_lat,
        }))

    parsed.sort(key=lambda x: x["amap_distance"])
    logger.debug(f"[高德] 名称搜索完成，返回 {len(parsed[:5])} 个 POI")
    return {"success": True, "raw": data, "pois": parsed[:5]}


async def name_to_poi(name: str, city: str, ref_lon: float, ref_lat: float, retries: int | None = None) -> dict[str, Any]:
    """高德 V5 POI 搜索"""
    if retries is None:
        retries = AMAP_MAX_RETRIES
    for attempt in range(1, retries + 1):
        result = await _name_to_poi_once(name, city, ref_lon, ref_lat)
        if result.get("success"):
            return result
        logger.warning(f"[高德] 名称搜索第 {attempt} 次请求失败")
        if attempt < retries:
            await asyncio.sleep(0.5 * attempt)
    return {"success": False, "raw": None, "pois": []}


# ===================== 合并候选 =====================


async def query_candidates(name: str, lon: float, lat: float,
                           city: str,
                           radius: int | None = None,
                           retries: int | None = None) -> dict[str, Any]:
    """逆地理 + 名称搜索，并行合并去重，返回候选列表。

    Args:
        name: SPOT 名称
        lon/lat: CGCS2000 坐标
        city: 城市名
        radius: 逆地理搜索半径，默认取 config.AMAP_RADIUS
        retries: 单次查询重试次数，默认取 config.AMAP_MAX_RETRIES
    """

    geo_res = await geo_to_address(lon, lat, radius=radius, retries=retries)
    if not AMAP_NAME:
        name_res = None
    else:
        name_res = await name_to_poi(name, city, lon, lat, retries=retries)

    # 全部失败 → 快速返回空结构
    if not geo_res.get("success") and (name_res is None or not name_res.get("success")):
        logger.warning(f"[高德] 逆地理+名称搜索均无结果: {name}")
        return {"geo": {}, "candidates": []}

    if not geo_res.get("pois") and not geo_res.get("aois"):
        logger.warning(f"[高德] 逆地理未返回 pois/aois: {name}")
    
    geo = geo_res.get("geo", {})
    all_items: list[dict[str, Any]] = []
    for p in geo_res.get("pois", []):
        cp = dict(p)
        cp["source"] = "geo_poi"
        all_items.append(cp)
    for a in geo_res.get("aois", []):
        ca = dict(a)
        ca["source"] = "geo_aoi"
        all_items.append(ca)
    
    if name_res is not None:
        if not name_res.get("pois"):
            logger.warning(f"[高德] 名称搜索未返回结果: {name}")    
        for p in name_res.get("pois", []):
            cp = dict(p)
            cp["source"] = "name_poi"
            all_items.append(cp)
    else:
        logger.info(f"[高德] 名称搜索已禁用")  

    # 去重
    seen = set()
    deduped = []
    for item in all_items:
        aid = item.get("amap_id", "")
        if aid and aid in seen:
            continue
        if aid:
            seen.add(aid)
        deduped.append(item)

    # 按距离升序
    deduped.sort(key=lambda x: x.get("amap_distance", 99999))

    logger.debug(f"[高德] 候选去重后: {len(deduped)} 条")
    return {"geo": geo, "candidates": deduped[:11]}

