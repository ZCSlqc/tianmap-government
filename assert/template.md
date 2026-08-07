# 天地图分享数据格式

> 单一权威文档：服务 `main.py`（入库解析）、`post.py`（导出编码）、前端行为分析
> 数据源：天地图分享 API `https://map.tianditu.gov.cn/api/map/share/{uuid}`，响应 `data` 字段是字符串，二次 JSON 解包后取 `drawInfo`
> 实证样本：`b621712993524e51bdd1d0d106569cde`（9 点 / 3 线 / 1 面）

## 0. drawInfo 顶层结构

```json
{
  "points": { "<featureId>": {...} },           // 点
  "lines":   { "<featureId>": {...} },          // 线
  "polygons": { "<featureId>": {...} },         // 面
  "circles": {},                                // 圆（样本为空）
  "rects": {},                                  // 矩形（空）
  "measure-polygons": {},                       // 测量面（空）
  "measure-distances": {},                      // 测量距离（空）
  "saves": { "<featureId>": true, ... },        // 已保存要素标记
  "plotType": "line",                           // 上次使用的绘制工具
  "clearDrawing": false                         // 是否清空绘制
}
```

### 条目通用结构

三种类型共用一个外壳，`points` / `lines` / `polygons` 的值都是 keyed object（key = featureId）：

```json
{
  "featureId": "14408cf1-8189-44e3-a517-4101293be2c7",   // 唯一标识（UUID）
  "featureType": "1",                                    // "1"=点 "2"=线 "3"=面
  "featureInfo": { ... }                                 // 内容，见下
}
```

## 1. Points（featureType = "1"）→ `poi_points` 表

真实示例（含非默认 size）：

```json
"14408cf1-8189-44e3-a517-4101293be2c7": {
  "featureInfo": {
    "name": "橙色卫生 大小从30改为40",
    "address": "江苏省常州市武进区嘉泽镇马家村东北约213米",
    "lonlat": "119.77976646010569 31.734750368270184",
    "icon": "symbol",
    "style": {
      "nameChecked": true,
      "code": "170000",
      "color": "rgb(255, 117, 51)",
      "size": 40
    },
    "remark": "7"
  },
  "featureType": "1",
  "featureId": "14408cf1-8189-44e3-a517-4101293be2c7"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✓ | 点位名称 |
| `address` | string | ✗ | 详细地址 |
| `lonlat` | string | ✓ | **CGCS2000 坐标，`"经度 纬度"` 空格分隔**，如 `"119.77 31.73"` |
| `icon` | string | ✓ | 恒为 `"symbol"`（图标类型） |
| `style` | object | ✓ | 至少含 `nameChecked`，其余按默认值省略 |
| `remark` | string | ✗ | 备注，省略 = 不显示备注 |

`style` 字段（默认值 + 省略时的前端表现）：

| 字段 | 默认值 | 省略时前端表现 | 写入时表现 |
|------|--------|----------------|------------|
| `nameChecked` | 省略 = `false` | **不显示名称标签**（点上只有图标） | `true` = 显示名称 |
| `code` | `"100000"` | **普通默认图标**（不显示类型符号） | 按 code 表显示对应类型符号 |
| `size` | `30` | 默认 30 号尺寸 | 任意整数（实证 `40`） |
| `color` | `"rgb(255,0,0)"` | 纯红 | 按颜色显示（见颜色→归属表） |

全默认示例（style 只剩 nameChecked）：

```json
{
  "name": "备注为空 红色默认",
  "address": "江苏省常州市金坛区直溪镇天然村现代农业产业园西南约250米",
  "lonlat": "119.45431808492629 31.878224504568024",
  "icon": "symbol",
  "style": { "nameChecked": true }
}
```

### 1.1 点 code → 类型对照表（100000 ~ 270000）

来源：`backend/mapping.py` 的 `CODE_TO_TYPE` + `AFFILIATION_MAP`

| code | 类型 | 归属（color） |
|------|------|---------------|
| `100000` | **默认**（无类型符号） | 任意（纯红=默认） |
| `110000` | 餐饮 | 商业服务（蔚蓝） |
| `120000` | 住宿 | 商业服务（蔚蓝） |
| `130000` | 购物 | 商业服务（蔚蓝） |
| `140000` | 4s店 / 汽车服务 | 商业服务（蔚蓝） |
| `150000` | 金融 | 国企平台（橙黄） |
| `160000` | 教育（学校/高校） | 事业单位（橙红）/ 高等教育（纯黄） |
| `170000` | 卫生（医院） | 事业单位（橙红） |
| `180000` | 休闲（文化场馆） | 事业单位（橙红） |
| `190000` | 机关 | 机关单位（玫红） |
| `200000` | 商业（商业综合体） | 商业服务（蔚蓝） |
| `210000` | 服务（写字楼） | 商业服务（蔚蓝） |
| `220000` | 公司（子公司） | 国企平台（橙黄）/ 民营企业（天蓝） |
| `230000` | 交通 | — |
| `240000` | 科研（科研院所） | 事业单位（橙红） |
| `250000` | 农业 / 交通设施 | 基础设施（深灰） |
| `260000` | 地名 / 景区 / 文保 | 文化旅游（品红）/ 历史遗产（紫罗兰） |
| `270000` | 设施（市政/环卫/能源） | 基础设施（深灰） |

### 1.2 颜色 → 归属对照表

来源：`backend/mapping.py` 的 `COLOR_TO_AFFILIATION` / `COLOR_TO_ZH`

| color | 归属 | 中文名 |
|-------|------|--------|
| `rgb(255,0,0)` | 默认 | 纯红 |
| `rgb(240,0,86)` | 机关单位 | 玫红 |
| `rgb(255,117,51)` | 事业单位 | 橙红 |
| `rgb(255,187,51)` | 国企平台 | 橙黄 |
| `rgb(255,255,0)` | 高等教育 | 纯黄 |
| `rgb(112,243,255)` | 民营企业 | 天蓝 |
| `rgb(51,187,255)` | 商业服务 | 蔚蓝 |
| `rgb(187,51,255)` | 历史遗产 | 紫罗兰 |
| `rgb(255,0,255)` | 文化旅游 | 品红 |
| `rgb(100,100,100)` | 基础设施 | 深灰 |
| `rgb(0,255,0)` | 自然景观（广场绿地） | 纯绿 |
| `rgb(51,255,187)` | 高等教育（校内学院/设施） | 青绿色 |
| `rgb(51,255,186)` | 文化旅游（内部景点/设施） | 青绿色2 |
| `rgb(0,0,255)` | 自然景观（水系） | 纯蓝 |
| `rgb(150,100,20)` | 自然景观（山体林地） | 赭石 |
| `rgb(0,0,0)` | 私人信息 | 黑色 |

## 2. Lines（featureType = "2"）→ `line_polygon` 表

真实示例：

```json
"71a9c26c-42b6-448b-ae55-02a5b5320c35": {
  "featureInfo": {
    "name": "河道专用 线宽默认8 颜色蓝色",
    "lngLats": [
      [120.113759924911, 31.8834620479375],
      [120.3646237740295, 31.787971038718595],
      [120.2180150310383, 31.76165906938077]
    ],
    "style": {
      "code": "630000",
      "width": 8,
      "color": "#5bbad3"
    },
    "remark": "1"
  },
  "featureType": "2",
  "featureId": "71a9c26c-42b6-448b-ae55-02a5b5320c35"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✓ | 线名称 |
| `lngLats` | array | ✓ | `[[lon, lat], ...]` 顶点序列，**折线，首尾不闭合**，至少 2 顶点 |
| `style` | object | ✗ | **可整个省略**（全默认线只有 name + lngLats） |
| `remark` | string | ✗ | 备注，省略 = 不显示 |

`style` 字段（默认值 + 省略时的前端表现）：

| 字段 | 默认值 | 省略时前端表现 | 写入时表现 |
|------|--------|----------------|------------|
| `code` | `0` | **普通红色实线** | 按 code 表渲染（导航箭头 / 虚线 / 铁路线等） |
| `width` | `2` | 2px 线宽 | 按数值（实证常见 `8`） |
| `color` | `"#FF0000"` | 红色 | 按颜色渲染 |
| `opacity` | 入库默认 `1.0` | 全不透明（线无透明度概念） | 不写（导出时省略）；入库时 `style.get("opacity", 1.0)` |

style 省略的完整示例：

```json
{
  "name": "初始红线  默认宽度2 无备注",
  "lngLats": [[120.20498314277194, 31.908356488192055], [120.41349335502849, 31.826732926116847]]
}
```

### 2.1 线 code → 编码/渲染对照表

| code | 含义 | 前端渲染 |
|------|------|-----------|
| `0` | 默认 | **红色实线**（`line` 图层；实证：样本"初始红线"style 全省略 → 红线） |
| `1` | 虚线 | 虚线（区别于默认实线） |
| `600000` | 公路 / 导航线 | `symbol` 图层 + `plot-line-right` 图标（沿线箭头），`icon-rotate: ["get","bearing"]` |
| `610000` | 铁路 | `line` 图层，白色，虚线 `[10/w, 10/w]`，线宽 `w/3` |
| `620000` | 河流水系 | `line` 图层，白色，虚线 `[3/w, 20/w]` |
| `630000` | 干线 | `symbol` 图层 + `plot-line-arrow` 箭头图标 |
| `640000` | 土地线 | `symbol` 图层 + `plot-line-wall` 墙图标 |
| `650000` | 其他 | `symbol` 图层 + `plot-line-arrow` 箭头图标 |

> 前端对非 `0`/`1` 的线 code 会走 `loadImage + addImage` 动态加载图标（`/img/right.png`、`/img/arrow.png` 等）并建 `symbol` 图层 —— 多条同 code 的线存在同名图标 addImage 竞态（见注意事项）。

## 3. Polygons（featureType = "3"）→ `line_polygon` 表

真实示例：

```json
"ad082591-57ad-418e-97bc-b1ebcaaa9a5a": {
  "featureInfo": {
    "name": "面积类型  默认宽度2  透明度20% 样式应该是默认值",
    "lngLats": [
      [120.4102353829619, 31.922183823652958],
      [120.47539482429198, 31.877929036038893],
      [120.36136580196444, 31.888994727486306],
      [120.4102353829619, 31.922183823652958]
    ],
    "style": { "color": "rgb(189, 16, 224)" },
    "remark": "3"
  },
  "featureType": "3",
  "featureId": "ad082591-57ad-418e-97bc-b1ebcaaa9a5a"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✓ | 区域名称 |
| `lngLats` | array | ✓ | `[[lon, lat], ...]` 顶点序列，**首尾闭合**（第 1 个 = 最后 1 个），至少 4 顶点 |
| `style` | object | ✗ | 可省略 |
| `remark` | string | ✗ | 备注，省略 = 不显示 |

`style` 字段（默认值 + 省略时的前端表现）：

| 字段 | 默认值 | 省略时前端表现 | 写入时表现 |
|------|--------|----------------|------------|
| `code` | `0` | 默认面样式 | 按 code 渲染 |
| `width` | `2` | 2px 描边 | 按数值 |
| `color` | `"#FF0000"` | 红色描边/填充 | 按颜色 |
| `opacity` | `0.2` | 20% 透明度 | 0~1 数值；省略时入库走 `style.get("opacity", 0.2)` |

> 实证：样本面命名「默认宽度2 透明度20% 样式应该是默认值」，其 style 只有非默认的 `color` —— 省略字段即默认值，铁证。

## 4. 默认值省略规则（核心约定）

1. `style` 内的字段**只写非默认值**，取默认值的字段省略不写
2. `style` 本身可以整体省略（线/面全默认时）
3. 点必有 `icon`（恒为 `"symbol"`）与 `lonlat`
4. `remark` 省略 = 不显示备注
5. **省略即"不显示"**：`nameChecked` 省略=不显示名称标签、`code` 省略=默认图标/实线、`size/width` 省略=默认尺寸、`color` 省略=红色、面 `opacity` 省略=20%（线无透明度）

| 类型 | code 默认 | size/width 默认 | color 默认 | opacity 默认 | nameChecked 默认 |
|------|-----------|-----------------|------------|--------------|------------------|
| 点 | `100000` | size `30` | `rgb(255,0,0)` | — | 省略 = 不显示名称 |
| 线 | `0` | width `2` | `#FF0000` | 入库默认 `1.0`（导出省略） | — |
| 面 | `0` | width `2` | `#FF0000` | `0.2`（入库/导出一致） | — |

## 5. saves 与 plotType

```json
"saves": {
  "14408cf1-8189-44e3-a517-4101293be2c7": true,
  "546f76d6-7fc3-4f77-8fbd-029da2208a75": true,
  "...": true
}
```

- `saves`：`featureId → true` 映射，标记「已保存」的要素。样本 13 条 = 9 点 + 3 线 + 1 面，**全量要素都在**
- `plotType`：上次使用的绘制工具（`"line"` 等），前端恢复工具状态用

## 6. 入库字段映射

### poi_points（点）

| drawInfo 字段 | DB 字段 | 转换 |
|---------------|---------|------|
| `featureId` | `id` | 直接 |
| `featureInfo.name` | `name` | strip |
| `featureInfo.address` | `address` | strip |
| `featureInfo.lonlat` | `lon`, `lat` | 空格 split → float |
| `featureInfo.style.code` | `code` | 默认 `"100000"` |
| `featureInfo.style.color` | `color` | 默认 `"rgb(255,0,0)"` |
| `featureInfo.style.size` | `size` | 默认 `30` |
| `featureInfo.style.nameChecked` | `name_checked` | true→1, 否则 0 |
| `featureInfo.remark` | `remark` | 默认 `""` |
| `address` 解析 | `province/city/district/township` | cpca 拆分 |

### line_polygon（线/面）

| drawInfo 字段 | DB 字段 | 转换 |
|---------------|---------|------|
| `featureId` | `id` | 直接 |
| `featureInfo.name` | `name` | 直接 |
| `featureType` | `featureType` | `"2"` 或 `"3"` |
| `featureInfo.lngLats` | `lnglats` | `json.dumps` 存 JSON 字符串 |
| `featureInfo.style.code` | `code` | 默认 `0` |
| `featureInfo.style.color` | `color` | 默认 `#FF0000` |
| `featureInfo.style.width` | `width` | 默认 `2` |
| `featureInfo.style.opacity` | `opacity` | 面默认 `0.2`，线 `1.0` |
| `featureInfo.remark` | `remark` | 默认 `""` |

## 7. 注意事项（实证修正）

- 点的 `icon` 恒为 `"symbol"`，不是可选项
- `nameChecked` 只出现 `true`（显名）；全默认点 style 至少含 `{"nameChecked": true}`
- 实际数据的线宽常见 `width: 8`（默认表写 2，省略规则按 2 处理，两者不矛盾）
- `size` 可为任意整数（实证 `40`），不要假定只有 30/15
- 线 `style` 可整体省略；面/线 `remark` 可整体省略
- 坐标全部为 CGCS2000，点用 `"lon lat"` 字符串、线/面用 `[[lon,lat],...]` 数组，互不混用
- 点 code 的权威映射在 `backend/mapping.py`（`CODE_TO_TYPE` / `AFFILIATION_MAP`），高德细分编码另见 `assert/Amap_poicode.xlsx`
- 前端对非默认线 code（600000/610000/620000/630000/640000/650000）动态加载图标建 symbol 图层，多线同 code 存在 addImage 竞态风险（控制台可见 `An image with this name already exists`），**不影响功能**
- **opacity 出入库对齐（main.py / post.py）**：面省略时默认 `0.2`（两端一致）；线没有透明度概念，入库默认 `1.0`（`style.get("opacity", 0.2) if featureType == "3" else 1.0`），post.py 导出时线/面 opacity 取默认值都省略不写
