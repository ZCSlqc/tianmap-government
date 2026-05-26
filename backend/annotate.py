"""POI 标注脚本：地址校验 → Agent 选择 AOI/POI → Agent 标注分类 → 入库

流程：
1. 从 DB 随机取 POI
2. 高德逆地理编码 + 名称搜索，校验省市区（不一致记录 record，优先采纳高德）
3. Agent 选择 POI 或 AOI（只返回 amap_id + name）
4. 用 amap_id 在候选中查找完整数据，验证 name 一致性（不一致记录 record，优先采纳 agent）
5. Agent 标注分类
6. 统一入库，record 记录所有变更

日志优先使用 loguru，关键步骤和所有报错写入 log
"""

import asyncio
import json
import sqlite3
import sys
import urllib.parse
from pathlib import Path
from datetime import datetime

from backend.util import logger, save_json
from backend.api.amap import query_candidates
from backend.api.config import HERMES_MAX_RETRIES
from backend.api.hermes import chat_return_json
from backend.mapping import get_color_code

DB_PATH = Path(__file__).parent.parent / "data" / "tianmap.db"
SELECT_PROMPT_PATH = Path(__file__).parent.parent / "assert" / "hermes_system" / "select_prompt.md"
ANNOTATE_PROMPT_PATH = Path(__file__).parent.parent / "assert" / "hermes_system" / "annotate_prompt.md"


# ===================== Agent 选择 AOI/POI =====================

def resolve_selection(agents_amap_id: str, agents_name: str, candidates: list) -> tuple[dict | None, str]:
    """
    用 agent 返回的 amap_id + name 在候选中查找完整数据。
    返回: (完整数据, 验证消息)
    """
    for c in candidates:
        if c.get("amap_id") == agents_amap_id:
            if agents_name and agents_name != c.get("amap_name", ""):
                return None, f"name='{agents_name}' 与候选 name='{c.get('amap_name')}' 不一致"
            return c, f"amap_id={agents_amap_id} 匹配成功"
    return None, f"amap_id={agents_amap_id} 未找到"


try:
    SYSTEM_SELECT = SELECT_PROMPT_PATH.read_text(encoding="utf-8")
except FileNotFoundError:
    raise RuntimeError(f"选择提示词文件不存在: {SELECT_PROMPT_PATH}")
try:
    SYSTEM_ANNOTATE = ANNOTATE_PROMPT_PATH.read_text(encoding="utf-8")
except FileNotFoundError:
    raise RuntimeError(f"标注提示词文件不存在: {ANNOTATE_PROMPT_PATH}")


def build_select_messages(poi_name: str, geo: dict, candidates: list) -> list[dict]:
    geo_info = ""
    if geo:
        geo_info = f"- **逆地理地址**: {geo.get('geo_detail', 'N/A')}\n"
        geo_info += f"- **省市区**: {geo.get('province', '')}/{geo.get('city', '')}/{geo.get('district', '')}/{geo.get('township', '')}\n"
    candidates_json = json.dumps(candidates, ensure_ascii=False, indent=2)
    user_content = (f"- **SPOT 名称**: {poi_name}\n{geo_info}"
                    f"- **候选列表（最多 11 条，已按距离排序）**:\n```json\n{candidates_json}\n```\n"
                    "\n请根据名称判断：这是一个单体点位（选 POI）还是一个片区/广场/商圈（选 AOI）？")
    return [{"role": "system", "content": SYSTEM_SELECT}, {"role": "user", "content": user_content}]


async def select_type(poi_name: str, geo: dict, candidates: list) -> tuple[str | None, dict | None, str, int]:
    """
    Agent 选择 POI 或 AOI（只返回 amap_id + name），
    然后在候选中用 amap_id 查找完整数据。
    返回: (选定类型，选定结果, 选择理由, 使用次数)
    """
    messages = build_select_messages(poi_name, geo, candidates)

    for attempt in range(1, HERMES_MAX_RETRIES + 1):
        parsed = await chat_return_json(messages)
        if not parsed:
            continue

        selected_type = parsed.get("selected_type", "")
        selected_item = parsed.get("selected_item", {})
        agents_source = selected_item.get("source", "")

        # 基础校验
        if selected_type not in ("poi", "aoi", "none"):
            messages.append({"role": "assistant", "content": ""})
            messages.append({"role": "user", "content": f"selected_type='{selected_type}' 无效，必须是 poi、aoi 或 none。"})
            continue
        if agents_source not in ("geo_poi", "geo_aoi", "name_poi"):
            messages.append({"role": "assistant", "content": ""})
            messages.append({"role": "user", "content": f"source='{agents_source}' 无效，必须是 geo_poi / geo_aoi / name_poi 之一。"})
            continue
        if selected_type == "aoi" and agents_source != "geo_aoi":
            messages.append({"role": "assistant", "content": ""})
            messages.append({"role": "user", "content": "selected_type=aoi 但 source 不是 geo_aoi，请修正。"})
            continue
        if selected_type == "poi" and agents_source == "geo_aoi":
            messages.append({"role": "assistant", "content": ""})
            messages.append({"role": "user", "content": "selected_type=poi 但 source 是 geo_aoi，请修正。"})
            continue

        agents_amap_id = selected_item.get("amap_id", "")
        agents_name = selected_item.get("name", "")
        selected, err_msg = resolve_selection(agents_amap_id, agents_name, candidates)
        if not selected:
            messages.append({"role": "assistant", "content": ""})
            messages.append({"role": "user", "content": f"{err_msg}，请重新选择。"})
            continue

        logger.debug(f"[选择] 自检通过: type={selected_type} source={agents_source} id={agents_amap_id}")
        return selected_type, selected, parsed.get("reason", ""), attempt

    logger.error("[选择] 全部重试失败")
    return None, None, "agent解析失败", HERMES_MAX_RETRIES


# ===================== Agent 标注分类 =====================

def build_annotate_messages(poi_name: str, geo: dict, selected_info: str, remark: str | None) -> list[dict]:
    user_content = (f"## SPOT 信息\n\n"
                    f"- **SPOT 名称**: {poi_name}\n"
                    f"- **省市区**: {geo.get('province', '')}/{geo.get('city', '')}/{geo.get('district', '')}/{geo.get('township', '')}\n"
                    f"- **备注**: {remark or '无'}\n"
                    f"## AMAP 选择\n\n"
                    f"{selected_info}"
                    f"## 你的任务\n\n"
                    f"1. **必须先搜索再标注**：\n"
                    f"   1.1 使用 web_search 工具搜索 SPOT 名称，获取搜索结果摘要\n"
                    f"   1.2 如 web_search 结果不足，使用 browser_navigate 打开百度搜索（URL: https://www.baidu.com/s?wd={urllib.parse.quote(poi_name)}），用 browser_snapshot 读取链接和摘要\n"
                    f"   1.3 对搜索结果中有价值的链接，使用 web_extract 提取详细内容\n"
                    f"   1.4 如百度结果仍不足，再打开搜狗搜索（URL: https://www.sogou.com/web?query={urllib.parse.quote(poi_name)}），重复 1.2-1.3\n"
                    f"      - 提示：可在 URL 中追加搜索参数\n"
                    f"   1.5 禁止凭记忆回答，必须以搜索到的实时信息为准\n"
                    f"   1.6 至少完成一次完整搜索后再开始标注\n"
                    f"   1.7 若采用无头搜索建议采用（URL: https://www.bing.com）\n"
                    f"2. **分类标注**: 对照上方分类规则判断归属大类和细分类型，补充全部字段\n"
                    f"3. **冲突处理**: 若同时符合多个分类，按规则中的冲突解决优先级判断\n")

    return [{"role": "system", "content": SYSTEM_ANNOTATE}, {"role": "user", "content": user_content}]


async def annotate_category(poi_name: str, geo: dict, selected_info: str, remark: str | None) -> tuple[dict | None, int]:
    """Agent 标注分类，最多重试 HERMES_MAX_RETRIES 次，内部自检字段。"""
    messages = build_annotate_messages(poi_name, geo, selected_info, remark)

    required_fields = ("name", "affiliation", "point_type", "level", "feature", "parent_company", "constructor")

    for attempt in range(1, HERMES_MAX_RETRIES + 1):
        parsed = await chat_return_json(messages)
        if not parsed:
            logger.warning(f"[标注] 第 {attempt} 次返回为空或格式不对")
            continue

        # 校验必填字段
        missing = [f for f in required_fields if not parsed.get(f, "")]
        if missing:
            logger.warning(f"[标注] 缺少字段: {missing}，重试")
            messages.append({"role": "assistant", "content": ""})
            messages.append({"role": "user", "content": f"缺少必填字段: {missing}，请补充完整后重新输出。"})
            continue

        # 校验关键内容字段不能是占位词
        invalid = False
        for f in ("name", "affiliation", "point_type"):
            v = parsed.get(f, "")
            if v in ("信息待补充", "未知", ""):
                logger.warning(f"[标注] {f}='{v}' 无效，请填写真实内容，重试")
                messages.append({"role": "assistant", "content": ""})
                messages.append({"role": "user", "content": f"{f} 不能填占位词，请填写真实内容。"})
                invalid = True
                break
        if invalid:
            continue

        logger.debug(f"[标注] 自检通过: {parsed.get('affiliation')}/{parsed.get('point_type')}")
        return parsed, attempt

    logger.error("[标注] 全部重试失败")
    return None, HERMES_MAX_RETRIES


# ===================== 入库 =====================

def save_result(poi_id: str, db_name: str, geo: dict | None, selected_type: str | None, selected: dict | None, annotation: dict | None):
    now = datetime.now().isoformat()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        conn.execute("BEGIN")
        # 1. 查旧数据打底
        cur = conn.execute("SELECT * FROM poi_points WHERE id=?", (poi_id,))
        old_row = cur.fetchone()
        cols = [d[0] for d in cur.description] if cur.description else []
        table_cols = set(cols)
        old_dict = dict(zip(cols, old_row)) if old_row else {}
        new = {}

        # 2. geo 负责：省市区街道
        if geo:
            for k in ("province", "city", "district", "township", "geo_detail"):
                v = geo.get(k, "")
                if v and k in table_cols:
                    new[k] = v

        # 3. selected 负责：全套高德字段（selected 返回值已带 amap_ 前缀，直接映射）
        if selected:
            if selected_type:
                new["amap_selected"] = selected_type
            for k, v in selected.items():
                if v and k in table_cols:
                    new[k] = v  # k 已带 amap_ 前缀
            new["name"] = selected.get("amap_name", db_name)  # 优先采纳 agent 选定的名称

        # 4. annotation 负责：业务属性  name最优先级
        if annotation:
            for k, v in annotation.items():
                if v and k in table_cols:
                    new[k] = v

        affiliation = annotation.get("affiliation", "")
        point_type = annotation.get("point_type", "")
        color, code = get_color_code(affiliation, point_type)
        new["color"] = color
        new["code"] = code

        # 去掉空值 key（0/False 是有效值，不跳过）
        new = {k: v for k, v in new.items() if v is not None and v != "" and not isinstance(v, dict)}

        if annotation:
            new["size"] = 15  # 已标注，缩小标记，避免重复选取
        new["name_checked"] = 1
        new["updated_at"] = now

        # 6. 变更记录：白名单对比
        compare_fields = ("name", "province", "city", "district", "township", "affiliation", "point_type")
        changes = {}
        for f in compare_fields:
            old_v = old_dict.get(f, "")
            cur_v = new.get(f, "")
            if old_v and cur_v and old_v != cur_v:
                changes[f] = [cur_v, old_v]

        if changes:
            full_record = json.dumps(changes, ensure_ascii=False)
        else:
            full_record = ""
        new["record"] = full_record[:2000]

        # 7. 入库
        cur = conn.execute("SELECT 1 FROM poi_points WHERE id=?", (poi_id,))
        if cur.fetchone():
            SET = ", ".join(f"{k}=?" for k in new)
            conn.execute(f"UPDATE poi_points SET {SET} WHERE id=?", list(new.values()) + [poi_id])
        else:
            cols = list(new)
            SET = ", ".join(f"{k}=?" for k in cols)
            placeholders = ", ".join(["?"] * len(cols))
            conn.execute(f"INSERT INTO poi_points ({', '.join(cols)}) VALUES ({placeholders})", list(new.values()) + [poi_id])
        conn.commit()
        logger.info(f"[入库] poi_id={poi_id} {affiliation}/{point_type} {color}/{code}")
        logger.info(f"[记录] {full_record}")
    except Exception as e:
        logger.error(f"[入库失败] poi_id={poi_id} error={e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ===================== 主流程 =====================

async def run(count: int = 1, all_mode: bool = False):
    logger.debug(f"{'='*80}")
    logger.debug(f"=== 启动标注，count={count}, all={all_mode} ===")

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    _current_poi = "[none]"

    try:
        total = 0
        # 随机选取：先 COUNT，再随机取 N 个 id，避免 ORDER BY RANDOM() 全表扫描
        n = conn.execute(
            "SELECT COUNT(*) FROM poi_points WHERE lon != 0 AND lat != 0 AND amap_id='' "
        ).fetchone()[0]
        logger.info(f"[标注] 待处理 {n} 条SPOT")
        while n > 0:
            take = min(count, n)
            n -= take
            rows = conn.execute(
                "SELECT id FROM poi_points WHERE lon != 0 AND lat != 0 AND amap_id='' "
                "ORDER BY RANDOM() LIMIT ?", (take,)
            ).fetchall()
            if not rows:
                break
            ids = [r[0] for r in rows]
            placeholders = ",".join(["?"] * len(ids))
            rows = conn.execute(
                f"SELECT id, name, lon, lat, province, city, district, township, remark "
                f"FROM poi_points WHERE id IN ({placeholders})", ids
            ).fetchall()
            for r in rows:
                total += 1
                poi_id, poi_name, lon, lat, province, city, district, township, remark = r
                _current_poi = poi_name
                logger.debug(f"{'-'*40}")
                logger.info(f"SPOT: {poi_name} | {province}/{city}/{district}/{township}")

                # Step 1: 高德查询
                logger.debug("[1] 高德查询...")
                result = await query_candidates(poi_name, lon, lat, city)
                geo = result["geo"]
                candidates = result["candidates"]
                await save_json([poi_name, poi_id[:8]], candidates, subdir="amap")

                # Step 2: geo 为空则跳过地址对比和选择，直接标注
                if geo:
                    amap_province = (geo.get("province") or "").strip()
                    amap_city = (geo.get("city") or "").strip()
                    amap_district = (geo.get("district") or "").strip()
                    amap_township = (geo.get("township") or "").strip()
                    diffs = []
                    for db_val, amap_val, _ in [
                        (province, amap_province, "省"), (city, amap_city, "市"),
                        (district, amap_district, "区"), (township, amap_township, "街道"),
                    ]:
                        if amap_val and db_val and amap_val != db_val:
                            diffs.append(f"DB={db_val} → 高德={amap_val}")
                    if not diffs:
                        logger.debug(f"[地址] 一致: {amap_province}/{amap_city}/{amap_district}/{amap_township}")
                    else:
                        logger.debug(f"[地址] 不一致: {' | '.join(diffs)}")
                else:
                    logger.warning("[地址] 高德返回为空，跳过地址对比")

                # Step 3: Agent 选择 AOI/POI（None=失败, {}=兜底, dict=选中）
                logger.debug("[2] Agent 筛选高德...")
                selected = None
                selected_type = None
                selected_reason = None
                if candidates:
                    selected_type, selected, selected_reason, select_attempts = await select_type(poi_name, geo, candidates)
                    if selected is None:
                        logger.error(f"[降级] {selected_reason}")
                        logger.error(f"[选择] 不使用 Amap 数据")
                    elif isinstance(selected, dict) and selected:
                        sel_name = selected.get('amap_name', '')
                        sel_type = selected.get('source', '')
                        sel_distance = selected.get('amap_distance', 99999)
                        prev_names = []
                        for c in candidates:
                            if c.get("amap_id") == selected.get("amap_id"):
                                break
                            prev_names.append(f"{c.get('amap_name', '')}({c.get('source', '')})")

                        if sel_name == poi_name:
                            logger.debug(f"[名称] 一致: {poi_name}")
                        else:
                            logger.debug(f"[名称] 不一致: DB={poi_name} → agent={sel_name}")
                        if prev_names:
                            logger.debug(f"[选择] {sel_type} | {sel_distance}m | 第{len(prev_names)+1}名 | 前面: {', '.join(prev_names)}")
                        else:
                            logger.debug(f"[选择] {sel_type} | {sel_distance}m | 第1名")
                        if sel_distance > 200:
                            logger.warning(f"[警告] {sel_distance}m 超出阈值")
                        logger.debug(f"[理由] {selected_reason} ({select_attempts}次成功)")
                else:
                    logger.warning("[选择] 高德返回为空，跳过agent选择")
                
                # 前期组装
                select_info = ""
                if selected:
                    if selected_type=="aoi":
                        select_type_info = "AOI(area of interert)，尽可能以该AOI名字为主，适应模板名称规则" 
                    elif selected_type=="poi":
                        select_type_info = "POI(point of interert)，尽可能以该POI名字为主，适应模板名称规则" 
                    else:
                        select_type_info = "没有适合选项，但依旧提供参考和理由，不过尽可能以原SPOT名字为主，适应模板名称规则"
                    select_info = (f"- **选定类型**: {select_type_info}\n"
                                   f"- **选定结果**: {selected.get('amap_name', '')}\n"
                                   f"- **与SPOT距离**: {selected.get('amap_distance', 0)}m\n"
                                   f"- **地址**: {selected.get('amap_address', '')}\n"
                                   f"- **商圈**: {selected.get('amap_businessarea', '')}\n"
                                   f"- **面积**: {selected.get('amap_area', '')}\n"
                                   f"- **类型**: {selected.get('amap_type', '')}\n"
                                   f"- **选定理由**: {selected_reason}\n")
                else:
                    select_info = "- **选定结果**: 不使用 Amap 数据，以原SPOT名字为主，适应模板名称规则\n"

                # Step 4: Agent 标注分类
                logger.debug("[3] Agent 标注分类...")
                annotation = None
                annotate_geo = geo or {"province": province, "city": city, "district": district, "township": township}
                annotation, annotate_attempts = await annotate_category(poi_name, annotate_geo, select_info, remark)
                if not annotation:
                    logger.error(f"[降级] agent标注失败")
                    logger.error(f"[4] 不入库")
                    continue

                logger.debug(f"[标注] {json.dumps(annotation, ensure_ascii=False)} ({annotate_attempts}次成功)")

                # Step 5: 入库
                logger.debug("[4] 入库...")
                await asyncio.to_thread(save_result, poi_id, poi_name, geo, selected_type, selected, annotation)

    except Exception as e:
        logger.error(f"[run异常] 当前POI={_current_poi} error={e}")
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass
    try:
        logger.info(f"=== 标注完成，共处理 {total} 条 ===")
    except Exception:
        pass

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="POI 标注")
    p.add_argument("-n", "--count", type=int, default=1, help="处理数量")
    p.add_argument("--all", action="store_true", help="处理全部剩余（size=30）")
    args = p.parse_args()
    try:
        asyncio.run(run(count=args.count, all_mode=args.all))
    except KeyboardInterrupt:
        logger.info("[中断] 用户强制停止 (Ctrl+C)")
    except Exception as e:
        logger.error(f"[致命] 程序异常退出: {e}")
        sys.exit(1)
