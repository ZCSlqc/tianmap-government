# 天地图项目当前状态

## 已完成

### backend/models.py
Pydantic POIPoint DTO，包含所有字段：id, name, address, lon, lat, color, code, size, remark, unit_type, poi_type, amap_id, amap_parent_id, province, city, district, phone, amap_type, amap_raw, img_url, created_at, updated_at

### backend/fetcher.py
TiandituClient 天地图 API 客户端：
- upload_points(points: list[dict]) -> dict — 上传点位，生成分享 UUID
- get_points(uuid: str) -> dict — 获取已保存点位
- get_share_link(uuid: str) -> str — 生成分享链接

### 已有文件（Claude Code 上次看过）
- backend/pyproject.toml — 项目配置 + 依赖
- backend/database/__init__.py — 数据库包入口
- backend/database/schema.sql — SQLite 建表语句
- backend/database/sqlite.py — SQLite 连接管理
- backend/repository/__init__.py — Repository 包入口
- backend/repository/base.py — POIRepository Protocol 抽象
- backend/repository/sqlite_repo.py — SQLite 具体实现

## 待完成（按 plan.md）

### 第一阶段
- [x] models.py
- [x] fetcher.py
- [ ] config.py — 环境变量、配置项
- [ ] mapping.py + util.py — 颜色/类型映射工具

### 第二阶段
- [ ] services/poi_service.py
- [ ] services/import_service.py
- [ ] services/export_service.py
- [ ] routers/ — 所有 API 路由
- [ ] main.py — 应用入口

## 参考
- plan.md 在项目根目录，包含完整的数据模型、API 设计、Repository 抽象、天地图 API 格式说明
