# 天地图POI点位管理系统 - 重构计划

## 项目目标

将 `tianmap_meta`（MongoDB + 单体应用）重构为 **前后端分离** 的 `tianmap-government` 项目，数据库改用 **SQLite**，便于后续运维部署。

## 源项目分析

| 维度 | 现状 |
|------|------|
| 数据库 | MongoDB（pymongo），集合 map_poi |
| 后端 | FastAPI 单文件 main.py，内嵌所有路由 |
| 前端 | 单文件 templates/index.html，内联 CSS + JS，由 FastAPI 直接返回 |
| 数据规模 | ~1.7 KB 级别，约数千个 POI 点位 |
| 外部依赖 | 天地图 API（数据源）、高德地图 API（坐标转换）、百度千帆 API（搜索） |
| Python 版本 | 3.12+，uv 包管理器 |

## 架构设计

### 分层原则

```
routers (API) → services (业务逻辑) → repository (数据访问抽象) → database (具体实现)
```

**关键约束**：`services` 只依赖 `repository` 的抽象接口，不依赖任何具体数据库。更换数据库只需新增一个 repository 实现，改一行配置即可。

```
tianmap-government/
├── backend/                    # 后端（FastAPI）
│   ├── main.py                 # 应用入口、路由注册
│   ├── config.py               # 环境变量、配置项（含 DATABASE_TYPE）
│   ├── models.py               # Pydantic 数据模型（DTO，不绑定任何数据库）
│   ├── repository/             # 数据访问层（抽象 + 实现）
│   │   ├── __init__.py         # 统一导出
│   │   ├── base.py             # 抽象基类（Protocol）
│   │   ├── sqlite_repo.py      # SQLite 实现
│   │   └── # 未来可加 mongo_repo.py、postgres_repo.py 等
│   ├── database/               # 数据库连接管理
│   │   ├── __init__.py
│   │   └── sqlite.py           # SQLite 连接、建表、迁移
│   ├── routers/
│   │   ├── poi.py              # POI 点位 CRUD
│   │   ├── import_.py          # 数据导入（URL/文件/天地图路径）
│   │   ├── stats.py            # 统计接口
│   │   ├── backup.py           # 备份管理
│   │   └── logs.py             # 日志接口
│   ├── services/
│   │   ├── poi_service.py      # POI 业务逻辑（增删改查）
│   │   ├── import_service.py   # 导入清洗逻辑（原 cleaner.py）
│   │   └── export_service.py   # 导出/备份逻辑
│   ├── mapping.py              # color→归属、code→类型 映射表
│   │   └── util.py             # 工具函数
│   ├── fetcher.py              # 天地图数据下载
│   ├── pyproject.toml
│   └── data/                   # SQLite 数据库文件存放
│       └── tianmap.db
├── frontend/                   # 前端（Vite + Vue 3）
│   ├── index.html
│   ├── src/
│   │   ├── main.js
│   │   ├── App.vue
│   │   ├── api/                # API 请求封装
│   │   │   ├── request.js      # fetch 封装
│   │   │   ├── poi.js
│   │   │   ├── stats.js
│   │   │   └── backup.js
│   │   ├── views/
│   │   │   ├── Dashboard.vue   # 统计面板
│   │   │   ├── ImportView.vue  # 导入面板
│   │   │   ├── BackupView.vue  # 备份管理
│   │   │   └── LogView.vue     # 实时日志
│   │   └── components/
│   │       ├── Toast.vue       # 通知组件
│   │       └── Modal.vue       # 弹窗组件
│   ├── package.json
│   └── vite.config.js
├── .env                        # 环境变量
├── .env.example                # 环境变量模板
└── docker-compose.yml          # 可选：Docker 部署
```

## 技术选型

| 层次 | 技术 | 理由 |
|------|------|------|
| 后端框架 | FastAPI | 与源项目一致，零学习成本 |
| 数据库（默认） | SQLite（aiosqlite） | 零运维、单文件、足够应对数千点位 |
| ORM | SQLAlchemy 2.0 (async) | 类型安全、异步支持、可切换后端 |
| 数据访问模式 | Repository + Protocol 抽象 | **业务层不依赖具体数据库** |
| 前端框架 | Vue 3 + Vite | 轻量、组件化、与后端完全分离 |
| 前端构建 | Vite | 开发体验好、构建快 |
| 包管理 | uv（后端） + npm（前端） | 各自生态 |
| CORS | 后端配置 CORS 中间件 | 前后端独立启动 |

## 数据模型

### Pydantic DTO（不绑定任何数据库）

```python
class POIPoint(BaseModel):
    id: str
    name: str = ""
    address: str = ""
    lon: float = 0.0
    lat: float = 0.0
    color: str = "rgb(255,0,0)"
    code: str = "100000"
    size: int = 30
    remark: str = ""            # 给人看的可读文本
    unit_type: str = ""         # 单位类型
    poi_type: str = ""          # POI细分类型
    amap_id: str = ""           # 高德POI ID
    amap_parent_id: str = ""    # 高德父节点ID
    province: str = ""
    city: str = ""
    district: str = ""
    phone: str = ""
    amap_type: str = ""         # 高德原始类型
    amap_raw: str = ""          # 高德原始JSON响应缓存
    created_at: datetime | None = None
    updated_at: datetime | None = None
    img_url: str = ""           # 图标图片URL
```

> 所有 `services` 和 `routers` 只使用这个 DTO，**不 import 任何数据库相关的类**。

### SQLite 表：poi_points

> **设计原则**：SQLite 存全部完整字段，不偷懒。高德搜索到的有用信息（高德ID、父节点、省市区、电话等）全部存下来，未来直接可用。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | TEXT | PRIMARY KEY, UNIQUE | 天地图 featureId |
| name | TEXT | | 点位名称 |
| address | TEXT | | 详细地址 |
| lon | REAL | | 经度（CGCS2000） |
| lat | REAL | | 纬度（CGCS2000） |
| color | TEXT | | 图标颜色 rgb() |
| code | TEXT | DEFAULT '100000' | 图标编码 |
| size | INTEGER | DEFAULT 30 | 图标大小 |
| remark | TEXT | | 人工可读备注（非JSON，给人看） |
| unit_type | TEXT | DEFAULT '' | 单位类型 |
| poi_type | TEXT | DEFAULT '' | POI细分类型 |
| amap_id | TEXT | DEFAULT '' | 高德POI ID（如 B0019098C1） |
| amap_parent_id | TEXT | DEFAULT '' | 高德父节点ID |
| province | TEXT | DEFAULT '' | 省份 |
| city | TEXT | DEFAULT '' | 城市 |
| district | TEXT | DEFAULT '' | 区/县 |
| phone | TEXT | DEFAULT '' | 电话 |
| amap_type | TEXT | DEFAULT '' | 高德原始类型（如 风景名胜;风景名胜;纪念馆） |
| amap_raw | TEXT | DEFAULT '' | 高德原始JSON响应（缓存，避免重复调用API收费） |
| img_url | TEXT | DEFAULT '' | 图标图片URL |
| created_at | DATETIME | DEFAULT now() | 创建时间 |
| updated_at | DATETIME | DEFAULT now() | 更新时间 |

**索引**：`idx_name` on name, `idx_poi_type` on poi_type, `idx_unit_type` on unit_type, `idx_amap_id` on amap_id

## Repository 抽象层

### 核心设计：Protocol 接口

```python
# repository/base.py
from typing import Protocol, Optional, List
from models import POIPoint

class POIRepository(Protocol):
    """数据访问抽象接口 - 更换数据库只需实现这个 Protocol"""

    # -- 查询 --
    async def get(self, fid: str) -> Optional[POIPoint]: ...
    async def get_many(self, fids: List[str]) -> List[POIPoint]: ...
    async def get_all(self) -> List[POIPoint]: ...
    async def paginate(self, page: int, page_size: int, order_by: str = "id") -> tuple[List[POIPoint], int]: ...
    async def search(self, keyword: str, fields: List[str] | None = None) -> List[POIPoint]: ...
    async def find(self, conditions: dict) -> List[POIPoint]: ...
    # -- 写入 --
    async def insert_one(self, point: POIPoint) -> None: ...
    async def upsert_one(self, point: POIPoint) -> None: ...
    async def update_one(self, fid: str, data: dict) -> None: ...
    async def bulk_upsert(self, points: List[POIPoint]) -> dict: ...
    async def bulk_insert(self, points: List[POIPoint]) -> dict: ...
    # -- 删除 --
    async def remove_one(self, fid: str) -> bool: ...
    async def remove_many(self, fids: List[str]) -> int: ...
    async def remove_all(self) -> None: ...
    # -- 统计 --
    async def count(self) -> int: ...
    async def count_by(self, field: str, value: str) -> int: ...
    async def group_by(self, field: str) -> dict: ...
    # -- 连接 --
    async def close(self) -> None: ...
```

### 更换数据库只需三步

1. 新增 `repository/postgres_repo.py`，实现 `POIRepository` Protocol
2. `.env` 中改 `DATABASE_TYPE=postgres`
3. `config.py` 工厂函数返回新实现

**业务层（services）零修改**。

### 当前 MongoDB → SQLite 操作对照（参考）

| MongoDB 操作 | SQLite 等价操作 |
|---|---|
| `collection.find({})` | `SELECT * FROM poi_points` |
| `collection.find_one({"id": fid})` | `SELECT * FROM poi_points WHERE id = ?` |
| `collection.insert_one(doc)` | `INSERT INTO poi_points ...` |
| `collection.update_one({"id": fid}, {"$set": doc})` | `UPDATE poi_points SET ... WHERE id = ?` |
| `collection.count_documents({})` | `SELECT COUNT(*) FROM poi_points` |
| `aggregate([{"$group": {"_id": "$type"}}])` | `SELECT type, COUNT(*) GROUP BY type` |
| `create_index("id", unique=True)` | `UNIQUE CONSTRAINT` |
| `insert_many(data, ordered=False)` | `INSERT OR IGNORE ...` / 批量插入 |

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/version` | 服务版本信息 |
| POI 点位 |
| GET | `/api/poi/{id}` | 单个点位详情 |
| GET | `/api/poi/list` | 分页列表（支持排序） |
| GET | `/api/poi/all` | 全量点位（天地图分享格式） |
| PUT | `/api/poi/{id}` | 更新单个点位 |
| PATCH | `/api/poi/{id}` | 部分更新点位字段 |
| DELETE | `/api/poi/{id}` | 删除单个点位 |
| POST | `/api/poi/batch/delete` | 批量删除 |
| POST | `/api/poi/search` | 关键词搜索（名称/地址/备注） |
| GET | `/api/poi/export` | 导出点位为 JSON 文件下载 |
| 导入 |
| POST | `/api/import/url` | 从 URL 下载并导入 |
| POST | `/api/import/file` | 本地文件上传导入 |
| POST | `/api/import/tianditu` | 天地图路径导入 |
| POST | `/api/import/data` | 直接传入 JSON 数据导入 |
| GET | `/api/import/history` | 导入历史记录 |
| 统计 |
| GET | `/api/stats/summary` | 总览统计（总数/类型/归属） |
| GET | `/api/stats/by_type` | 按 POI 类型统计 |
| GET | `/api/stats/by_unit_type` | 按单位类型统计 |
| GET | `/api/stats/by_region` | 按省市区统计 |
| 备份 |
| POST | `/api/backup/export` | 导出备份 |
| GET | `/api/backup/list` | 备份列表 |
| POST | `/api/backup/import` | 从备份恢复 |
| DELETE | `/api/backup/{filename}` | 删除备份 |
| POST | `/api/backup/cleanup` | 清理旧备份 |
| 日志 |
| GET | `/api/logs` | 最新日志 |
| GET | `/api/logs/stream` | SSE 实时日志 |

> 所有接口加 `/api` 前缀，与前端路由不冲突。

## Hermes Agent 智能标注 — 归属映射表

Hermes Agent 根据网络搜索结果判断 `unit_type` 和 `poi_type` 后，**自动推导** color、code、remark。
以下为反向映射规则，Agent 按此填充字段：

| unit_type (归属) | poi_type (细分) | color | code | 图标预览 |
|---|---|---|---|---|
| 临时点位 | - | rgb(255,0,0) | 100000 | 🔴 纯红 |
| 机关单位 | 地方政府部门 | rgb(240,0,86) | 190000 | 🩷 玫红 |
| 机关单位 | 垂直管理部门 | rgb(240,0,86) | 190000 | 🩷 玫红 |
| 事业单位 | 学校 | rgb(255,117,51) | 160000 | 🟠 橙红 |
| 事业单位 | 医院 | rgb(255,117,51) | 170000 | 🟠 橙红 |
| 事业单位 | 科研院所 | rgb(255,117,51) | 180000 | 🟠 橙红 |
| 事业单位 | 文化场馆 | rgb(255,117,51) | 180000 | 🟠 橙红 |
| 事业单位 | 其他 | rgb(255,117,51) | 180000 | 🟠 橙红 |
| 国企平台 | 一级集团 | rgb(255,187,51) | 150000 | 🟡 橙黄 |
| 国企平台 | 二级子公司 | rgb(255,187,51) | 220000 | 🔵 天蓝 |
| 国企平台 | 三级及以下子公司 | rgb(255,187,51) | 220000 | 🔵 天蓝 |
| 高等教育 | 本科高校 | rgb(51,255,187) | 160000 | 🟢 青绿 |
| 高等教育 | 科研院所 | rgb(51,255,187) | 240000 | 🟢 青绿 |
| 民营企业 | 民营独资 | rgb(112,243,255) | 220000 | 🔵 天蓝 |
| 民营企业 | 混合所有制 | rgb(112,243,255) | 220000 | 🔵 天蓝 |
| 商业服务 | 酒店 | rgb(51,187,255) | 120000 | 🔷 蔚蓝 |
| 商业服务 | 商场 | rgb(51,187,255) | 130000 | 🔷 蔚蓝 |
| 商业服务 | 购物 | rgb(51,187,255) | 130000 | 🔷 蔚蓝 |
| 商业服务 | 餐饮 | rgb(51,187,255) | 110000 | 🔷 蔚蓝 |
| 商业服务 | 住宿 | rgb(51,187,255) | 120000 | 🔷 蔚蓝 |
| 商业服务 | 商业综合体 | rgb(51,187,255) | 200000 | 🔷 蔚蓝 |
| 商业服务 | 写字楼 | rgb(51,187,255) | 200000 | 🔷 蔚蓝 |
| 商业服务 | 汽车服务 | rgb(51,187,255) | 140000 | 🔷 蔚蓝 |
| 文化旅游 | 5A景区 | rgb(255,0,255) | 260000 | 🩻 品红 |
| 文化旅游 | 4A景区 | rgb(255,0,255) | 260000 | 🩻 品红 |
| 文化旅游 | 中国历史文化名街 | rgb(255,0,255) | 260000 | 🩻 品红 |
| 历史遗产 | 全国重点文保单位 | rgb(187,51,255) | 260000 | 🟣 紫罗兰 |
| 历史遗产 | 省级文保单位 | rgb(187,51,255) | 260000 | 🟣 紫罗兰 |
| 历史遗产 | 市级文保单位 | rgb(187,51,255) | 260000 | 🟣 紫罗兰 |
| 历史遗产 | 县级文保单位 | rgb(187,51,255) | 260000 | 🟣 紫罗兰 |
| 其他分类 | 交通枢纽 | rgb(255,255,0) | 230000 | 🟡 明黄 |
| 其他分类 | 广场绿地 | rgb(0,255,0) | 100000 | 🟩 纯绿 |
| 其他分类 | 水系水域 | rgb(0,0,255) | 100000 | 🔵 纯蓝 |
| 其他分类 | 山体林地 | rgb(150,100,20) | 250000 | 🟤 赭石 |
| 其他分类 | 基础设施 | rgb(0,0,0) | 270000 | ⚫ 纯黑 |
| 其他分类 | 临时点位 | rgb(255,0,0) | 100000 | 🔴 纯红 |
| 其他分类 | 服务设施 | rgb(0,0,0) | 210000 | ⚫ 纯黑 |

### Hermes Agent 工作流程

```
现有POI点位 (name + lon/lat)
  → Hermes Agent 网络搜索 → 获取真实信息
  → 判断 unit_type + poi_type + remark
  → 查上表 → 自动填充 color + code
  → 高德API校验坐标 → 微调 lon/lat（如距离>50m则修正）
  → 调用 PUT /api/poi/{id} 更新数据
```

### remark 字段策略 — 为人服务，不为程序

`remark` 是**给人看的纯文本**，不是 JSON，不供程序解析。你扫一眼就知道这个点位是什么来头：

```
# 国企平台
"中国大唐集团 → 大唐国际 → 大唐江苏发电公司（三级子公司）"

# 事业单位（医院）
"公益二类，南京鼓楼医院集团，南京大学附属医院"

# 商业服务（酒店）
"五星级，洲际酒店集团管理，南京国资集团+上海绿地集团建设"

# 民营企业
"上汽集团控股，混合所有制"
```

- **SQLite 全量存**：高德ID、父节点、省市区、电话、高德原始类型等结构化信息各存各的字段
- **remark 自由写**：上级单位、等级、产业结构、合作院校等你关心的内容，Hermes Agent 帮我整理成一行可读文本
- **天地图ID管理**：天地图上的点位删了重建会生成新ID。旧ID留在数据库里，导入时靠 name + amap_id 匹配，不靠天地图ID。新天地图ID可以临时写到 remark 里标注 `"新ID: feature_xxx"`，拾取后替换

## 实施步骤

### 第一阶段：后端骨架 + 数据库抽象
1. 创建 `backend/` 目录结构和配置文件
2. 实现 `models.py` — Pydantic DTO（**不依赖任何数据库**）
3. 实现 `repository/base.py` — POIRepository Protocol 抽象接口
4. 实现 `database/sqlite.py` — SQLite 连接 + 建表
5. 实现 `repository/sqlite_repo.py` — SQLite 的具体实现
6. `config.py` 工厂函数：根据 `DATABASE_TYPE` 返回对应的 repository 实例

### 第二阶段：后端路由 + 业务逻辑
7. 实现 `services/poi_service.py` — 接收 repository 作为参数，只做业务逻辑
8. 实现 `routers/` — 所有 API 路由，通过 Dependency Injection 获取 repository
9. 迁移 `fetcher.py` — 天地图数据下载
10. 迁移 `cleaner.py` → `services/import_service.py` — 数据清洗入库
11. 迁移 `backup.py` → `services/export_service.py` — 备份导出
12. 迁移 `mapping.py` 和 `util.py`

### 第三阶段：前端开发
13. 初始化 Vite + Vue 3 项目
14. 实现 API 请求封装层
15. 实现 Dashboard（统计面板）
16. 实现 Import 面板（导入表单）
17. 实现 Backup 管理面板
18. 实现实时日志面板

### 第四阶段：联调与部署
19. 配置 CORS，前后端联调
20. 编写 .env.example 和启动脚本
21. 可选：docker-compose.yml 一键部署

## 运维优势

- **数据库解耦**：换数据库只需新增一个 repository 实现 + 改一行配置，业务代码零修改
- **单文件数据库**：默认 SQLite，`tianmap.db` 一个文件即全部数据
- **零数据库服务**：无需安装 MongoDB，降低运维成本
- **前后端分离**：后端 `uv run uvicorn` 启动 API，前端 `npm run dev` 启动管理界面
- **生产部署**：前端 `npm run build` 产出静态文件，可 Nginx 托管，反向代理 `/api` 到后端

## 天地图 API — 点位上传与分享

> 通过天地图官网分享功能逆向得出的 API，可用于不经过前端 UI 直接将点位数据保存到��图网站，生成公开分享链接。

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `https://map.tianditu.gov.cn/api/map/share` | 保存点位数据，生成分享 UUID |
| `GET` | `https://map.tianditu.gov.cn/api/map/share/{uuid}` | 获取已保存的点位数据 |

### POST /api/map/share — 上传点位

**请求格式**：

```
Content-Type: application/x-www-form-urlencoded

body: json={URL_ENCODED_JSON}
```

**JSON 结构**：

```json
{
  "drawInfo": {
    "points": {
      "<featureId>": {
        "featureInfo": {
          "name": "点位名称",
          "address": "详细地址",
          "lonlat": "<经度> <纬度>",
          "icon": "symbol",
          "style": { "nameChecked": true }
        },
        "featureType": "1",
        "featureId": "<featureId>"
      }
    },
    "saves": {
      "<featureId>": true
    }
  }
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `featureId` | string | 唯一标识，UUID 格式 |
| `name` | string | 点位显示名称 |
| `address` | string | 详细地址 |
| `lonlat` | string | 坐标，格式 `"经度 纬度"`（空格分隔，CGCS2000） |
| `icon` | string | 图标类型，`"symbol"` 为默认标记 |
| `featureType` | string | 固定 `"1"` |
| `saves[featureId]` | boolean | 必须为 `true`，否则不持久化 |

**响应**：返回 JSON，包含生成的 `uuid`，分享链接为：

```
https://map.tianditu.gov.cn/share/{uuid}
```

### GET /api/map/share/{uuid} — 获取已保存数据

直接 GET 请求即可返回完整的 `drawInfo.points` 数据。

### curl 示例 — 上传单个点位

```bash
MARKER_UUID=$(python3 -c "import uuid; print(uuid.uuid4())")

curl -X POST 'https://map.tianditu.gov.cn/api/map/share' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d "json=$(python3 -c "
import json, urllib.parse
data = {
  'drawInfo': {
    'points': {
      '${MARKER_UUID}': {
        'featureInfo': {
          'name': '测试点位',
          'address': '江苏省南京市玄武区',
          'lonlat': '118.796 32.060',
          'icon': 'symbol',
          'style': {'nameChecked': True}
        },
        'featureType': '1',
        'featureId': '${MARKER_UUID}'
      }
    },
    'saves': { '${MARKER_UUID}': True }
  }
}
print(urllib.parse.quote(json.dumps(data)))
")"
```

### curl 示例 — 批量上传点位

```bash
python3 -c "
import json, urllib.parse, uuid

points = [
    {'name': '点位A', 'lonlat': '118.796 32.060', 'address': '南京市A'},
    {'name': '点位B', 'lonlat': '118.800 32.070', 'address': '南京市B'},
    {'name': '点位C', 'lonlat': '118.810 32.080', 'address': '南京市C'},
]

pts = {}
saves = {}
for p in points:
    fid = str(uuid.uuid4())
    pts[fid] = {
        'featureInfo': {
            'name': p['name'],
            'address': p['address'],
            'lonlat': p['lonlat'],
            'icon': 'symbol',
            'style': {'nameChecked': True}
        },
        'featureType': '1',
        'featureId': fid
    }
    saves[fid] = True

data = {'drawInfo': {'points': pts, 'saves': saves}}
print(urllib.parse.quote(json.dumps(data)))
" | xargs -I{} curl -s -X POST 'https://map.tianditu.gov.cn/api/map/share' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d "json={}" | python3 -c "import sys,json; d=json.load(sys.stdin); print('Share:', 'https://map.tianditu.gov.cn/share/'+d.get('uuid','?'))"
```

### 注意事项

1. **不需要登录**，直接 POST 即可
2. 每个点位必须有唯一的 `featureId`（UUID 格式）
3. `saves` 中对应 key 必须设为 `true`，否则该点位不会持久化
4. `lonlat` 格式为**空格分隔**的 `"经度 纬度"`（CGCS2000 坐标系），不是逗号
5. 返回的分享链接**公开可访问**
6. 天地图上的点位删了重建会生成新 ID。旧 ID 留在数据库里，导入时靠 `name + amap_id` 匹配，不靠天地图 ID
7. 通过浏览器前端添加的 marker 只存在 Redux store（内存）中，必须点"分享"按钮才会 POST 到服务端。绕过前端直接调 API 可避免 UI 操作限制
