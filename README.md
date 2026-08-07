# 天地图政府POI标注系统

天地图 POI 数据导入 + 高德坐标校验 + Hermes Agent 智能标注一体化 pipeline。

## 环境准备

```bash
# 安装依赖
uv sync
```

确保 `.env` 文件已配置（项目根目录）：

```bash
# 高德 API key
AMAP_KEY=your_key
AMAP_RADIUS=2000
AMAP_MAX_RETRIES=3

# Hermes Agent 服务地址
HERMES_HOST=0.0.0.0
HERMES_PORT=8643
HERMES_KEY=12345678
HERMES_MAX_RETRIES=3
HERMES_MAX_TOKENS=1024
```

## 启动方式

### 1. 天地图数据导入

从天地图下载分享数据，增量写入 SQLite：

```bash
cd /data/openclaw/tianmap-government
uv run python backend/main.py
```

默认处理 `main.py` 中配置的 UUID，修改该变量可切换数据源。

- **增量模式**：id 不存在 → INSERT；id 存在且 remark 不同 → UPDATE
- 坐标使用 CGCS2000（天地图坐标系）
- 并发处理 points（POI 点）和 lines/polygons（线/面）

### 2. POI 智能标注

对数据库中未标注的 POI（`size = 30`）进行全流程标注：

```bash
# 处理 1 条
uv run python -m backend.annotate -n 1

# 处理 10 条
uv run python -m backend.annotate -n 10

# 处理全部（自动循环直到没有未标注数据）
uv run python -m backend.annotate -n 100 --all
```

**标注流程**：
1. 高德逆地理 + 名称搜索（并行），合并去重生成候选列表
2. 地址校验（对比 DB 存储与高德返回）
3. Hermes Agent 选择 POI/AOI
4. Hermes Agent 网络搜索 + 分类标注
5. 统一入库，记录变更

### 3. 坐标转换精度测试

```bash
uv run python backend/test/test_coord.py
```

### 4. 数据库 → 天地图分享（POST）

从数据库读取 POI/线/面数据，反向编码为天地图分享 JSON，POST 创建新分享：

```bash
uv run python backend/post.py
```

- 输出新 UUID 和分享链接
- 从 `poi_points` 和 `line_polygon` 表读取数据
- 按 `assert/templete.json` 模板 + `assert/template.md` 编码规则生成（默认值省略）
- **自动按省份切批**：点按 `province`、线面按 `s_province` 分为「江苏省 / 其他」两批，
  每批独立创建分享（服务端解码后 ~1MB / 约 2600 点上限），payload 落盘 `tmp/gen_url/`

#### 最新分享批次（2026-08-07）

| 批次 | 内容 | 链接 |
|------|------|------|
| jiangsu | 1876 点 + 6 线 + 1 面 | https://map.tianditu.gov.cn/share/f16b4221a9964b9e97ca96b67e87d760 |
| other | 2581 点 + 2 线（杭州马拉松/潜江马拉松） | https://map.tianditu.gov.cn/share/93dd3e1c1c0a4145804b9af2a3b79136 |

## 后台运行（nohup）

### POST 分享

```bash
nohup uv run python backend/post.py > /dev/null 2>&1 &
echo $! > log/post.pid

# 停止
kill $(cat log/post.pid)
```

### 天地图导入

```bash
nohup uv run python backend/main.py > /dev/null 2>&1 &
echo $! > log/import.pid

# 查看日志
tail -f log/app.log

# 停止
kill $(cat log/import.pid)
```

### POI 标注（全部）

```bash
nohup uv run python -m backend.annotate -n 100 --all > /dev/null 2>&1 &
echo $! > log/annotate.pid

# 查看日志
tail -f log/app.log

# 停止
kill $(cat log/annotate.pid)
```

### 日志说明

| 文件 | 级别 | 内容 |
|------|------|------|
| `log/app.log` | INFO | 核心流程：导入统计、入库结果 |
| `log/app_detail.log` | DEBUG | 中间数据：高德返回、Agent 交互、重试细节 |

日志每天轮转，保留 7 天。

## 表结构

### `poi_points` — 点数据

| 字段 | 说明 | 字段 | 说明 |
|------|------|------|------|
| `id` | featureId | `name` | 点位名称 |
| `lon`, `lat` | CGCS2000 坐标 | `address` | 地址 |
| `color`, `code`, `size` | 样式 | `remark` | 备注 |
| `name_checked` | 名称显示标记 | `province/city/district/township` | 行政区域 |
| `amap_*` | 高德匹配结果 | `created_at/updated_at` | 时间戳 |

### `line_polygon` — 线/面数据

| 字段 | 说明 | 字段 | 说明 |
|------|------|------|------|
| `id` | featureId | `name` | 线/面名称 |
| `lnglats` | JSON `[[lon,lat],...]` | `featureType` | "2"=线, "3"=面 |
| `width`, `opacity`, `color`, `code` | 样式 | `remark` | 备注 |
| `s_*` / `e_*` | 起终点行政区域（`s_province` 用于导出切批） | `created_at/updated_at` | 时间戳 |

## 项目结构

```
tianmap-government/
  backend/
    main.py                # 天地图数据导入（增量模式）
    post.py                # 数据库 → 天地图分享 POST（按省切批，创建新 UUID）
    annotate.py            # POI 智能标注 pipeline
    mapping.py             # 归属/类型 → color + code 映射表
    api/
      amap.py              # 高德 API（逆地理 + 名称搜索 + 候选合并）
      hermes.py            # Hermes Agent 接口
      config.py            # .env 环境变量
    util/
      coord.py             # CGCS2000/WGS84/GCJ02 坐标转换（Newton 迭代）
      amap_codes.py        # 高德 POI 编码查表（Excel 源）
      address.py           # 地址解析
      io.py                # 文件工具
      log.py               # loguru 配置
    test/
      test_coord.py        # 坐标转换精度测试
  data/
    tianmap.db             # SQLite 数据库（生产）
    tianmap copy.db        # 数据库备份/副本
  log/                     # 运行日志
  tmp/
    raw_url/               # main.py 下载的分享原始数据
    gen_url/               # post.py 待上传 payload
    update/                # main.py 入库变更日志
  assert/
    hermes_system/         # Agent 系统提示词
    Amap_poicode.xlsx      # 高德类型编码源表
    code.png               # 编码对照图
    template.md / templete.json  # 天地图分享格式文档（入库解析 + 导出编码）/ 模板
  .env                     # 环境变量
  pyproject.toml           # 项目配置
```

## 数据流转

```
天地图分享数据 (CGCS2000)
    ↓ main.py
SQLite poi_points / line_polygon 表
    ↓ annotate.py
高德逆地理 + 名称搜索 (GCJ02)
    ↓ 坐标互转 CGCS2000 ↔ GCJ02
Hermes Agent 选择 POI/AOI
Hermes Agent 网络搜索 + 分类标注
    ↓ 入库
SQLite 更新（含变更记录）
    ↓ post.py（点按 province、线面按 s_province 切批）
天地图 API POST → 新 UUID（江苏省 / 其他，各一批）
```

## 坐标系统

```
CGCS2000（天地图）
    ←→ WGS84（GPS）
    ←→ GCJ02（高德）

转换链：
CGCS2000 → WGS84 → GCJ02    （天地图 → 高德查询）
GCJ02 → WGS84 → CGCS2000    （高德返回 → 写回数据库）

精度：gcj02_to_wgs84 使用 Newton 迭代，10 次迭代精度 0.01m
```

## 关键设计

- **`size` 标记状态**：30 = 未标注，15 = 已标注
- **增量去重**：main.py 以 `id` 判断是否已存在，`remark` 不同才更新，避免重复写入
- **`record` 字段**：每次更新对比关键字段（name/省市区/归属/类型），写入 JSON 变更记录
- **`--all` 循环**：不依赖 cron，启动一次自动跑完全部未标注数据
- **日志文件直写**：loguru 直写文件，不受 nohup 重定向影响
- **SQLite 单文件**：`data/tianmap.db` 即全部数据，复制即备份
- **分享 1MB 限制**：天地图创建/保存分享解码后 JSON ~1MB（约 2600 点）上限，超限 HTTP 500；前端分享按钮同限（源码实证）
- **导出按省切批**：post.py 点按 `province`、线面按 `s_province` 分为 江苏省/其他 两批，规避 1MB 上限