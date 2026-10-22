# HP Printer Monitor（惠普打印机监控）

[![GitHub](https://img.shields.io/badge/GitHub-chjspp520%2Fhp__print-blue)](https://github.com/chjspp520/hp_print)
[![Version](https://img.shields.io/badge/version-1.0.2-green)](https://github.com/chjspp520/hp_print)

这是一个 Home Assistant 自定义集成，用于监控支持 EWS（嵌入式 Web 服务器）和 SNMP 的惠普打印机，提供墨量、打印/扫描/复印/传真页数、卡纸事件、设备状态等丰富指标，并自动按日/月/年统计用量、推断今日打印作业。

## 功能特性

- **墨量与耗材监控**：实时监测青、品红、黄、黑四色墨水的剩余量、累计用墨量、HP 原装用墨量、更换墨盒次数、墨盒状态与序列号。
- **页数统计**：覆盖打印、扫描、复印、传真四大应用场景，细分黑白/彩色、单面/双面、ADF 扫描/平台扫描、网络/无线打印等维度。
- **设备状态监控**：通过 SNMP 获取设备状态、打印机状态与错误状态。
- **事件日志**：读取打印机事件日志，将事件码映射为可读中文描述（卡纸、墨盒故障、缺纸等），并提供总条数与逐条明细。
- **用量统计**：自动生成 **每日/每月/每年** 用量列表，涵盖打印/扫描/复印/传真/卡纸，`daylist` 另含四色墨水剩余量；`total` 直接取自打印机累计值；首次配置时会从 HA 历史记录**自动回填**历史数据。
- **今日作业记录**：根据累计计数器的增减推断今日发生的打印/扫描/复印/传真作业（含时长与页数），并精确记录当日卡纸事件（带真实时间戳）。
- **全部实体汇总**：将本设备下所有实体的 `entity_id`、`name`、`icon`、`state` 汇总为一个传感器的属性，便于外部系统一次性获取。
- **数据持久化**：用量统计与作业记录均保存到 `.storage/` 下的 JSON 文件，HA 重启不丢失。
- **手动按钮**：提供"补齐历史用量"与"重新加载用量数据"两个按钮，方便回填或重新读取存储数据。

## 工作原理

集成通过两条路径获取打印机数据：

1. **HTTP + XML（EWS）**：请求打印机的 `http://<IP>/DevMgmt/ProductUsageDyn.xml`（用量数据）与 `/DevMgmt/ProductLogsDyn.xml`（事件日志），解析 XML 得到各类累计计数器与耗材信息。
2. **SNMP v1**：通过 UDP 查询标准 MIB OID，获取设备状态、打印机状态与错误状态。使用内置的**纯 Python SNMP 客户端**（仅依赖标准库，无需额外安装 pysnmp）。

两类数据通过 `DataUpdateCoordinator` **并行采集**后合并，统一按配置的轮询间隔刷新。

## 建议搭配"房间精灵"卡片使用

本集成可与**房间精灵**卡片（地址：https://github.com/chjspp520/room-elves-card）配合，一站式展示打印机各项数据。在卡片配置中添加：

```yaml
type: printer
name: HP OfficeJet Pro 7730
entity: sensor.hp_printer_yong_liang_tong_ji
today_print: sensor.hp_printer_jin_ri_zuo_ye_ji_lu
width: 400px
```

> 其中 `entity` 对应"用量统计"传感器（含 `daylist`/`monthlist`/`yearlist`/`total`/`lik` 属性），`today_print` 对应"今日作业记录"传感器。

## 建议搭配"HA 数据统一存储系统"使用

本集成可与 **HA 数据统一存储系统（ha_data_store）**（地址：https://github.com/chjspp520/ha_data_store）配合，对打印机各类数据进行**长期数据存储**，便于后续追溯与统计。

ha_data_store 可将本集成生成的传感器数据（页数、墨量、用量统计、作业记录等）统一采集并持久化，突破 Home Assistant recorder 默认存储期限的限制，实现历史数据的长期留存与分析。

## 安装

1. 将 `hp_print` 文件夹复制到 Home Assistant 配置目录的 `custom_components/` 下：

   ```
   <config>/custom_components/hp_print/
   ```

2. 重启 Home Assistant。
3. 前往 **设置 → 设备与服务 → 添加集成**，搜索 **HP Printer**。

> 提示：集成依赖 Home Assistant 的 `recorder` 历史记录组件，用于首次自动回填历史用量。请确保 recorder 正常工作且传感器历史数据存在。

## 配置

通过 UI 完成配置，支持以下选项：

| 配置项 | 说明 | 默认值 | 范围 |
| --- | --- | --- | --- |
| 主机（Host） | 打印机 IP 地址 | —（必填） | — |
| 设备名称（Name） | 用于标识设备的显示名称 | `HP Printer` | — |
| 轮询间隔（Scan Interval） | 数据刷新间隔（秒） | `60` | 10 – 3600 |
| 每日记录保留天数（Daylist Days） | `daylist` 中保留的每日记录条数 | `90` | 7 – 730 |

配置完成后可通过设备页面的"齿轮"图标**重新配置**（如更换 IP 或调整轮询间隔）。

## 支持的实体

### 传感器（Sensor）

#### 墨量与耗材（四色 × 6 项）

针对青（Cyan）、品红（Magenta）、黄（Yellow）、黑（Black）四色各生成：

| 传感器 | 说明 | 单位 |
| --- | --- | --- |
| 墨水剩余 | 墨水剩余百分比 | % |
| 累计用墨量 | 累计标记剂用量 | ml |
| HP 原装墨量 | 累计 HP 原装标记剂用量 | ml |
| 更换墨盒次数 | 累计更换墨盒次数 | 次 |
| 墨盒状态 | 墨盒状态文本（如 OK / 故障） | 文本 |
| 序列号 | 墨盒序列号 | 文本 |

#### 打印引擎页数

| 传感器 | 说明 |
| --- | --- |
| 引擎页面总数 | 引擎累计总印量 |
| 黑白打印页数 | 黑白印量 |
| 彩色打印页数 | 彩色印量 |
| 单面打印页数 | 单面印量 |
| 双面打印页数 | 双面印量 |
| 打印卡纸次数 | 累计卡纸事件数 |
| 打印拾纸错误次数 | 累计拾纸错误数 |
| EWS 访问次数 | Web 访问次数 |
| 网络打印页数 | 网络打印印量 |
| 无线打印页数 | 无线打印印量 |

#### 扫描/复印/传真

| 传感器 | 说明 |
| --- | --- |
| ADF 扫描页数 / 平台扫描页数 / 总扫描图像数 | 扫描相关 |
| 扫描卡纸次数 / 扫描拾纸错误次数 | 扫描故障 |
| 总复印页数 / 彩色复印页数 / 黑白复印页数 | 复印相关 |
| 总传真页数 / 彩色传真页数 / 黑白传真页数 | 传真相关 |

#### 打印应用页数

| 传感器 | 说明 |
| --- | --- |
| 打印应用总页数 | 打印应用累计总页数 |
| 照片打印页数 | 照片打印页数 |

#### 状态传感器

| 传感器 | 说明 |
| --- | --- |
| 设备状态 | SNMP 设备状态（运行中 / 警告 / 停机等） |
| 打印机状态 | SNMP 打印机状态（空闲 / 打印中 / 预热中等） |
| 错误状态 | SNMP 错误状态（正常 / 错误码） |
| 事件日志 | 事件日志总条数（state），明细在 attributes 中按时间列出（含事件码、中文描述、发生次数、页数） |

#### 用量统计传感器

| 传感器 | 说明 |
| --- | --- |
| 用量统计 | state = `print` + `scan` + `copy` + `fax` + `jam_printer` 的累计合计值；attributes 含 `daylist` / `monthlist` / `yearlist` / `total` / `lik` |

属性结构说明：

- **`daylist`**：每日增量列表，最新在前。每项含 `day`、`print`、`scan`、`copy`、`fax`、`jam_printer`，以及四色墨水剩余量 `ink_black` / `ink_cyan` / `ink_magenta` / `ink_yellow`（带 `%` 单位，为该日快照值）。
- **`monthlist`**：每月增量列表，最新在前。每项含 `month`、`print`、`scan`、`copy`、`fax`、`jam_printer`（不含墨水字段）。
- **`yearlist`**：每年增量列表，最新在前。每项含 `year`、`print`、`scan`、`copy`、`fax`、`jam_printer`（不含墨水字段）。
- **`total`**：直接取自打印机上报的累计值，不做列表合计；四色墨水剩余量带 `%` 单位。
- **`lik`**：四色墨水明细，每项含 `color`、`remaining`（`%`）、`replace_count`（`次`）、`total_usage`（`ml`）、`status`。

示例：

```yaml
state: 9926
daylist:
  - day: "2026-10-21"
    print: 2
    scan: 0
    copy: 0
    fax: 0
    jam_printer: 0
    ink_black: "75%"
    ink_cyan: "68%"
    ink_magenta: "70%"
    ink_yellow: "72%"
monthlist:
  - month: 2026-10
    print: 35
    scan: 4
    copy: 0
    fax: 0
    jam_printer: 1
yearlist:
  - year: "2026"
    print: 8757
    scan: 1015
    copy: 154
    fax: 0
    jam_printer: 3
total:
  print: 8757
  scan: 1015
  copy: 154
  fax: 0
  jam_printer: 3
  ink_black: "75%"
  ink_cyan: "68%"
  ink_magenta: "70%"
  ink_yellow: "72%"
lik:
  - color: black
    remaining: "75%"
    replace_count: "3次"
    total_usage: "42ml"
    status: OK
```

#### 今日作业记录传感器

| 传感器 | 说明 |
| --- | --- |
| 今日作业记录 | state = 今日作业总条数；attributes 含 `print`/`scan`/`copy`/`fax`（作业列表，含时间区间、页数、时长）与 `jam_printer`（卡纸事件） |

#### 全部实体传感器

| 传感器 | 说明 |
| --- | --- |
| 全部实体 | state = 本设备下实体数量；attributes 含 `count` 与 `entities` 列表，每项包含 `entity_id`、`name`、`icon`、`state` |

示例：

```yaml
state: 42
count: 42
entities:
  - entity_id: sensor.hp_printer_cai_se_da_yin_ye_shu
    name: 彩色打印页数
    icon: mdi:printer
    state: "8757"
  - entity_id: sensor.hp_printer_mo_shui_sheng_yu
    name: 墨水剩余
    icon: mdi:water-percent
    state: "75"
```

> 该传感器会随每次数据刷新重新读取设备下所有实体的最新状态，方便外部系统（如 ha_data_store）批量采集。

### 按钮（Button）

| 按钮 | 说明 |
| --- | --- |
| 补齐历史用量 | 从 HA 历史记录重新回填用量统计的每日/每月/每年列表 |
| 重新加载用量数据 | 从存储 JSON 文件重新加载用量数据（手动编辑文件后使用） |

## 事件码说明

集成内置了常见打印机事件码到中文描述的映射，包括：

- **卡纸**：`15.00.00` 未知卡纸
- **墨盒故障/缺墨/空墨盒**：`17.x.00 / 17.x.60 / 17.x.80`（Black/Cyan/Magenta/Yellow）
- **原装耗材**：`17.99.40` 已安装原装 HP 耗材
- **纸盒尺寸不匹配**：`41.03.01 / 41.03.02`

未知事件码会显示为 `未知事件 (代码)`。

## 存储文件

集成在 Home Assistant 的 `.storage/` 目录下持久化数据（每个配置条目一个文件）：

- `hp_print.period_usage_<entry_id>.json`：用量统计（`baselines` / `daylist` / `monthlist` / `yearlist`）
- `hp_print.today_jobs_<entry_id>.json`：今日作业记录

## 常见问题

### 传感器显示"不可用"或长时间无数据

- 确认打印机 IP 可达，且已开启 EWS（嵌入式 Web 服务器）。
- 确认打印机型号支持 `ProductUsageDyn.xml` 接口（多数支持 EWS 的惠普打印机均支持）。
- 查看 HA 日志中是否有 `ProductUsageDyn.xml fetch failed` 或 SNMP 相关错误。
- 注意：部分打印机 EWS 接口不支持 HTTPS，集成使用 HTTP 协议访问。

### 状态传感器无值

- SNMP 需要打印机开启 SNMP（社区字符串默认 `public`）。若打印机未开启 SNMP，状态类传感器会缺失，但其余传感器不受影响。

### 用量统计没有历史数据

- 首次配置时集成会从 recorder 历史自动回填。若回填为空，可能是历史记录中缺少对应传感器数据，可点击"补齐历史用量"按钮手动回填。

## 技术说明

- **无第三方依赖**：SNMP 客户端为纯 Python 标准库实现，集成不依赖 pysnmp 等外部库。
- **并行采集**：用量 XML、事件日志 XML 与 SNMP 状态通过 `asyncio.gather` 并行获取，各自独立容错。
- **重试机制**：XML 接口请求失败自动重试 3 次。
- **容错设计**：某个数据源失败不影响其他数据源，仅导致相关传感器不可用。
- **`local_polling` IOT 类型**：数据通过轮询获取，属于本地轮询类集成。

## 兼容性

- 针对支持 EWS（`ProductUsageDyn.xml`）与 SNMP 的惠普激光/喷墨打印机设计。
- 主要面向具备四色墨盒（CMYK）的彩色打印机，但黑白机亦可正常使用（墨量传感器仅返回存在的数据）。
- **已测试机型**：HP OfficeJet Pro 7720、7730、7740。其他机型未实测，理论上支持 EWS 与 SNMP 的机型均可使用，如有问题可在集成仓库中反馈。

## 目录结构

```
hp_print/
├── __init__.py        # 集成入口、协调器初始化、配置更新监听、全部实体传感器
├── manifest.json      # 集成元数据
├── const.py           # 常量、传感器定义、事件码映射
├── config_flow.py     # 配置流程（添加/重新配置）
├── coordinator.py     # DataUpdateCoordinator，XML+SNMP 数据采集
├── sensor.py          # 传感器平台
├── button.py          # 按钮平台（回填/重载）
├── snmp_client.py     # 纯 Python SNMPv1 客户端
├── period_usage.py    # 用量统计（日/月/年 + 历史回填）
├── today_jobs.py      # 今日作业记录推断
├── strings.json       # 配置流程字符串
├── translations/      # 多语言翻译（en / zh-Hans）
└── brand/             # 品牌图标
```

## 更新日志

### 1.0.2

- 修复「用量统计」中日/月/年条目重复的问题：写入改为按周期键更新（upsert），并在加载存储时自动去重排序，已有脏数据会自动修复。
- 适配新版设备注册表 API，改用 `async_get_device_by_identifier`，消除 `async_get_device` 弃用警告（保留对旧版 HA 的回退支持）。

### 1.0.1

- 新增「全部实体」传感器，汇总本设备所有实体的 `entity_id`、`name`、`icon`、`state`。
- 「用量统计」state 改为 `print` + `scan` + `copy` + `fax` + `jam_printer` 的合计值。
- 「用量统计」`daylist` 增加四色墨水剩余量（带 `%` 单位）与卡纸次数。
- 新增墨水信息属性 `lik`，各字段带单位（`%` / `次` / `ml`）。
- 优化历史回填逻辑：修正实体 ID 解析、修正阻塞调用、回填时跳过当天并由实时计算接管。
- 更新仓库信息（codeowners / documentation / issue_tracker）。

## 反馈与支持

- 仓库地址：https://github.com/chjspp520/hp_print
- 问题反馈：https://github.com/chjspp520/hp_print/issues
- 维护者：[@chjspp520](https://github.com/chjspp520)
