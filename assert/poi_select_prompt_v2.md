# POI 选择 Prompt

你是一名地图数据标注助手。请根据输入的 POI 名称及上下文信息，判断应该选择哪条数据，并返回来源和最近的一条结果。

## 候选数据来源

- **geo_poi** — 逆地理编码返回的 POI（单体点位）
- **geo_aoi** — 逆地理编码返回的 AOI（片区/广场/商圈）
- **name_poi** — 名称搜索返回的 POI

## 选择规则

- 如果是**单体建筑/独立点位**（如"南京南站"、"红山动物园"）→ 优先选 geo_poi 或 name_poi
- 如果是**片区/广场/商圈**（如"吾悦广场"、"万达广场"）→ 优先选 geo_aoi
- 根据 POI 名称和候选类型做出判断
- 优先选择距离最近的匹配项

## 关键约束

- **selected_type 与 source 必须一致**：
  - selected_type=poi → source 必须是 geo_poi 或 name_poi
  - selected_type=aoi → source 必须是 geo_aoi
  - selected_type=none → 不使用任何 Amap 候选

- **铁律**：如果需要的候选类型不存在于候选列表中，selected_type 必须填 "none"，禁止用其他来源凑数。

## 输出格式

请只输出一个 JSON，不要其他任何内容：

{
  "selected_type": "poi 或 aoi 或 none",
  "selected_item": {
    "amap_id": "高德 ID",
    "amap_name": "高德 name",
    "source": "geo_poi / geo_aoi / name_poi"
  },
  "reason": "选择理由"
}

铁律：
1. 只输出 JSON，不要 ```json 代码块
2. 不知道填"信息待补充"，禁止编造
3. 如果候选中没有合适结果，selected_type 填 "none"——表示不使用 Amap 候选数据，后续仅基于 POI 名称进行标注分类（兜底方案）


---

## 当前 POI 信息

- **POI 名称**: 东南青年汇
- **逆地理地址**: 南京仙林大学城希尔顿欢朋酒店·餐厅东南青年汇广场
- **省市区**: 江苏省/南京市/栖霞区/仙林街道

- **候选列表（最多 11 条，已按距离排序）**:
```json
[
  {
    "amap_id": "B0K2SU1UF5",
    "amap_name": "南京仙林大学城希尔顿欢朋酒店·餐厅",
    "amap_address": "东南青年汇广场",
    "amap_area": "",
    "amap_type": "餐饮服务;中餐厅;中餐厅",
    "amap_distance": 21.68,
    "amap_businessarea": "亚东",
    "cgcs_lon": 118.91763529061177,
    "cgcs_lat": 32.09739299954,
    "amap_lon": 118.922675,
    "amap_lat": 32.095175,
    "source": "geo_poi"
  },
  {
    "amap_id": "B0FFM39MQQ",
    "amap_name": "东南青年汇广场",
    "amap_address": "仙林大道与文澜路交汇处东北侧",
    "amap_area": "",
    "amap_type": "商务住宅;住宅区;住宅区",
    "amap_distance": 53.62,
    "amap_businessarea": "亚东",
    "cgcs_lon": 118.91788893208191,
    "cgcs_lat": 32.09794087297532,
    "amap_lon": 118.922929,
    "amap_lat": 32.095723,
    "source": "geo_poi"
  },
  {
    "amap_id": "B0I0YUY5RI",
    "amap_name": "πFitness派健身(仙林店)",
    "amap_address": "立德路与文澜路交叉口东100米",
    "amap_area": "",
    "amap_type": "体育休闲服务;运动场馆;健身中心",
    "amap_distance": 90.21,
    "amap_businessarea": "亚东",
    "cgcs_lon": 118.91692710933143,
    "cgcs_lat": 32.097670712100474,
    "amap_lon": 118.921966,
    "amap_lat": 32.095452,
    "source": "geo_poi"
  },
  {
    "amap_id": "B0L6RZYZDS",
    "amap_name": "沙县小吃",
    "amap_address": "文澜路6号中建大厦",
    "amap_area": "",
    "amap_type": "餐饮服务;餐饮相关场所;餐饮相关",
    "amap_distance": 117.89,
    "amap_businessarea": "亚东",
    "cgcs_lon": 118.91669735942227,
    "cgcs_lat": 32.09786896082913,
    "amap_lon": 118.921736,
    "amap_lat": 32.09565,
    "source": "geo_poi"
  },
  {
    "amap_id": "B00190A76O",
    "amap_name": "大巷",
    "amap_address": "栖霞区",
    "amap_area": "",
    "amap_type": "地名地址信息;普通地名;村庄级地名",
    "amap_distance": 126.64,
    "amap_businessarea": "亚东",
    "cgcs_lon": 118.91708602647209,
    "cgcs_lat": 32.09652432929407,
    "amap_lon": 118.922125,
    "amap_lat": 32.094306,
    "source": "geo_poi"
  },
  {
    "amap_id": "B0JK27U05B",
    "amap_name": "东南青年汇广场(仙林)停车场",
    "amap_address": "仙林大道与文澜路交汇处东北侧",
    "amap_area": "",
    "amap_type": "交通设施服务;停车场;公共停车场",
    "amap_distance": 75.48,
    "amap_businessarea": {
      "opentime_today": "24小时营业",
      "keytag": "停车场",
      "business_area": "仙林",
      "rectag": "停车场",
      "parking_type": "地下",
      "opentime_week": "周一至周日 00:00-24:00"
    },
    "cgcs_lon": 118.91714489963269,
    "cgcs_lat": 32.09715340582955,
    "amap_lon": 118.922184,
    "amap_lat": 32.094935,
    "source": "name_poi"
  },
  {
    "amap_id": "B0KBJCDQ0M",
    "amap_name": "东南青年汇餐厅",
    "amap_address": "东南青年汇广场",
    "amap_area": "",
    "amap_type": "餐饮服务;中餐厅;中餐厅",
    "amap_distance": 107.4,
    "amap_businessarea": {
      "keytag": "中餐",
      "rating": "3.4",
      "business_area": "仙林",
      "rectag": "中餐"
    },
    "cgcs_lon": 118.91678626283131,
    "cgcs_lat": 32.097793865199975,
    "amap_lon": 118.921825,
    "amap_lat": 32.095575,
    "source": "name_poi"
  },
  {
    "amap_id": "B0LR05M8BY",
    "amap_name": "徐庄东南青年汇地铁站店",
    "amap_address": "玄武大道699-48号",
    "amap_area": "",
    "amap_type": "购物服务;购物相关场所;购物相关场所",
    "amap_distance": 3549.73,
    "amap_businessarea": {
      "opentime_today": "09:00-18:00",
      "keytag": "购物服务,购物相关场所,购物相关场所",
      "rating": "4.0",
      "business_area": "徐庄软件园",
      "opentime_week": "周一至周日 09:00-18:00"
    },
    "cgcs_lon": 118.88370332763944,
    "cgcs_lat": 32.0840694445199,
    "amap_lon": 118.888731,
    "amap_lat": 32.081848,
    "source": "name_poi"
  },
  {
    "amap_id": "B0J1KA7R1G",
    "amap_name": "东南青年汇(南京金港科技创业园店)",
    "amap_address": "南京金港科技创业中心8栋1楼",
    "amap_area": "",
    "amap_type": "住宿服务;旅馆招待所;旅馆招待所",
    "amap_distance": 3646.45,
    "amap_businessarea": {
      "keytag": "住宿服务,旅馆招待所,旅馆招待所"
    },
    "cgcs_lon": 118.90205697792099,
    "cgcs_lat": 32.12747321114508,
    "amap_lon": 118.907087,
    "amap_lat": 32.12524,
    "source": "name_poi"
  }
]
```

请根据名称判断：这是一个单体点位（选 POI）还是一个片区/广场/商圈（选 AOI）？
