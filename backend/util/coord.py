"""坐标系转换工具

CGCS2000 ↔ WGS84 ↔ GCJ02 之间的转换。纯函数，不碰网络。"""

import math
from pyproj import Transformer

# CGCS2000 ↔ WGS84
_cgcs2wgs = Transformer.from_crs("EPSG:4490", "EPSG:4326", always_xy=True)
_wgs2cgcs = Transformer.from_crs("EPSG:4326", "EPSG:4490", always_xy=True)

# 中国边界（GCJ02 偏移算法使用）
GCJ_LON_MIN, GCJ_LON_MAX = 73.66, 135.05
GCJ_LAT_MIN, GCJ_LAT_MAX = 18.15, 53.55

# GCJ02 椭球参数
PI = math.pi
A = 6378245.0
EE = 0.00669342162296594323


def _out_of_china(lon: float, lat: float) -> bool:
    return not (GCJ_LON_MIN < lon < GCJ_LON_MAX and GCJ_LAT_MIN < lat < GCJ_LAT_MAX)


def _transform_lat(lon: float, lat: float) -> float:
    ret = -100.0 + 2.0 * lon + 3.0 * lat + 0.2 * lat * lat + 0.1 * lon * lat + 0.2 * math.sqrt(abs(lon))
    ret += (20.0 * math.sin(6.0 * lon * PI) + 20.0 * math.sin(2.0 * lon * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * PI) + 40.0 * math.sin(lat / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * PI) + 320.0 * math.sin(lat * PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(lon: float, lat: float) -> float:
    ret = 300.0 + lon + 2.0 * lat + 0.1 * lon * lon + 0.1 * lon * lat + 0.1 * math.sqrt(abs(lon))
    ret += (20.0 * math.sin(6.0 * lon * PI) + 20.0 * math.sin(2.0 * lon * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lon * PI) + 40.0 * math.sin(lon / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lon / 12.0 * PI) + 300.0 * math.sin(lon / 30.0 * PI)) * 2.0 / 3.0
    return ret


def cgcs2000_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
    """CGCS2000 → WGS84"""
    return _cgcs2wgs.transform(lon, lat)


def wgs84_to_cgcs2000(lon: float, lat: float) -> tuple[float, float]:
    """WGS84 → CGCS2000"""
    return _wgs2cgcs.transform(lon, lat)


def wgs84_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    """WGS84 → GCJ02"""
    if _out_of_china(lon, lat):
        return round(lon, 6), round(lat, 6)
    d_lon = _transform_lon(lon - 105.0, lat - 35.0)
    d_lat = _transform_lat(lon - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * PI
    magic = math.sin(rad_lat)
    magic = 1 - EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((A * (1 - EE)) / (magic * sqrt_magic) * PI)
    d_lon = (d_lon * 180.0) / (A / sqrt_magic * math.cos(rad_lat) * PI)
    return lon + d_lon, lat + d_lat


def gcj02_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
    """GCJ02 → WGS84"""
    if _out_of_china(lon, lat):
        return round(lon, 6), round(lat, 6)
    d_lon = _transform_lon(lon - 105.0, lat - 35.0)
    d_lat = _transform_lat(lon - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * PI
    magic = math.sin(rad_lat)
    magic = 1 - EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((A * (1 - EE)) / (magic * sqrt_magic) * PI)
    d_lon = (d_lon * 180.0) / (A / sqrt_magic * math.cos(rad_lat) * PI)
    mg_lon = lon + d_lon
    mg_lat = lat + d_lat
    return lon * 2 - mg_lon, lat * 2 - mg_lat


def cgcs2000_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    """CGCS2000 → GCJ02（天地图坐标转高德坐标）"""
    w_lon, w_lat = cgcs2000_to_wgs84(lon, lat)
    return wgs84_to_gcj02(w_lon, w_lat)


def gcj02_to_cgcs2000(lon: float, lat: float) -> tuple[float, float]:
    """GCJ02 → CGCS2000（高德坐标转天地图坐标）"""
    w_lon, w_lat = gcj02_to_wgs84(lon, lat)
    return wgs84_to_cgcs2000(w_lon, w_lat)
