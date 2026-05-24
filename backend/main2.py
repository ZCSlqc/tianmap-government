"""line/polygon 天地图分享数据 → SQLite 入库

用法：修改 UUID 变量，直接运行 python3 backend/main2.py

增量模式：
- id 不存在 → INSERT
- id 存在且 remark 不同 → UPDATE remark + record
- 其余跳过
"""

import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

from backend.util import logger, save_json

import asyncio
import json
import sqlite3
from datetime import datetime

import aiohttp

# ==================== 配置 ====================
UUID = "c34faf791b4641a19a02104ebc7f83f4"
TIANDITU_API = "https://map.tianditu.gov.cn/api/map/share"
DB_PATH = Path(__file__).parent.parent / "data" / "tianmap.db"


def _safe_float(val, default=0.0):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


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

    # 解包：支持 drawInfo 嵌套或直接顶层两种格式
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
    lines = draw_info.get("lines", {})
    polygons = draw_info.get("polygons", {})
    logger.debug(f"[下载] 获取 {len(lines)} 条线 | {len(polygons)} 个面")

    # ---- 2. 建表 ----
    logger.debug("[建表] 确保 line_polygon 表存在")
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("CREATE TABLE IF NOT EXISTS line_polygon ("
        "id TEXT PRIMARY KEY, "
        "name TEXT DEFAULT '', featureType TEXT DEFAULT '', "
        "lnglats TEXT DEFAULT '', "
        "code TEXT DEFAULT '', color TEXT DEFAULT '', "
        "width INT DEFAULT 0, opacity FLOAT DEFAULT 0.0, "
        "region_type TEXT DEFAULT '', size INTEGER DEFAULT 30, "
        "remark TEXT DEFAULT '', feature TEXT DEFAULT '', "
        "s_province TEXT DEFAULT '', s_city TEXT DEFAULT '', "
        "s_district TEXT DEFAULT '', s_township TEXT DEFAULT '', "
        "e_province TEXT DEFAULT '', e_city TEXT DEFAULT '', "
        "e_district TEXT DEFAULT '', e_township TEXT DEFAULT '', "
        "record TEXT DEFAULT '', created_at TEXT, updated_at TEXT)")
    conn.commit()

    # ---- 3. 入库 ----
    now = datetime.now().isoformat()

    INSERT = (
        "INSERT INTO line_polygon "
        "(id,name,featureType,lnglats,code,color,width,opacity,"
        "region_type,size,remark,feature,"
        "s_province,s_city,s_district,s_township,"
        "e_province,e_city,e_district,e_township,"
        "record,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )
    UPDATE_FIELDS = (
        "name=?, code=?, color=?, width=?, opacity=?, region_type=?, "
        "size=?, remark=?, feature=?, s_province=?, s_city=?, s_district=?, "
        "s_township=?, e_province=?, e_city=?, e_district=?, e_township=?, "
        "lnglats=?, updated_at=?"
    )

    # 变更日志收集
    changes = []

    for dic in (lines, polygons):
        for fid, item in dic.items():
            try:
                featureType = item.get("featureType")
                if featureType not in ["2","3"]:
                    continue
                fi = item.get("featureInfo", {})
                if not isinstance(fi, dict):
                    continue
                name = fi.get("name", "")
                if not name:
                    continue
                lnglats_raw = fi.get("lngLats", [])
                if not lnglats_raw:
                    continue

                style = fi.get("style", {})
                remark = fi.get("remark", "")

                code = style.get("code", "0")
                color = style.get("color", "#FF0000")
                width = style.get("width", 2)
                opacity = style.get("opacity", 0.2) if featureType == "3" else 1.0

                # 类型转换
                width_val = _safe_int(width, 0) if width else 0
                opacity_val = _safe_float(opacity, 0.0) if opacity else 0.0

                # lnglats → JSON 字符串
                lnglats_str = json.dumps(lnglats_raw, ensure_ascii=False)

                # 检查 id 是否存在
                old_row = conn.execute(
                    "SELECT name, remark FROM line_polygon WHERE id=?", (fid,)
                ).fetchone()

                if old_row is None:
                    # 新 line/polygon
                    conn.execute(INSERT, (
                        fid, name, featureType, lnglats_str,
                        code, color, width_val, opacity_val,
                        "", 30, remark, "",
                        "", "", "", "",
                        "", "", "", "",
                        "", now, now
                    ))
                    stats["add"] += 1
                    changes.append({
                        "id": fid,
                        "name": [name, ""],
                        "remark": [remark, ""],
                        "status": "add"
                    })
                    logger.debug(f"[导入] 新 line/polygon: {name} ({fid[:8]}...) remark={remark[:80]}")
                else:
                    old_name, old_remark = old_row
                    if remark == old_remark:
                        stats["skipped"] += 1
                    elif old_remark in remark and len(remark) > len(old_remark):
                        # 新 remark 包含旧 remark 且内容更长 → 更新
                        conn.execute("UPDATE line_polygon SET remark=?, updated_at=? WHERE id=?",
                                    (remark, now, fid))
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
                        stats["record"] += 1
                        changes.append({
                            "id": fid,
                            "name": [name, old_name],
                            "remark": [remark, old_remark],
                            "status": "record"
                        })
                        logger.debug(f"[记录] {name} id={fid[:8]} 无包含关系")

            except Exception as e:
                stats["error"] += 1
                name = fi.get("name", "") if fi else ""
                logger.error(f"[导入失败] id={fid} name={name} error={e}")

    conn.commit()
    conn.close()

    # ---- 4. 保存变更日志 ----
    if changes:
        await save_json([UUID, "changes(line)"], changes, subdir="update")

    logger.info(f"[入库] 新增={stats['add']}, 更新={stats['update']}, 记录={stats['record']}, 跳过={stats['skipped']}, 失败={stats['error']}")

    # ---- 5. 验证 ----
    conn = sqlite3.connect(str(DB_PATH))
    total = conn.execute("SELECT COUNT(*) FROM line_polygon").fetchone()[0]
    logger.info(f"[验证] line_polygon 总记录数: {total}")
    conn.close()

    return stats


if __name__ == "__main__":
    try:
        from backend.util import save_json
        stats = asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[中断] 用户强制停止 (Ctrl+C)")
    except Exception as e:
        logger.error(f"[致命] 程序异常退出: {e}")
        sys.exit(1)
