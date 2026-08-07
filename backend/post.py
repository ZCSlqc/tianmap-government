"""从数据库读取 POI/线/面数据，反向编码为天地图分享格式，POST 创建新分享。

用法：python3 backend/post.py
"""

import sys
import json
import urllib.parse
from pathlib import Path

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

from backend.util import logger, save_json

import asyncio
import sqlite3
import requests

# ==================== 配置 ====================
DB_PATH = Path(__file__).parent.parent / "data" / "tianmap.db"
TEMPLATE_PATH = Path(__file__).parent.parent / "assert" / "templete.json"
TIANDITU_POST = "https://map.tianditu.gov.cn/api/map/share"

# 默认值（与 template.md 一致）
_DEFAULT_STYLE_POINT = {"code": "100000", "size": 30, "color": "rgb(255,0,0)"}
_DEFAULT_STYLE_LINE = {"code": 0, "width": 2, "color": "#FF0000"}
_DEFAULT_STYLE_POLYGON = {"code": 0, "width": 2, "color": "#FF0000", "opacity": 0.2}

SHOW_NAME = True

def _diff_style(style: dict, defaults: dict, featureType: str) -> dict:
    """剔除默认值，只保留非默认字段。"""
    result = {}
    for k, v in style.items():
        default_v = defaults.get(k)
        # color 需要字符串化对比
        if k == "color":
            expected = defaults.get("color", "")
            if str(v) == expected:
                continue
        elif v == default_v:
            continue
        result[k] = v
    return result


def encode_point(row: tuple) -> dict:
    """poi_points 表一行 → Points 结构。"""
    fid, name, address, lon, lat, color, code, size, remark, nc = row[:10]

    style = {}
    if str(color) != _DEFAULT_STYLE_POINT["color"]:
        style["color"] = color
    if int(size) != _DEFAULT_STYLE_POINT["size"]:
        style["size"] = int(size)
    if str(code) != _DEFAULT_STYLE_POINT["code"]:
        style["code"] = code
    style["nameChecked"] = bool(nc) if SHOW_NAME else False

    fi = {
        "name": name,
        "address": address or "",
        "lonlat": f"{lon} {lat}" if lon and lat else "",
        "icon": "symbol",
        "style": style if style else {},
    }

    if remark:
        fi["remark"] = remark

    return {"featureId": fid, "featureType": "1", "featureInfo": fi}


def encode_line(row: tuple) -> dict:
    """line_polygon 表线记录 → Lines 结构。"""
    # id, name, featureType, lnglats, code, color, width, opacity,
    # region_type, size, remark, feature,
    # s_*, e_*
    fid, name, _, lnglats_str, code, color, width, opacity, _, _, remark = (
        row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7],
        row[8], row[9], row[10],
    )

    lnglats = json.loads(lnglats_str) if lnglats_str else []
    if not lnglats:
        return None

    style = {}
    if int(width) != _DEFAULT_STYLE_LINE["width"]:
        style["width"] = int(width)
    if str(color) != _DEFAULT_STYLE_LINE["color"]:
        style["color"] = color
    if str(code) != str(_DEFAULT_STYLE_LINE["code"]):
        style["code"] = code

    fi = {
        "name": name,
        "lngLats": lnglats,
        "style": style if style else {},
    }
    if remark:
        fi["remark"] = remark

    return {"featureId": fid, "featureType": "2", "featureInfo": fi}


def encode_polygon(row: tuple) -> dict:
    """line_polygon 表面记录 → Polygons 结构。"""
    fid, name, _, lnglats_str, code, color, width, opacity, _, _, remark = (
        row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7],
        row[8], row[9], row[10],
    )

    lnglats = json.loads(lnglats_str) if lnglats_str else []
    if not lnglats:
        return None

    style = {}
    if int(width) != _DEFAULT_STYLE_POLYGON["width"]:
        style["width"] = int(width)
    if str(color) != _DEFAULT_STYLE_POLYGON["color"]:
        style["color"] = color
    if float(opacity) != _DEFAULT_STYLE_POLYGON["opacity"]:
        style["opacity"] = float(opacity)
    if str(code) != str(_DEFAULT_STYLE_POLYGON["code"]):
        style["code"] = code

    fi = {
        "name": name,
        "lngLats": lnglats,
        "style": style if style else {},
    }
    if remark:
        fi["remark"] = remark

    return {"featureId": fid, "featureType": "3", "featureInfo": fi}


def build_payload(points: dict, lines: dict, polygons: dict) -> dict:
    """把 points/lines/polygons 组装进完整 share 模板。"""
    # 加载模板
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        template = json.load(f)

    # 替换 drawInfo
    template["drawInfo"]["points"] = points
    template["drawInfo"]["lines"] = lines
    template["drawInfo"]["polygons"] = polygons

    # 清理空容器
    for k in ("circles", "rects", "saves", "measure-polygons", "measure-distances"):
        if k in template["drawInfo"]:
            template["drawInfo"][k] = {}

    return template


def build_payloads() -> list[tuple[str, dict]]:
    """从数据库读取，按 江苏省/其他 切分，返回 [(label, payload)]。

    点按 poi_points.province、线面按 line_polygon.s_province 区分。
    """
    js_points, other_points = {}, {}
    js_lines, other_lines = {}, {}
    js_polygons, other_polygons = {}, {}

    with sqlite3.connect(str(DB_PATH)) as conn:
        # ---- Points ----
        rows = conn.execute(
            "SELECT id, name, address, lon, lat, color, code, size, remark, name_checked, province FROM poi_points"
        ).fetchall()
        for row in rows:
            encoded = encode_point(row)
            if not encoded:
                continue
            target = js_points if row[-1] == "江苏省" else other_points
            target[encoded["featureId"]] = encoded

        # ---- Lines & Polygons ----
        rows = conn.execute(
            "SELECT id, name, featureType, lnglats, code, color, width, opacity, region_type, size, remark, s_province FROM line_polygon"
        ).fetchall()
        for row in rows:
            featureType = row[2]
            if featureType == "2":
                encoded = encode_line(row)
            elif featureType == "3":
                encoded = encode_polygon(row)
            else:
                continue
            if not encoded:
                continue
            js = row[-1] == "江苏省"
            if featureType == "2":
                (js_lines if js else other_lines)[encoded["featureId"]] = encoded
            else:
                (js_polygons if js else other_polygons)[encoded["featureId"]] = encoded

    batches = []
    for label, pts, lns, pgs in (
        ("jiangsu", js_points, js_lines, js_polygons),
        ("other", other_points, other_lines, other_polygons),
    ):
        if not pts and not lns and not pgs:
            continue  # 空批次跳过
        batches.append((label, build_payload(pts, lns, pgs)))
    return batches


def submit(draw_info: dict) -> str:
    """POST 天地图 API，返回新 UUID。"""
    body = "json=" + urllib.parse.quote(json.dumps(draw_info, ensure_ascii=False))
    resp = requests.post(
        TIANDITU_POST,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=body,
        timeout=60,
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("status") != 200:
        raise RuntimeError(f"API 返回错误: {result}")
    new_uuid = json.loads(result["data"])["address"]
    return new_uuid


def save_payload(draw_info: dict, label: str = "") -> Path:
    """待上传 payload 落盘 tmp/gen_url/（复用 util.save_json，与 main.py 的 raw_url 落盘一致）"""
    name = f"post_payload_{label}" if label else "post_payload"
    path = asyncio.run(save_json(name, draw_info, subdir="gen_url"))
    logger.info(f"[POST] payload 已保存: {path}")
    return path


def main():
    logger.info("[POST] 开始构建 payload")
    batches = build_payloads()
    logger.info(f"[POST] 共 {len(batches)} 批")

    for label, draw_info in batches:
        points = draw_info["drawInfo"]["points"]
        lines = draw_info["drawInfo"].get("lines", {})
        polygons = draw_info["drawInfo"].get("polygons", {})
        logger.info(f"[POST] 批次[{label}] points={len(points)}, lines={len(lines)}, polygons={len(polygons)}")

        save_payload(draw_info, label)

        logger.info(f"[POST] 批次[{label}] 提交到天地图 API")
        new_uuid = submit(draw_info)
        logger.info(f"[POST] 批次[{label}] 成功! UUID={new_uuid}")
        logger.info(f"[POST] 批次[{label}] 新分享链接: https://map.tianditu.gov.cn/share/{new_uuid}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("[中断]")
    except Exception as e:
        logger.error(f"[致命] {e}")
        sys.exit(1)
