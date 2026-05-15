"""地址解析工具

基于 cpca（中国省市区地址）库，自动拆分省市区，街道从剩余地址中提取。
对 cpca 吞掉区名的情况（如光明区、临平区等），用原始地址手动裁剪兜底。"""

import re

import cpca

# 街道/镇/乡/办事处级前缀
_TOWN_RE = re.compile(
    r"^(.*?(街道|镇|乡|民族乡|办事处))"
)


def _extract_town(detail: str) -> str:
    """从详细地址开头提取街道/镇级别信息。"""
    if not detail:
        return ""
    m = _TOWN_RE.match(detail)
    if m:
        return m.group(1)
    return ""


def parse_address(addr: str) -> dict | None:
    """解析中文地址为省市区乡镇。

    策略：
    1. 先过 cpca，拿到省、市、区
    2. 从原始地址手动剪掉"省"+"市"，剩余部分取区名（解决 cpca 吞区名问题）
    3. 从 detail 或裁剪后的剩余部分中提取 township

    :param addr: 如 "广东省深圳市光明区凤凰街道长圳路东218号"
    :return: {province, city, district, town, detail} 或 None
    """
    if not addr or not addr.strip():
        return None

    df = cpca.transform([addr])
    if df.empty:
        return None

    rec = df.iloc[0]
    province = rec.get("省", "")
    city = rec.get("市", "")
    cpca_district = rec.get("区", "")
    detail = rec.get("地址", "")

    # 直辖市/港澳台：cpca 把"重庆市"/"北京市"等当省，市=None
    # 此时 city 设为 province 本身
    if not city and province:
        city = province

    # 手动裁剪：从原始地址剪掉省+市，拿剩余部分
    rest = addr
    if province and rest.startswith(province):
        rest = rest[len(province):]
    if city and rest.startswith(city):
        rest = rest[len(city):]

    # 从 rest 中提取 district（如"光明区凤凰街道..."→"光明区"）
    district = cpca_district
    rest_after_district = ""
    if not district and rest:
        m = re.match(r"([一-龥]+?[区市县])(.*)", rest)
        if m:
            district = m.group(1)
            rest_after_district = m.group(2)

    # 提取 township
    # 优先从 rest_after_district 中提取（最干净，不含 cpca 吞掉的杂质）
    town = ""
    if rest_after_district:
        town = _extract_town(rest_after_district)
    # 退而求其次从 cpca 的 detail 中提取
    if not town:
        town = _extract_town(detail)

    return {
        "province": province,
        "city": city,
        "district": district,
        "town": town,
        "detail": detail,
    }
