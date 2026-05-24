# Points 解析入库规则

## 数据源

天地图分享 API：`https://map.tianditu.gov.cn/api/map/share/{uuid}`

返回的 JSON 中，`drawInfo.points` 是一个 keyed object（key = featureId）。

## Points 结构

```
{
  "featureId": "xxx",              // 唯一标识
  "featureType": "1",              // "1" = 点，"2" = 线，"3" = 面
  "featureInfo": {
    "name": "xxx",                 // 点位名称
    "address": "xxx",              // 详细地址
    "lonlat": "104.5 31.5",        // CGCS2000 坐标，空格分隔（经度 纬度）
    "icon": "symbol",              // 图标类型（通常 "symbol"）
    "style": {                     // 样式（始终存在，省略的字段走默认值）
      "nameChecked": true,         // 是否显示名称标签（true=显示，false/无）
      "code": "100000",            // 符号编码（可选，默认 100000=不显示）
      "size": 30,                  // 标注点尺寸（可选，默认 30=不显示）
      "color": "rgb(255,0,0)"    // 图标颜色（可选，默认 rgb(255,0,0)=不显示）
    },
    "remark": "xxx"                // 备注（可选，省略则默认 ""=不显示）
  }
}
```

### 省略对象

`style` 对象始终存在，其中的字段按需出现，取默认值的字段省略不写：
- `code` 省略 → 默认 `100000`（普通图标）
- `size` 省略 → 默认 `30`（标注点尺寸）
- `color` 省略 → 默认 `rgb(255,0,0)`（红色）

`featureInfo` 中的 `remark` 字段同样省略不写：
- `remark` 省略 → 默认 `""`（不显示备注）

## 字段映射（入库 poi_points 表）

| 字段 | 来源 | 转换逻辑 |
|------|------|----------|
| `id` | `featureInfo.featureId` | 直接使用 |
| `name` | `featureInfo.name` | strip()，空则跳过 |
| `address` | `featureInfo.address` | strip()，空则 "" |
| `lon` | `featureInfo.lonlat` 前半 | float，CGCS2000 经度 |
| `lat` | `featureInfo.lonlat` 后半 | float，CGCS2000 纬度 |
| `code` | `featureInfo.style.code` | 默认 "0" |
| `color` | `featureInfo.style.color` | 默认 "rgb(255,0,0)" |
| `size` | `featureInfo.style.size` | 默认 30（=未标注状态） |
| `remark` | `featureInfo.remark` | 默认 "" |
| `name_checked` | `featureInfo.style.nameChecked` | true→1, false→0 |
| `province` | `address` 解析 | cpca 解析 |
| `city` | `address` 解析 | cpca 解析 |
| `district` | `address` 解析 | cpca 解析 |
| `township` | `address` 解析 | cpca 解析 |
| `affiliation` | 归属（对标color） | 默认 "" |
| `point_type` | 类型（对标code） | 默认 "" |
| `level` | agent搜索 | 默认 "" |
| `feature` | agent搜索 | 默认 "" |
| `parent_company` | agent搜索 | 默认 "" |
| `constructor` | agent搜索 | 默认 "" |
| `amap_id` | 高德匹配 | 默认 "" |
| `amap_name` | 高德匹配 | 默认 "" |
| `amap_address` | 高德匹配 | 默认 "" |
| `amap_area` | 高德匹配 | 默认 "" |
| `amap_type` | 高德匹配 | 默认 "" |
| `amap_distance` | 高德匹配 | 默认 0.0 |
| `amap_businessarea` | 高德匹配 | 默认 "" |
| `cgcs_lon` | 高德转换 | CGCS2000 经度 |
| `cgcs_lat` | 高德转换 | CGCS2000 纬度 |
| `amap_lon` | 高德返回 | GCJ02 经度 |
| `amap_lat` | 高德返回 | GCJ02 纬度 |
| `img_url` | - | 默认 "" |
| `record` | 变更记录 | 默认 "" |
| `created_at` | 创建时间 | ISO format |
| `updated_at` | 更新时间 | ISO format |

---

## Lines 结构

```
{
  "featureId": "xxx",              // 唯一标识
  "featureType": "2",              // "2" = 线
  "featureInfo": {
    "name": "xxx",                 // 线名称
    "lngLats": [                   // 顶点坐标序列（CGCS2000，[[经度,纬度], ...]）
      [104.3155, 28.4448],
      [103.5895, 25.3701],
      [108.4297, 24.1062]
    ],
    "style": {                     // 样式（可不存在，省略的字段走默认值）
      "code": "630000",            // 线状符号编码（可选，默认 0=实线）
      "width": 8,                  // 线宽（可选，默认 2）
      "color": "#5bbad3"           // 描边颜色（可选，默认 #FF0000=红色）
    },
    "remark": "xxx"                // 备注（可选，省略则默认 ""=不显示）
  }
}
```

### code 编码表（lines）

| code | 含义 | 示例 |
|------|------|------|
| `0` | 默认 | 红实线 |
| `1` | 默认/普通 | 红虚线 |
| `600000` | 公路/主干道 | 导航线 |
| `610000` | 铁路 | 铁路线 |
| `620000` | 河流水系 | 河道线 |
| `630000` | 干线 | 蓝底黑箭头 |
| `640000` | 土地线 | 土地线 |
| `650000` | 其他 | 灰底黑箭头 |

### 顶点规则

- `lngLats` 是 `[[lon, lat], ...]` 二维数组
- **line 不闭合**：首尾坐标不同，是折线
- 至少 2 个顶点

### 省略对象

`style` 对象可不存在，其中的字段按需出现，取默认值的字段省略不写：
- `code` 省略 → 默认 `0`（实线）
- `width` 省略 → 默认 `2`（线宽）
- `color` 省略 → 默认 `#FF0000`（红色）

`featureInfo` 中的 `remark` 字段同样省略不写：
- `remark` 省略 → 默认 `""`（不显示备注）

---

## Polygons 结构

```
{
  "featureId": "xxx",              // 唯一标识
  "featureType": "3",              // "3" = 面
  "featureInfo": {
    "name": "xxx",                 // 区域名称
    "lngLats": [                   // 顶点坐标序列（CGCS2000，[[经度,纬度], ...]）
      [95.9662, 23.5528],
      [96.3292, 25.7521],
      [98.7493, 24.6573],
      [98.0233, 21.6538],
      [95.9662, 23.5528]            // 首尾闭合（与第一个点相同）
    ],
    "style": {                     // 样式（可不存在，省略的字段走默认值）
      "code": "830000",            // 面样式编码（可选，默认 0=一般用这个样式足够）
      "width": 3,                  // 描边宽度（可选，默认 2）
      "color": "#66CCFF",        // 描边/填充颜色（可选，默认 #FF0000=红色）
      "opacity": 0.38              // 透明度 0~1（可选，默认 0.2）
    },
    "remark": "xxx"                // 备注（可选，省略则默认 ""=不显示）
  }
}
```

### 省略对象

`style` 对象可不存在，其中的字段按需出现，取默认值的字段省略不写：
- `code` 省略 → 默认 `0`（实线）
- `width` 省略 → 默认 `2`（线宽）
- `color` 省略 → 默认 `#FF0000`（红色）
- `opacity` 省略 →  `0.2`（透明度）

`featureInfo` 中的 `remark` 字段同样省略不写：
- `remark` 省略 → 默认 `""`（不显示备注）

### 顶点规则

- `lngLats` 是 `[[lon, lat], ...]` 二维数组，顺序为 `[经度, 纬度]`
- **polygon 首尾闭合**：第一个和最后一个坐标相同
- 至少 4 个顶点（3 个几何点 + 1 个闭合点 = 4 条边）

