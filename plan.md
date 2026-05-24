# 天地图政府POI标注系统 - 计划

## 项目目标

从天地图分享数据中拾取 POI 点位，通过 **高德 API 校验坐标 + Hermes Agent 智能标注**，自动写入 SQLite 数据库，并提供 Web 管理界面。

---

## 当前架构

```
天地图分享数据 (CGCS2000)
    ↓ backend/main.py (CLI 导入)
SQLite poi_points 表
    ↓ backend/annotate.py (CLI 标注)
高德逆地理 + 名称搜索 (GCJ02)
    ↓ 坐标互转 CGCS2000 ↔ GCJ02
Hermes Agent 分类标注
    ↓ 入库
SQLite 更新（含变更记录）
    ↓
前端 (React 18 + Ant Design 5) ← FastAPI API → 数据查询/统计/备份
```

### 技术栈

| 层次 | 技术 | 说明 |
|------|------|------|
| 运行环境 | Python 3.13 + uv | 包管理 |
| 后端框架 | FastAPI | REST API |
| 前端框架 | React 18 + Vite + Ant Design 5 | 管理界面 |
| 状态管理 | zustand | 轻量状态管理 |
| 路由 | react-router-dom v6 | 前端路由 |
| HTTP 客户端 | axios | 前端 API 请求 |
| 数据库 | SQLite (aiosqlite) | 异步操作 |
| 后端框架 | FastAPI | REST API + JWT 认证 |
| HTTP 客户端 | aiohttp | 外部 API 请求 |
| 坐标转换 | 自定义算法 | CGCS2000 ↔ WGS84 ↔ GCJ02 |
| 地图 SDK | 天地图 JS API | POI/线/面可视化（未来） |
| 高德 API | 逆地理编码 v3 + 名称搜索 v5 | 坐标校验、POI/AOI 候选 |
| Agent | Hermes API | 网络搜索 + 分类标注 |
| 日志 | loguru | app.log (INFO) + app_detail.log (DEBUG) |

---

## 项目结构

```
tianmap-government/
  backend/
    main.py                # 天地图数据导入（CLI，增量模式）
    annotate.py            # POI 智能标注 pipeline（CLI）
    mapping.py             # 归属/类型 → color + code 映射表
    app/                   # FastAPI 服务层（新增）
      main.py              # FastAPI 应用入口，CORS，JWT 认证
      deps.py              # 依赖注入（当前用户、权限检查）
      middlewares/
        auth.py            # JWT 认证中间件
        logger.py          # 请求日志
      routers/
        __init__.py
        import_.py         # UUID 导入
        poi.py             # POI 查询/搜索/详情
        annotate.py        # 标注任务管理
        stats.py           # 统计
        backup.py          # 备份
        auth.py            # 登录/登出/修改密码
        user.py            # 用户管理
      services/
        import_service.py  # 导入逻辑
        poi_service.py     # POI 业务逻辑
        annotate_service.py # 标注任务调度
        backup_service.py  # 备份逻辑
        user_service.py    # 用户认证逻辑
    api/
      amap.py              # 高德 API 集成（逆地理 + 名称搜索 + 候选合并）
      hermes.py            # Hermes Agent API 封装
      config.py            # .env 环境变量加载
    util/
      coord.py             # CGCS2000/WGS84/GCJ02 坐标转换
      amap_codes.py        # 高德 POI 类型编码查表（Excel 源）
      address.py           # 地址解析（省市区街道）
      io.py / json.py      # 文件与 JSON 工具
      log.py               # loguru 统一配置
  frontend/                # React 18 前端（新增）
    index.html
    src/
      main.jsx
      App.jsx              # 路由 + 认证守卫
      api/
        request.js         # axios 封装（拦截器 + token）
        import.js
        poi.js
        stats.js
        backup.js
        auth.js
      store/
        useAuthStore.js    # 用户状态（zustand）
        useAppStore.js     # 应用全局状态
      views/
        Login.jsx            # 登录页
        Dashboard.jsx        # 统计面板
        PoiList.jsx          # POI 列表/搜索/筛选/详情
        PoiDetail.jsx        # POI 详情
        ImportView.jsx       # UUID 导入面板
        AnnotateView.jsx     # 标注管理（触发/进度/失败重试）
        BackupView.jsx       # 备份管理
        LogView.jsx          # 实时日志（SSE/轮询）
        Layout.jsx           # 侧边栏 + 顶栏布局
        MapView.jsx          # 天地图 SDK 可视化（未来）
      components/
        Layout.jsx           # 全局布局（侧边栏+顶栏）
        PageHeader.jsx       # 页面标题
        StatCard.jsx         # 统计卡片
        ConfirmModal.jsx     # 确认弹窗
        Toast.jsx            # 通知
        Empty.jsx            # 空状态
    package.json
    vite.config.js
  data/tianmap.db          # SQLite 数据库
  log/                     # 运行日志（app.log + app_detail.log）
  tmp/                     # 临时文件（高德返回数据缓存）
  assert/
    hermes_system/         # Agent 系统提示词（select_prompt, annotate_prompt）
    Amap_poicode.xlsx      # 高德 POI 类型编码源表
  test/
    test_coord.py          # 坐标转换精度测试
  .env                     # 环境变量
  pyproject.toml           # 项目配置
  README.md                # 使用文档
```

---

## 现有核心模块（已实现）

### main.py — 数据导入（CLI）

从天地图 API 下载分享数据，增量写入 SQLite。

- 增量模式：id 不存在 → INSERT；id 存在且 remark 不同 → UPDATE
- 坐标使用 CGCS2000（天地图坐标系）
- 解析地址获取省市区街道
- 默认处理 `main.py` 中配置的 UUID，可修改切换数据源

### annotate.py — 智能标注 Pipeline（CLI）

对数据库中未标注的 POI（`size = 30`）进行全流程标注。

1. 高德查询：并行发起逆地理编码 + 名称搜索，合并去重生成候选列表（最多 11 条）
2. 地址校验：对比 DB 存储的省市区与高德返回
3. Agent 选择：Hermes 判断 POI/AOI，匹配完整数据
4. Agent 标注：Hermes 网络搜索 + 分类标注
5. 统一入库：合并字段，计算 color/code，写入 record

支持 `-n N` / `--all`。

### mapping.py — 颜色映射

归属 + 细分类型 → (color, code) 映射表，覆盖 10 大分类 + 模糊匹配。

### amap.py — 高德集成

坐标转换链（Newton 迭代 GCJ02→WGS84，精度 0.01m），逆地理 + 名称搜索 + 候选合并去重。

### hermes.py — Agent 接口

HTTP 调用 Hermes API，JSON 提取与重试机制。

### 数据库表 poi_points

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | PRIMARY KEY，天地图 featureId |
| name | TEXT | 点位名称 |
| address | TEXT | 详细地址 |
| lon/lat | REAL | CGCS2000 坐标 |
| color/code | TEXT | 图标颜色/编码 |
| size | INTEGER | 30=未标注，15=已标注 |
| remark | TEXT | 人工可读备注 |
| province/city/district/township | TEXT | 行政区域 |
| affiliation/point_type/level/feature | TEXT | 标注结果 |
| parent_company/constructor | TEXT | 标注结果 |
| amap_id/amap_name/amap_address | TEXT | 高德匹配结果 |
| amap_type/amap_area/amap_distance | TEXT/REAL | 高德类型/面积/距离 |
| amap_businessarea | TEXT | 高德商圈（字符串或空） |
| cgcs_lon/cgcs_lat | REAL | CGCS2000 坐标（高德回转） |
| amap_lon/amap_lat | REAL | GCJ02 坐标 |
| record | TEXT | 变更记录（JSON，最多 2000 字符） |
| created_at/updated_at | TEXT | 时间戳 |
| name_checked | INTEGER | 名称是否已校验（0/1） |

---

## 实施状态与待办

### 后端服务层（新增）

- [ ] `backend/app/main.py` — FastAPI 应用入口，CORS，JWT 认证，路由注册
- [ ] `backend/app/deps.py` — 依赖注入（当前用户、权限检查）
- [ ] `backend/app/middlewares/auth.py` — JWT 认证中间件
- [ ] `backend/app/middlewares/logger.py` — 请求日志
- [ ] `backend/app/routers/__init__.py` — 路由统一导出
- [ ] `backend/app/routers/auth.py` — 登录/登出/修改密码
- [ ] `backend/app/routers/user.py` — 用户管理
- [ ] `backend/app/routers/import_.py` — UUID 导入接口（复用 main.py 逻辑）
- [ ] `backend/app/routers/poi.py` — POI 列表/分页/搜索/详情
- [ ] `backend/app/routers/annotate.py` — 标注任务管理（触发/进度/结果）
- [ ] `backend/app/routers/stats.py` — 统计接口（总数/类型/归属/区域）
- [ ] `backend/app/routers/backup.py` — 备份导出/列表/恢复/清理
- [ ] `backend/app/services/import_service.py` — 导入逻辑（从 main.py 抽离）
- [ ] `backend/app/services/poi_service.py` — POI 查询/搜索/分页逻辑
- [ ] `backend/app/services/annotate_service.py` — 标注任务调度（异步队列）
- [ ] `backend/app/services/backup_service.py` — 备份导出/恢复逻辑
- [ ] `backend/app/services/user_service.py` — 用户认证逻辑

### 前端管理界面（新增）

- [ ] `frontend/` — Vite + React 18 + Ant Design 5 项目初始化
- [ ] `frontend/src/api/` — API 请求封装层（axios + 拦截器 + token 管理）
- [ ] `frontend/src/store/` — zustand 状态管理（用户态、应用全局态）
- [ ] `frontend/src/views/Login.jsx` — 登录页
- [ ] `frontend/src/views/Layout.jsx` — 侧边栏 + 顶栏布局
- [ ] `frontend/src/views/Dashboard.jsx` — 统计面板（总点位数/类型/归属统计卡片）
- [ ] `frontend/src/views/PoiList.jsx` — POI 列表/搜索/筛选/分页
- [ ] `frontend/src/views/PoiDetail.jsx` — POI 详情（完整信息 + 变更记录）
- [ ] `frontend/src/views/ImportView.jsx` — UUID 导入面板
- [ ] `frontend/src/views/AnnotateView.jsx` — 标注管理（触发/进度/失败重试）
- [ ] `frontend/src/views/BackupView.jsx` — 备份管理（导出/列表/恢复/清理）
- [ ] `frontend/src/views/LogView.jsx` — 实时日志
- [ ] `frontend/src/views/MapView.jsx` — 天地图 SDK 可视化（未来）
- [ ] `frontend/src/components/` — 通用组件（StatCard, ConfirmModal, Empty, PageHeader 等）

### 认证体系（新增）

- [ ] 管理员账号：admin / admin123（首次登录后强制改密码）
- [ ] JWT token（HS256，有效期 24h），Bearer 认证
- [ ] `.env` 配置 JWT_SECRET
- [ ] 路由守卫：未登录 → 跳转登录页

### CLI 工具（保持现有）

- [x] `backend/main.py` — 天地图数据导入（points + lines/polygons 并发）
- [x] `backend/annotate.py` — POI 智能标注 pipeline
- [x] `backend/post.py` — 数据库 → 天地图 POST 分享（反向编码 + 创建新 UUID）
- [x] `backend/mapping.py` — 颜色映射表
- [x] `backend/api/amap.py` — 高德 API 集成
- [x] `backend/api/hermes.py` — Hermes Agent 接口
- [x] `backend/api/config.py` — 环境变量配置
- [x] `backend/util/coord.py` — 坐标转换（Newton 迭代）
- [x] `backend/util/amap_codes.py` — 高德编码查表
- [x] `backend/util/io.py` — 异步文件写入工具
- [x] `backend/util/log.py` — loguru 配置
- [x] `test/test_coord.py` — 坐标转换精度测试

### 数据表

- [x] `poi_points` — 点数据（4407+ 条）
- [x] `line_polygon` — 线/面数据（9+ 条，featureType="2"/"3"）

---

### CLI 工具

- [x] `backend/main.py` — 天地图数据导入（points + lines/polygons 并发）
- [x] `backend/annotate.py` — POI 智能标注 pipeline
- [x] `backend/post.py` — 数据库 → 天地图 POST 分享（反向编码 + 创建新 UUID）
- [x] `backend/mapping.py` — 颜色映射表

### 数据表

- [x] `poi_points` — 点数据（4407+ 条）
- [x] `line_polygon` — 线/面数据（9+ 条，featureType="2"/"3"）

---

## 关键设计决策

1. **CLI pipeline 不变**：标注是后台任务，保持现有 CLI 脚本不变，通过 API 触发
2. **SQLite 直连不绕 ORM**：表结构固定，sqlite3 内置模块足够，FastAPI 用 aiosqlite
3. **`size=30` 未标注 / `size=15` 已标注**：单一整数标记状态
4. **`record` 字段记录变更**：UPDATE 时对比关键字段，写入 JSON 变更记录
5. **日志文件轮转**：loguru `rotation="00:00" retention="7 days"`
6. **前端通过 API 管理**：不直接操作 DB，所有操作走 FastAPI 接口
7. **`--all` + 循环**：CLI 不依赖 cron，手动启动一次跑完全部
8. **标注 pipeline 解耦**：`run()` 函数可被 FastAPI 调用，未来加任务队列管理进度
9. **JWT 认证**：HS256，Bearer token，24h 有效期，前端 axios 拦截器自动附加 token
10. **前端路由守卫**：React Router Navigate，未登录跳转 /login
11. **React + Ant Design 5**：减少 UI 组件开发量，Ant Design Pro 风格布局
12. **天地图 SDK**：未来引入 JS API 渲染 POI/线/面，支持点聚合、缩放平移、弹窗详情
