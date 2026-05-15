"""高德 POI 类型编码 → 中文名转换。

从 Amap_poicode.xlsx 加载映射，将 "060102" 转为 "购物服务;商场;普通商场"。"""

import openpyxl
from pathlib import Path

_CODE_XLSX = Path(__file__).parent.parent.parent / "assert" / "Amap_poicode.xlsx"

_type_cache: dict[str, str] | None = None


def _load_codes() -> dict[str, str]:
    global _type_cache
    if _type_cache is not None:
        return _type_cache

    wb = openpyxl.load_workbook(_CODE_XLSX, read_only=True)
    ws = wb.active
    mapping: dict[str, str] = {}

    # 先收集中类和大类（以 00 结尾）
    big_mid: dict[str, tuple[str, str]] = {}
    for r in range(2, ws.max_row + 1):
        new_type = ws.cell(r, 2).value
        big = ws.cell(r, 3).value or ""
        mid = ws.cell(r, 4).value or ""
        if not isinstance(new_type, str):
            continue
        if new_type.endswith("00") and not new_type.endswith("0000"):
            big_mid[new_type[:4]] = (big, mid)

    # 再处理小类（6位）
    for r in range(2, ws.max_row + 1):
        new_type = ws.cell(r, 2).value
        sub = ws.cell(r, 5).value or ""
        if not isinstance(new_type, str) or len(new_type) != 6:
            continue
        code = new_type
        big, mid = big_mid.get(code[:4], ("", ""))
        mapping[code] = f"{big};{mid};{sub}" if mid and sub else (sub if sub else "")

    wb.close()
    _type_cache = mapping
    return mapping


def code_to_name(code: str) -> str:
    """将 POI 编码转为 "大类;中类;小类" 格式。"""
    if not code:
        return ""
    codes = _load_codes()
    return codes.get(code, "")


def codes_to_name(codes_str: str) -> str:
    """将高德返回的分号分隔编码（如 "050400|050700"）转为中文名。

    高德 type 字段可能用 | 分隔多个编码，这里取第一个匹配。
    """
    if not codes_str:
        return ""
    parts = codes_str.replace("|", ";").split(";")
    names = []
    for c in parts:
        n = code_to_name(c.strip())
        if n:
            names.append(n)
        else:
            names.append(c.strip())
    return ";".join(names)


if __name__ == "__main__":
    print(code_to_name("060102"))       # 购物服务;商场;普通商场
    print(code_to_name("010000"))       # 汽车服务
    print(codes_to_name("050400|050700"))  # 餐饮服务;休闲餐饮场所;餐饮相关|餐饮服务;冷饮店;冷饮店
