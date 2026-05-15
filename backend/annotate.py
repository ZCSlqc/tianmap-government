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

import json
import sqlite3
from pathlib import Path
from typing import Any
from datetime import datetime
from dotenv import load_dotenv

from backend.util import logger
from backend.api import query_candidates, save_candidates
from backend.api import chat as hermes_chat
from backend.mapping import get_color_code

# ===================== 配置 =====================
_env_path = Path(__file__).resolve().parent / ".." / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

DB_PATH = Path(__file__).parent.parent / "data" / "tianmap.db"
SELECT_PROMPT_PATH = Path(__file__).parent.parent / "assert" / "select_prompt.md"
ANNOTATE_PROMPT_PATH = Path(__file__).parent.parent / "assert" / "agent_prompt.md"

MAX_RETRIES = 3


# ===================== 工具函数 =====================

def parse_json(text: str) -> dict | None:
    """从文本中提取第一个 JSON 对象"""
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失败: {e}, 内容: {text[:200]}")
            return None
    logger.warning(f"未找到 JSON 对象: {text[:100]}")
    return None


def load_select_prompt() -> str:
    return SELECT_PROMPT_PATH.read_text(encoding="utf-8")


# ===================== 查询封装 =====================

async def query_poi(name: str, lon: float, lat: float,
                    city: str) -> dict[str, Any]:
    """高德查询：逆地理 + 名称搜索，合并去重"""
    return await query_candidates(name, lon, lat, city)


# ===================== Agent 选择 AOI/POI =====================

def build_select_prompt(poi_name: str, geo: dict, candidates: list) -> str:
    geo_info = ""
    if geo:
        geo_info = f"- **逆地理地址**: {geo.get('geo_detail', 'N/A')}\n"
        geo_info += f"- **省市区**: {geo.get('province', '')}/{geo.get('city', '')}/{geo.get('district', '')}/{geo.get('township', '')}\n"

    candidates_json = json.dumps(candidates, ensure_ascii=False, indent=2)
    select_md = load_select_prompt()
    return f"""{select_md}

---

## 当前 POI 信息

- **POI 名称**: {poi_name}
{geo_info}
- **候选列表（最多 11 条，已按距离排序）**:
```json
{candidates_json}
```

请根据名称判断：这是一个单体点位（选 POI）还是一个片区/广场/商圈（选 AOI）？"""


def resolve_selection(agents_amap_id: str, candidates: list) -> tuple[dict | None, str]:
    """
    用 agent 返回的 amap_id 在候选中查找完整数据。
    返回: (完整数据, 验证消息)
    """
    for c in candidates:
        if c.get("amap_id") == agents_amap_id:
            return c, f"amap_id={agents_amap_id} 匹配成功"
    return None, f"amap_id={agents_amap_id} 未找到"


async def select_type(poi_name: str, geo: dict, candidates: list) -> tuple[dict | None, str, int]:
    """
    Agent 选择 POI 或 AOI（只返回 amap_id + name），
    然后在候选中用 amap_id 查找完整数据。
    返回: (选定结果, 选择理由, 使用次数, 是否兜底none)
    """
    prompt = build_select_prompt(poi_name, geo, candidates)
    messages = [{"role": "user", "content": prompt}]

    for attempt in range(1, MAX_RETRIES + 1):
        text = await hermes_chat(messages, max_tokens=1024)
        if not text:
            logger.warning(f"[选择] 第 {attempt} 次返回为空")
            continue

        parsed = parse_json(text)
        if not parsed:
            logger.warning(f"[选择] 第 {attempt} 次格式不对")
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": "返回格式不对，请只输出一个 JSON 对象，不要其他任何文字。"})
            continue

        if parsed.get("selected_type") == "none":
            reason = parsed.get("reason", "无合适结果")
            return {}, reason, attempt

        selected_type = parsed.get("selected_type", "")
        selected_item = parsed.get("selected_item", {})
        agents_amap_id = selected_item.get("amap_id", "")
        agents_source = selected_item.get("source", "")
        reason = parsed.get("reason", "")

        # 校验 source 格式
        if agents_source not in ("geo_poi", "geo_aoi", "name_poi"):
            logger.warning(f"[选择] source='{agents_source}' 无效，重试")
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": "source 必须是 geo_poi / geo_aoi / name_poi 之一，请重新输出。"})
            continue

        # 校验 selected_type
        if selected_type not in ("poi", "aoi"):
            logger.warning(f"[选择] selected_type='{selected_type}' 无效，重试")
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": "selected_type 必须是 poi 或 aoi 之一，请重新输出。"})
            continue

        # source 与 selected_type 一致性检查
        if selected_type == "aoi" and agents_source != "geo_aoi":
            logger.warning(f"[选择] 类型不匹配: selected_type=aoi 但 source={agents_source}，重试")
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": "selected_type=aoi 但 source 不是 geo_aoi，请修正。"})
            continue
        if selected_type == "poi" and agents_source == "geo_aoi":
            logger.warning(f"[选择] 类型不匹配: selected_type=poi 但 source=geo_aoi，重试")
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": "selected_type=poi 但 source 是 geo_aoi，请修正。"})
            continue

        selected, verify_msg = resolve_selection(agents_amap_id, candidates)
        if not selected:
            logger.warning(f"[选择] {verify_msg}，重试")
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": f"未在候选中找到 amap_id={agents_amap_id}，请重新选择。"})
            continue

        # 校验 name 一致性
        agent_name = selected_item.get("name", "")
        if agent_name and agent_name != selected.get("amap_name", ""):
            logger.warning(f"[选择] name 不一致: agent返回='{agent_name}' 候选='{selected.get('amap_name')}'，重试")
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": f"selected_item.name='{agent_name}' 与候选数据 name='{selected.get('amap_name')}' 不一致，请修正。"})
            continue

        logger.info(f"[选择] 自检通过: type={selected_type} source={agents_source} id={agents_amap_id}")
        return selected, reason, attempt

    logger.error("[选择] 全部重试失败")
    return None, "agent解析失败", MAX_RETRIES


# ===================== Agent 标注分类 =====================

def build_annotate_prompt(poi_name: str, geo: dict,
                           selected_item: dict | None, remark: str | None) -> str:
    # 加载 prompt 模板（内部处理）
    _annotate_md = ANNOTATE_PROMPT_PATH.read_text(encoding="utf-8")
    template = _annotate_md.split("# 系统提示")[0].strip()

    if selected_item:
        select_info = f"""- **选定结果**: {selected_item.get('amap_name', '')}
- **高德 ID**: {selected_item.get('amap_id', '')}
- **距离**: {selected_item.get('amap_distance', 0)}m
- **地址**: {selected_item.get('amap_address', '')}
- **商圈**: {selected_item.get('amap_businessarea', '')}
- **面积**: {selected_item.get('amap_area', '')}
- **类型**: {selected_item.get('amap_type', '')}
"""
    else:
        select_info = "- **选定结果**: 无合适候选（不使用 Amap 数据）\n"

    search_q = poi_name
    geo_info = f"- **省市区街道**: {geo.get('province', '')}/{geo.get('city', '')}/{geo.get('district', '')}/{geo.get('township', '')}\n"
    remark_info = f"- **备注**: {remark or '无'}\n"
    return f"""{template}

## 当前 POI 上下文

- **POI 名称**: {poi_name}
{geo_info}
{remark_info}
{select_info}

## 你的任务

1. **必须先搜索再标注**：
   1.1 使用 web_search 工具搜索 POI 名称，获取搜索结果摘要
   1.2 如 web_search 结果不足，使用 browser_navigate 打开百度搜索（URL: https://www.baidu.com/s?wd={search_q}），用 browser_snapshot 读取链接和摘要
   1.3 对搜索结果中有价值的链接，使用 web_extract 提取详细内容
   1.4 如百度结果仍不足，再打开搜狗搜索（URL: https://www.sogou.com/web?query={search_q}），重复 1.2-1.3
      - 提示：可在 URL 中追加搜索参数，例如 wd={search_q}%20额外关键词
   1.5 禁止凭记忆回答，必须以搜索到的实时信息为准
   1.6 至少完成一次完整搜索后再开始标注
2. **分类标注**: 对照上方分类规则判断归属大类和细分类型，补充全部字段
3. **冲突处理**: 若同时符合多个分类，按规则中的冲突解决优先级判断

## 输出格式

只输出一个 JSON，不要其他任何文字：
{{
  "name": "POI 名称",
  "affiliation": "归属大类",
  "point_type": "细分类型",
  "level": "层级标识",
  "feature": "核心特征",
  "parent_company": "上级单位",
  "constructor": "建设方"
}}

铁律：
1. 必须先搜索再标注，禁止凭记忆回答
2. 只输出 JSON，不要 ```json 代码块
3. 不要任何非 JSON 文字
4. 不知道填"信息待补充"，禁止编造
"""


async def annotate_category(poi_name: str, geo: dict, selected_item: dict | None, remark: str | None) -> tuple[dict | None, int]:
    """Agent 标注分类，最多重试 MAX_RETRIES 次，内部自检字段。"""
    prompt = build_annotate_prompt(poi_name, geo, selected_item, remark)
    messages = [{"role": "user", "content": prompt}]

    required_fields = ("name", "affiliation", "point_type", "level", "feature", "parent_company", "constructor")

    for attempt in range(1, MAX_RETRIES + 1):
        text = await hermes_chat(messages, max_tokens=2048)
        if not text:
            logger.warning(f"[标注] 第 {attempt} 次返回为空")
            continue

        parsed = parse_json(text)
        if not parsed:
            logger.warning(f"[标注] 第 {attempt} 次格式不对")
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": "返回格式不对，请只输出一个 JSON 对象，不要其他任何文字。"})
            continue

        # 校验必填字段
        missing = [f for f in required_fields if not parsed.get(f, "")]
        if missing:
            logger.warning(f"[标注] 缺少字段: {missing}，重试")
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": f"缺少必填字段: {missing}，请补充完整后重新输出。"})
            continue

        # 校验关键内容字段不能是占位词
        for f in ("name", "affiliation", "point_type"):
            v = parsed.get(f, "")
            if v in ("信息待补充", "未知", ""):
                logger.warning(f"[标注] {f}='{v}' 无效，请填写真实内容，重试")
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": f"{f} 不能填占位词，请填写真实内容。"})
                continue

        logger.info(f"[标注] 自检通过: {parsed.get('affiliation')}/{parsed.get('point_type')}")
        return parsed, attempt

    logger.error("[标注] 全部重试失败")
    return None, MAX_RETRIES


# ===================== 入库 =====================

def save_result(poi_id: str, db_name: str, conn: sqlite3.Connection, geo: dict | None, selected: dict | None, annotation: dict | None):
    now = datetime.now().isoformat()

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

    # 去掉空值 key
    new = {k: v for k, v in new.items() if v and not isinstance(v, dict)}

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
        if old_v and old_v != cur_v:
            changes[f] = [cur_v, old_v]

    if changes:
        full_record = f"{json.dumps(changes, ensure_ascii=False)}"  #如果直接打印dict行不行
    else:
        full_record = ""
    new["record"] = full_record[:2000]

    # 7. 一次性 UPDATE 入库
    SET = ", ".join(f"{k}=?" for k in new)
    conn.execute(f"UPDATE poi_points SET {SET} WHERE id=?", list(new.values()) + [poi_id])
    conn.commit()
    logger.info(f"[入库] poi_id={poi_id} {affiliation}/{point_type} {color}/{code}")
    logger.info(f"[记录] {full_record}")


# ===================== 主流程 =====================

async def run(count: int = 1, batch_mode: bool = False):
    logger.info(f"{'='*80}")
    logger.info(f"=== 启动标注，count={count}, batch={batch_mode} ===")

    conn = sqlite3.connect(str(DB_PATH))

    rows = conn.execute(
        "SELECT id, name, lon, lat, province, city, district, township, remark "
        "FROM poi_points WHERE lon != 0 AND lat != 0 AND size != 15 "
        "ORDER BY RANDOM()"
    ).fetchmany(count)

    if not rows:
        logger.warning("没有找到可处理的 POI")
        conn.close()
        return

    for r in rows:
        poi_id, poi_name, lon, lat, province, city, district, township, remark = r
        logger.info(f"POI: {poi_name} | {province}/{city}/{district}/{township}")

        # Step 1: 高德查询
        logger.info("[1] 高德查询...")
        result = await query_poi(poi_name, lon, lat, city)
        geo = result["geo"]
        candidates = result["candidates"]
        save_candidates(poi_name, poi_id, candidates)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        logger.info(f"[保存] tmp/amap/{ts}_{poi_name}-{poi_id[:8]}.json")

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
                logger.info(f"[地址] 一致: {amap_province}/{amap_city}/{amap_district}/{amap_township}")
            else:
                logger.info(f"[地址] 不一致: {' | '.join(diffs)}")
        else:
            logger.warning("[地址] 高德返回为空，跳过地址对比")
        
          
        # Step 3: Agent 选择 AOI/POI（None=失败, {}=兜底, dict=选中）
        logger.info("[2] Agent 筛选高德...")
        selected = None
        if candidates:
            selected, reason, select_attempts = await select_type(poi_name, geo, candidates)
            if selected is None:
                logger.error(f"[降级] {reason}")
            if selected == {}:
                logger.info(f"[选择] 不使用 Amap 数据")
                logger.info(f"[理由] {reason} ({select_attempts}次成功)")
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
                    logger.info(f"[名称] 一致: {poi_name}")
                else:
                    logger.info(f"[名称] 不一致: DB={poi_name} → agent={sel_name}")
                if prev_names:
                    logger.info(f"[选择] {sel_type} | {sel_distance}m | 第{len(prev_names)+1}名 | 前面: {', '.join(prev_names)}")
                else:
                    logger.info(f"[选择] {sel_type} | {sel_distance}m | 第1名")
                if sel_distance > 200:
                    logger.warning(f"[距离警告] {sel_distance}m 超出阈值")
                logger.info(f"[理由] {reason} ({select_attempts}次成功)")

        # Step 4: Agent 标注分类
        logger.info("[3] Agent 标注分类...")
        annotation = {}
        annotate_geo = geo or {"province": province, "city": city, "district": district, "township": township}
        annotation, annotate_attempts = await annotate_category(poi_name, annotate_geo, selected, remark)
        if not annotation:
            logger.error("[降级] agent解析失败")
            continue

        logger.info(f"[标注] {json.dumps(annotation, ensure_ascii=False)} ({annotate_attempts}次成功)")

        # Step 5: 入库
        logger.info("[4] 入库...")
        save_result(poi_id, poi_name, conn, geo, selected, annotation)

    conn.close()
    logger.info("=== 标注完成 ===")


if __name__ == "__main__":
    import asyncio
    import argparse
    p = argparse.ArgumentParser(description="POI 标注")
    p.add_argument("-n", "--count", type=int, default=1, help="处理数量")
    p.add_argument("--batch", action="store_true", help="批量模式")
    args = p.parse_args()
    asyncio.run(run(count=args.count, batch_mode=args.batch))
