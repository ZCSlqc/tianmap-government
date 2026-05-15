"""天地图分享数据 → SQLite 入库

用法：修改 UUID 变量，直接运行 python3 backend/main.py"""

import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

# 统一日志
from backend.util import logger
logger.info("[main] 启动天地图数据入库")

import asyncio
import json
import sqlite3
from datetime import datetime

import aiohttp

from backend.util import parse_address

# ==================== 配置 ====================
UUID = "f6756cd4aff441528f72e2d3252f1eb4"  # <-- 改这里
TIANDITU_API = "https://map.tianditu.gov.cn/api/map/share"
DB_PATH = Path(__file__).parent.parent / "data" / "tianmap.db"


def _safe_float(val: str) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(val: str) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return 30


async def main() -> dict:
    stats = {"success": 0, "error": 0}

    # ---- 1. 下载 JSON ----
    logger.info("[下载] 从天地图获取分享数据")
    url = f"{TIANDITU_API}/{UUID}"
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                resp.raise_for_status()
                raw_data = await resp.json()
    except asyncio.TimeoutError:
        logger.error("[下载] 请求超时")
        return stats
    except aiohttp.ClientError as e:
        logger.error(f"[下载] 请求失败: {e}")
        return stats
    except json.JSONDecodeError as e:
        logger.error(f"[下载] JSON 解析失败: {e}")
        return stats

    # 解包双层 JSON
    data_str = raw_data.get("data", "")
    if isinstance(data_str, str):
        inner = json.loads(data_str)
    else:
        inner = data_str
    draw_info = inner.get("drawInfo", inner)
    points = draw_info.get("points", {})
    logger.info(f"[下载] 获取 {len(points)} 个点")

    # ---- 1.5. 保存原始 JSON ----
    tmp_dir = Path(__file__).parent.parent / "tmp" / "raw_url"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = tmp_dir / f"{ts}_{UUID}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(draw_info, f, ensure_ascii=False, indent=2)
    logger.info(f"[保存] JSON 已保存: {json_path}")

    # ---- 2. 建表 ----
    logger.info("[建表] 创建 poi_points 表")
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DROP TABLE IF EXISTS poi_points")
    conn.execute(
        "CREATE TABLE poi_points ("
        "id TEXT PRIMARY KEY, "
        "name TEXT DEFAULT '', address TEXT DEFAULT '', "
        "province TEXT DEFAULT '', city TEXT DEFAULT '', district TEXT DEFAULT '', township TEXT DEFAULT '', "
        "lon REAL DEFAULT 0.0, lat REAL DEFAULT 0.0, "
        "color TEXT DEFAULT 'rgb(255,0,0)', code TEXT DEFAULT '100000', "
        "size INTEGER DEFAULT 30, remark TEXT DEFAULT '', "
        "name_checked INTEGER DEFAULT 0, "
        "affiliation TEXT DEFAULT '', point_type TEXT DEFAULT '', "
        "level TEXT DEFAULT '', feature TEXT DEFAULT '', "
        "parent_company TEXT DEFAULT '', constructor TEXT DEFAULT '', "
        "amap_id TEXT DEFAULT '', amap_name TEXT DEFAULT '', amap_address TEXT DEFAULT '', "
        "amap_area TEXT DEFAULT '', amap_type TEXT DEFAULT '', "
        "amap_distance REAL DEFAULT 0.0, amap_businessarea TEXT DEFAULT '', "
        "cgcs_lon REAL DEFAULT 0.0, cgcs_lat REAL DEFAULT 0.0, "
        "amap_lon REAL DEFAULT 0.0, amap_lat REAL DEFAULT 0.0, "
        "img_url TEXT DEFAULT '', record TEXT DEFAULT '', "
        "created_at TEXT, updated_at TEXT)"
    )
    conn.commit()

    # ---- 3. 入库 ----
    now = datetime.now().isoformat()
    INSERT = (
        "INSERT OR REPLACE INTO poi_points "
        "(id,name,address,province,city,district,township,lon,lat,color,code,size,remark,name_checked,"
        "affiliation,point_type,level,feature,parent_company,constructor,"
        "amap_id,amap_name,amap_address,amap_area,amap_type,amap_distance,amap_businessarea,cgcs_lon,cgcs_lat,amap_lon,amap_lat,"
        "img_url,record,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )

    for fid, item in points.items():
        try:
            info = item.get("featureInfo", {})
            if not isinstance(info, dict):
                continue
            name = info.get("name", "").strip()
            if not name:
                continue

            address = info.get("address", "").strip()
            lonlat = info.get("lonlat", "")
            style = info.get("style", {})
            remark = info.get("remark", "") or ""

            lon = _safe_float(lonlat.split(" ")[0]) if lonlat and " " in lonlat else 0.0
            lat = _safe_float(lonlat.split(" ")[1]) if lonlat and " " in lonlat else 0.0
            code = style.get("code", "100000")
            color = style.get("color", "rgb(255,0,0)")
            size = _safe_int(style.get("size", 30))
            nc = 1 if style.get("nameChecked", False) else 0

            addr_info = parse_address(address)
            province = addr_info["province"] if addr_info else ""
            city = addr_info["city"] if addr_info else ""
            district = addr_info["district"] if addr_info else ""
            township = addr_info["town"] if addr_info else ""

            conn.execute(INSERT, (
                fid, name, address, province, city, district, township,
                lon, lat, color, code, size, remark, nc,
                "", "", "", "", "", "", "",
                "", "", "", "", 0.0, "", 0.0, 0.0, 0.0, 0.0,
                "", "", now, now
            ))
            stats["success"] += 1
            logger.debug(f"[入库] {name}")
        except Exception as e:
            stats["error"] += 1
            logger.error(f"[入库失败] id={fid} name={info.get('name', '')} error={e}")

    conn.commit()
    conn.close()
    logger.info(f"[入库] 成功={stats['success']}, 失败={stats['error']}")

    # ---- 4. 验证 ----
    conn = sqlite3.connect(str(DB_PATH))
    total = conn.execute("SELECT COUNT(*) FROM poi_points").fetchone()[0]
    logger.info(f"[验证] 数据库总记录数: {total}")
    rows = conn.execute(
        "SELECT id[:8], name, province, city, district, color[:12], code, name_checked, "
        "affiliation, point_type "
        "FROM poi_points ORDER BY id LIMIT 10"
    ).fetchall()
    for r in rows:
        aff = r[8][:10] if r[8] else ""
        ptype = r[9][:10] if r[9] else ""
        logger.debug(f"  {r[0]}.. | {r[1][:15]:15s} | {r[2]}/{r[3]}/{r[4]:10s} | {r[5]} aff={aff} pt={ptype}")
    conn.close()

    return stats


if __name__ == "__main__":
    stats = asyncio.run(main())
