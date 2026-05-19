"""纯函数测试：coord.py 坐标转换精度验证。

高德返回的 location 是 GCJ02，天地图坐标是 CGCS2000，
统一转到 WGS84 后对比。不依赖任何 API 调用。
"""

from backend.util.coord import cgcs2000_to_wgs84, gcj02_to_wgs84
from geopy.distance import geodesic

# 高德名称搜索返回的 GCJ02 location
AMAP = {
    "人民英雄纪念碑": (116.397691, 39.904632),
    "雨花台烈士纪念馆": (118.780429, 31.997211),
    "鸠顶泽瑞": (118.372894, 31.330648),
}

# 天地图 WFS 返回的 lonlat（CGCS2000）
TDT = {
    "人民英雄纪念碑": (116.39143967261776, 39.9031982132266),
    "雨花台烈士纪念馆": (118.77522752633945, 31.999161861149673),
    "鸠顶泽瑞": (118.36750213714333, 31.33247873565267),
}


def test_cgcs2wgs():
    """CGCS2000 → WGS84 往返精度"""
    print("=== CGCS2000 → WGS84 往返精度 ===")
    for lon, lat in [(100.0, 20.0), (116.39, 30.0), (120.5, 35.0), (129.5, 50.0)]:
        wgs = cgcs2000_to_wgs84(lon, lat)
        back = cgcs2000_to_wgs84(*wgs)
        diff = geodesic((lat, lon), (back[1], back[0])).meters
        print(f"  ({lon}, {lat}) → {wgs} → back {back} diff={diff:.3f}m")


def test_amap_vs_tdt():
    """高德 GCJ02 → WGS84 vs 天地图 CGCS2000 → WGS84"""
    print("\n=== 高德 vs 天地图 统一转 WGS84 ===")
    for name in AMAP:
        amap_wgs = gcj02_to_wgs84(*AMAP[name])
        td_wgs = cgcs2000_to_wgs84(*TDT[name])
        diff = geodesic((amap_wgs[1], amap_wgs[0]), (td_wgs[1], td_wgs[0])).meters
        print(f"  {name}")
        print(f"    高德 GCJ02 → WGS84:       ({amap_wgs[0]:.8f}, {amap_wgs[1]:.8f})")
        print(f"    天地图 CGCS2000 → WGS84:  ({td_wgs[0]:.8f}, {td_wgs[1]:.8f})")
        print(f"    偏差: {diff:.1f}m")


if __name__ == "__main__":
    test_cgcs2wgs()
    test_amap_vs_tdt()
