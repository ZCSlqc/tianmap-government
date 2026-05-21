"""天地图分享数据 → SQLite 入库

用法：修改 UUID 变量，直接运行 python3 backend/main.py

增量模式：
- id 不存在 → INSERT
- id 存在且 remark 不同 → UPDATE remark + 记录变更
- 其余跳过（保留已标注数据）
"""

import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

# 统一日志
from backend.util import logger, save_json
logger.debug("[main] 启动天地图数据入库")

import asyncio
import json
import sqlite3
from datetime import datetime

import aiohttp

from backend.util import parse_address

# ==================== 配置 ====================
# UUID = "f6756cd4aff441528f72e2d3252f1eb4"  # <-- 改这里
UUID = "c34faf791b4641a19a02104ebc7f83f4"
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
    stats = {"add": 0, "update": 0, "record": 0, "skipped": 0, "error": 0}

    # ---- 1. 下载 JSON ----
    logger.debug("[下载] 从天地图获取分享数据")
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
        try:
            inner = json.loads(data_str)
        except json.JSONDecodeError as e:
            logger.error(f"[下载] data 字段 JSON 解析失败: {e}")
            return stats
    else:
        inner = data_str
    draw_info = inner.get("drawInfo", inner)
    points = draw_info.get("points", {})
    logger.debug(f"[下载] 获取 {len(points)} 个点")

    # ---- 1.5. 保存原始 JSON ----
    await save_json(UUID, draw_info, subdir="raw_url")

    # ---- 2. 建表 ----
    logger.debug("[建表] 确保 poi_points 表存在")
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS poi_points ("
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
        "INSERT INTO poi_points "
        "(id,name,address,province,city,district,township,lon,lat,color,code,size,remark,name_checked,"
        "affiliation,point_type,level,feature,parent_company,constructor,"
        "amap_id,amap_name,amap_address,amap_area,amap_type,amap_distance,amap_businessarea,cgcs_lon,cgcs_lat,amap_lon,amap_lat,"
        "img_url,record,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )
    UPDATE_REMARK = "UPDATE poi_points SET remark=?, updated_at=? WHERE id=?"

    # 变更日志收集
    changes = []

    info = None
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

            # 检查 id 是否存在
            old_row = conn.execute(
                "SELECT name, remark FROM poi_points WHERE id=?", (fid,)
            ).fetchone()

            if old_row is None:
                # 新 POI
                conn.execute(INSERT, (
                    fid, name, address, province, city, district, township,
                    lon, lat, color, code, size, remark, nc,
                    "", "", "", "", "", "", "",
                    "", "", "", "", 0.0, "", 0.0, 0.0, 0.0, 0.0,
                    "", "", now, now
                ))
                stats["add"] += 1
                changes.append({
                    "id": fid,
                    "name": [name, ""],
                    "remark": [remark, ""],
                    "status": "add"
                })
                logger.debug(f"[导入] 新 POI: {name} ({fid}) remark={remark[:80]}")
            else:
                old_name, old_remark = old_row
                if remark == old_remark:
                    stats["skipped"] += 1
                elif old_remark in remark and len(remark) > len(old_remark):
                    # 新 remark 包含旧 remark 且内容更长 → 更新
                    conn.execute(UPDATE_REMARK, (remark, now, fid))
                    stats["update"] += 1
                    changes.append({
                        "id": fid,
                        "name": [name, old_name],
                        "remark": [remark, old_remark],
                        "status": "update"
                    })
                    logger.debug(f"[更新] {name} id={fid[:8]} remark={old_remark[:40]}→{remark[:40]}")
                else:
                    # 无包含关系 → 只记录不更新
                    changes.append({
                        "id": fid,
                        "name": [name, old_name],
                        "remark": [remark, old_remark],
                        "status": "record"
                    })
                    logger.debug(f"[记录] {name} id={fid[:8]} 无包含关系")

        except Exception as e:
            stats["error"] += 1
            name = info.get("name", "") if info else ""
            logger.error(f"[导入失败] id={fid} name={name} error={e}")

    conn.commit()
    conn.close()

    # ---- 4. 保存变更日志 ----
    if changes:
        await save_json([UUID, "changes"], changes, subdir="update")

    logger.info(f"[入库] 新增={stats['add']}, 更新={stats['update']}, 记录={stats['record']}, 跳过={stats['skipped']}, 失败={stats['error']}")

    # ---- 5. 验证 ----
    conn = sqlite3.connect(str(DB_PATH))
    total = conn.execute("SELECT COUNT(*) FROM poi_points").fetchone()[0]
    logger.info(f"[验证] 数据库总记录数: {total}")
    conn.close()

    return stats


if __name__ == "__main__":
    try:
        stats = asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[中断] 用户强制停止 (Ctrl+C)")
    except Exception as e:
        logger.error(f"[致命] 程序异常退出: {e}")
        sys.exit(1)
