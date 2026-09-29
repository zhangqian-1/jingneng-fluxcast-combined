> 历史记录：旧96点和8步优化入口已于2026-09-23移除。当前接入请以 [项目说明](../README.md) 和 [联合封装说明](../deploy/forecast-dispatch/README.md) 为准。

> 历史接口记录，已由2026-09-20全场站UTC接口替代，不能作为当前调用约定。

# Fluxcast 平台实时接口使用说明

本文档对应平台对接方 2026-08-24 的《平台对接改造需求—算法侧》。实时接口采用已确认的方案 B：平台逐站上报，服务聚合七站数据，收齐后只执行一次七站联合优化，再按请求 `source_id` 返回该站结果。原有 `/compute` 离线调试接口保留，但不属于本实时契约。

## 请求

```text
POST /api/v1/fluxcast/compute?source_id={场站编码}
Content-Type: application/json
```

`source_id` 是必填整数。新版多厂信息表确认：`2=JYRD`、`3=JQRD`、`4=JFRD`、`5=GARD`、`6=JXRD`、`7=WLRD`、`8=SZRD`。默认已内置，可由 `SOURCE_ID_MAP_JSON` 或 `SOURCE_ID_MAP_FILE` 显式配置，但必须与正式七站映射一致。

请求体：

```json
{
  "point_table": [
    "GARD_11MBY0100000BJ01XQ01",
    "GARD_12MBY0100000BJ01XQ01",
    "GARD_13MKA01CE903BJ01XQ01"
  ],
  "frames": [
    {
      "timestamp": "2026-09-20 00:00:00",
      "GARD_11MBY0100000BJ01XQ01": 125.3,
      "GARD_12MBY0100000BJ01XQ01": 130.1,
      "GARD_13MKA01CE903BJ01XQ01": 180.5
    }
  ]
}
```

示例只展示一个 frame，正式请求必须恰好包含96个 frame，覆盖同一自然日00:00至23:45，相邻15分钟、严格递增且不得重复。`timestamp` 接受空格分隔或ISO8601；内部按 Asia/Shanghai 解释无时区值并转换成UTC比较。结果时间戳逐站使用该站请求中的原字符串，不擅自改变格式。

`point_table` 必须包含本次 `source_id` 对应站的全部必填测点。每帧必须包含相同必填字段。平台转义规则只把原始编码中的 `.` 替换成 `_`，例如 `JYRD_LOADCTL:GTMWSEL1_1.OUT` 传成 `JYRD_LOADCTL:GTMWSEL1_1_OUT`。值必须是非负有限浮点数。

正式测点见 [measurement-points.csv](measurement-points.csv)，测点名称和归属按文件中的明细执行。

19个新能源场站预测可通过请求体 `renewable_data` 透传原始长表；未透传时使用配置的预测提供器。当前测试默认读取随包 `202609180800` 批次文件，也可显式配置原有HTTP宽表适配接口。来源在调用前确定，失败后不会自动回退其他来源。完整规则见文末“原始新能源预测接入”。

## 聚合状态响应

前六站或新能源尚未齐全时返回 HTTP 202：

```json
{
  "source_id": 2,
  "status": "pending",
  "event_key": "JYRD.Fluxcast.Compute",
  "batch_key": "时间轴哈希",
  "missing_stations": ["JXRD", "SZRD", "WLRD"],
  "renewable_status": "ready"
}
```

并发请求发现另一进程正在求解时仍返回202，`status` 为 `solving`。`event_key` 严格采用 `{场站标识}.Fluxcast.Compute`。

## 完成响应

第七站触发联合求解后返回 HTTP 200；其他场站用相同内容重试时读取同一缓存结果：

```json
{
  "source_id": 2,
  "status": "completed",
  "result_point": [
    {
      "varname": "JYRD_MW",
      "timestamp": "2026-09-20 00:00:00",
      "value": 240.0,
      "period": 1
    }
  ],
  "event_key": "JYRD.Fluxcast.Compute",
  "batch_key": "时间轴哈希",
  "metadata": {
    "solver_mode": "highs",
    "stations": 7,
    "periods": 96,
    "returned_station": "JYRD",
    "global_kpis": {}
  }
}
```

正式响应有96个 `result_point`。`value` 一律为有限浮点数，`period` 固定为1（不是第1至96个时段的序号）；同一调度变量跨96个时间戳出现，记录唯一性由 `(varname,timestamp)` 保证。全局成本和碳排放保存在 `metadata.global_kpis`，不冒充单站指标。

待平台确认：原始需求写的是 `varname` 本身唯一，而当前96点曲线采用同一变量名配96个不同时间戳。两种约定并不完全相同，不能在未确认前声称此项已按原文字面验收，也不应擅自给变量名追加时段编号。

## 错误码

| HTTP | error_code示例 | 含义 |
|---:|---|---|
| 400 | `MISSING_SOURCE_ID` / `INVALID_JSON` | 缺必填查询参数或JSON无法解析 |
| 404 | `UNKNOWN_SOURCE_ID` | `source_id` 不在正式七站映射中 |
| 408 | `BATCH_TIMEOUT` | 聚合等待超过默认300秒；旧批次已清空，需重新上报 |
| 409 | `BATCH_INPUT_CONFLICT` | 求解中或已完成批次收到不同内容 |
| 422 | `INVALID_REALTIME_INPUT` | 非96点、时间轴错误、必填测点定义缺失等结构错误 |
| 422 | `REQUEST_VALIDATION_ERROR` | 请求模型或查询参数类型不符合约定；可解析的source_id仍在错误体中保留 |
| 422 | `INVALID_RENEWABLE_FORECAST` | 新能源结构、场站标识或时间轴错误 |
| 424 | `RENEWABLE_UPSTREAM_UNAVAILABLE` | 上游新能源预测算法不可用或响应无法解析 |
| 503 | `PLATFORM_CONFIGURATION_ERROR` | 七站ID映射、静态参数、目录权限或批次数据库不可用 |
| 503 | `DISPATCH_SOLVE_FAILED` | 求解器依赖、可选Gurobi许可证或模型求解失败 |

错误体统一返回 `error_code`、中文 `detail`、`source_id`、`batch_key`，不包含堆栈、业务文件路径、上游URL凭据或许可证内容。

## 运行配置

预测来源：`RENEWABLE_FORECAST_MODE=file` 为随包测试文件；`http` 模式必须配置 `RENEWABLE_FORECAST_URL`。请求透传 `renewable_data` 时使用请求数据。七站正式ID默认内置，可选 `SOURCE_ID_MAP_JSON` 或 `SOURCE_ID_MAP_FILE` 显式配置。`DISPATCH_SOLVER` 默认 `highs`，可选 `gurobi`，`auto` 等同 `highs`。`HIGHS_TIME_LIMIT_SECONDS` 和 `GUROBI_TIME_LIMIT_SECONDS` 默认300秒，`BATCH_SOLVING_LEASE_SECONDS` 默认600秒，应大于求解和制图总时限。选择Gurobi时才需要 `GRB_LICENSE_FILE`。生产不接受请求侧选择fallback；fallback只供离线调试。

## 数据与故障处理


数值异常按已约定的“上一有效值优先、新能源首点超容量按上限、无法补齐返回空结果”规则处理，并记录工作日志；原始输入保持不变。结构错误明确拒绝，求解失败不会改用启发式基线返回成功结果。

### 输入校验

单站请求必须含96个15分钟点，覆盖同一自然日00:00—23:45。时间戳乱序、重复、跨日、间隔错误或必填测点定义缺失返回422。测点值缺失、布尔值、非数值、非有限值或负值优先沿用上一有效值；没有可用前值时返回HTTP200、status=unavailable及null结果。`point_table` 可列额外字段，但当前站全部正式字段必须存在且不得重复。平台的点号转下划线规则在解析入口统一处理。

新能源预测送入求解器前必须形成19×96矩阵，每个值非负、有限且不超过 `config/renewable_capacities.json` 的装机容量。原始数值异常按上一有效值处理；新能源首点超容量且无前值时采用配置上限，仍无法补齐必要输入时返回unavailable空结果。结构或时间轴错误返回422；HTTP提供器的网络错误、超时、HTTP错误或JSON不可解析返回424。请求数据、文件和HTTP提供器之间不因错误自动切换；显式配置文件模式时只使用文件实际覆盖的目标日期。

### 七站聚合

同一成本版本内，相同标准化UTC时间轴生成相同批次键。当前成本版本为 `generation_includes_fuel_v1`，不会复用升级前的结果。已收到但尚未收齐时返回202，并列出缺少的场站；另一个进程已取得求解权时返回202 `solving`。相同站、相同时间轴、相同内容重复上报属于幂等请求。批次仍在收集中时，同站新内容替换旧版本并增加修订号；批次进入求解或完成后，任何不同内容返回409，防止结果与输入版本错配。

成本字段现按“发电成本含燃料”核算，气费估算不计入总成本。旧字段兼容关系、看板更新和部署要求见 [成本口径升级说明](cost-accounting-update.md)。平台七站96点输入、逐站结果和状态码结构不变。

等待窗口默认300秒，从首站首次写入开始计时。超时请求返回408，并原子清空未完成批次；随后七站需重新上报，不能把超时前的旧站数据和新数据拼接。完成和失败记录默认保留7天，可按部署配置清理。

### 求解和输出

生产平台路由默认运行HiGHS（无需许可证），可显式配置Gurobi。HiGHS仅接收在设定MIP gap内的最优结果，超时可行解仍按失败处理。许可证不可用、依赖加载失败、模型无解、求解异常、结果不是96点、缺少任一站输出或出现非有限值，都返回503并把批次标记为失败。错误响应不返回异常堆栈、服务器路径或许可证内容。

求解后必须通过既有输出校验：七站出力之和、系统功率平衡、开停状态、在线Pmin/Pmax、正常/启停爬坡、每日最多一次启动和一次停机、购售电分摊合计。任何校验失败均不得保存为成功结果。

### 日初状态

若SQLite中存在该场站早于本调度窗、且批次已完成的最近有效96点输入，使用其末点作为日初状态；不使用收集中或失败批次。否则使用本次00:00原始场站汇总值作为窗前状态。在线值按场站Pmin/Pmax夹紧后进入机组状态，离线阈值沿用原算法“大于1 MW为在线”。日初已在线只是状态，不计作当日启动。这只是日初状态推断，不等于现场确认的初始条件；当前未携带窗前连续开停时长。

### 平台处置建议

收到202时按固定间隔重试相同请求，不修改内容。收到408后协调七站重新上报同一日完整数据。收到409时停止自动覆盖并核对批次版本。收到422时修正源数据后重建该日批次。收到424时检查新能源预测服务。收到503时检查求解器状态、可选Gurobi许可证、目标架构依赖、模型日志和静态配置，不能自动改用fallback对外返回。


## 2026-09-19：原始新能源预测接入

七站请求体新增可选 `renewable_data`，为19个场站原生接口 `data` 数组的合并列表。每个场站仍只上传自己的燃机 `point_table` 与96个 `frames`；七个请求中的新能源数据必须一致。示意记录（不是完整请求）：

```json
{"farmId":1,"predictedTime":"202609200015","predictedPower":12.3,"timeSeries":2,"batch":"202609180800"}
```

- 有 `renewable_data` 时优先使用请求数据；数值异常按上一有效值及首点上限规则处理并记日志，不能补齐时返回HTTP200、unavailable和null结果；结构错误返回422，不改用文件或HTTP。
- 未提供时，使用配置的文件或既有HTTP宽表提供器。文件默认目录为 `INPUT_PATH/新能源场站预测输入数据`；原生GET接口不等于原有POST宽表接口，不能仅替换URL直接调用。
- 原始 `predictedTime` 必须为北京时间结束时刻，适配时只减15分钟一次。燃机 `frames.timestamp` 与旧宽表仍是开始时刻，不作偏移。
- 按转换后的目标调度日期选择19×96点，不固定 `timeSeries=1`。例如9月20日取本批的第2天。
- `farmId`、批次、重复点、连续时段、缺失值均校验；同批请求预测不一致返回409，已完成结果不会被静默覆盖。
- 响应 `metadata.renewable_forecast_batch` 标识原始批次；旧宽表没有此信息时为null。
- 文件仅支持它实际覆盖的日期，超出日期范围没有必要输入时返回unavailable空结果。`RENEWABLE_FORECAST_DAY` 仅控制离线情景，不会强行改变实时请求日期。
- HTTP202表示等待，HTTP200需区分completed（有效数值）与unavailable（无有效结果、value为null）；结构错误422、上游不可用424、求解失败503。不能仅凭HTTP200执行调度。


## 异常值沿用、首点上限及空结果（2026-09-19更新）

实时燃机测点和新能源预测的缺失、空值、非有限值、负值或新能源超容量值，使用**同一测点/同一farmId上一有效时段的值**；连续异常持续沿用，正常值恢复后立即使用新值。0是有效值。原始请求和预测文件不改写。

首点超过新能源场站容量且无前值时，按配置容量上限计算并记日志。新能源原始长表若包含同批次中目标日之前紧邻的15分钟有效点，可优先用于首点替代；不从其他场站借值、不向后取值。首点空值、缺失、负值或非有限值仍无前值时，实时接口返回HTTP200、`status=unavailable`、`metadata.dispatch_valid=false`，请求站96点value均为null；同批其他站同步无有效结果，补齐后才能恢复计算。整站缺失、未知ID、重复点、错误时间轴、不同批次混合或求解失败，不用单个前值掩盖。

接口完成响应 `metadata.input_quality` 包含 `policy`、`status`（original/substituted）、`renewable_replacements` 和 `thermal_replacements`。计数按本次七站输入的不同替代点统计，不累加重试次数。

工作日志默认 `output/logs/work.jsonl`，可设置 `WORK_LOG_PATH`。每行是一个JSON对象，包含记录时间、处理策略、测点/场站、异常时段、原值、原因、替代值及来源时段；求解开始/完成/失败、接口等待/完成/拒绝也记入日志。重复请求各自留痕。替代记录表示输入处理，不代表调度已完成。日志无法写入时返回503 `WORK_LOG_UNAVAILABLE`，避免无记录地继续。

历史CSV离线情景沿用原有清洗口径；新能源文件入口使用同一替代规则。详情见 [异常处理说明](input-quality-policy.md)。

空值schema、日志字段及预测批次确认办法见 [当前处理规则](input-quality-policy.md)。当前规则优先于本报告较早的异常行为说明。
