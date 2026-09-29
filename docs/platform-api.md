# 平台接口约定与实现（2026-09-29增加字符串返回）

本说明以用户第一份[接口约定原文](requirements/platform-contract-20260919.md)为首要依据，结合用户明确确认的“96帧为历史实测、末帧当前、优化下一时段”。其余两份文件只补充不冲突的要求，不恢复逐站source_id或新造请求结构。完整核对见[修复记录](平台接口依据核对与修复-20260923.md)。

## 1. 原入口与请求

`POST /api/v1/fluxcast/compute`，`Content-Type: application/json`。一次提交全场站。三个必填顶层字段保持不变：

```json
{
  "point_table": ["GARD_11MBY0100000BJ01XQ01", "其余测点见清单"],
  "frames": [
    {"timestamp": "2026-09-21 10:00:00", "GARD_11MBY0100000BJ01XQ01": 125.3}
  ],
  "renewable_data": [
    {"farmId": 1, "predictedTime": "202609211830", "predictedPower": 50.0, "timeSeries": 1, "batch": "202609200800"}
  ]
}
```

上面只是字段节选，不能直接调用；必须提供完整96帧和完整19站长表。可复核的完整历史请求见 [examples/README.md](../examples/README.md) 与随包 `联调记录/platform-request.json`。平台照原方式从新能源预测系统获取19个data数组后合并为 `renewable_data`；算法不访问新能源取数接口，不轮询、不在缺数据时重新抓取，也不从随包历史文件补造在线新能源预测。

2026-09-27确认：`renewable_data` 是在线新能源预测的唯一输入来源。该字段缺失、为空、为null或场站不完整时返回422及空result_point。七站单点功率预测继续由算法内部调用包内forecast服务；`FORECAST_BASE_URL` 只配置这一服务，不配置新能源接口。两种预测职责见[来源确认](新能源数据来源确认-20260927.md)。

| 字段 | 校验与含义 |
|---|---|
| point_table | 原预测35测点：19功率、8温度、8湿度；可含额外测点，不得重复。见[原名/转义名清单](forecast-measurement-points.csv) |
| frames | 恰好96帧，UTC、连续升序，每15分钟一帧；末帧为当前实测，允许跨日，不要求自然日00:00开始 |
| 帧测点键 | 扁平字段。接受原始点号或约定的 `.`→`_` 名称；冒号保留。同一测点两种名称同时出现视为冲突 |
| renewable_data | 合并后的原始长表，19场齐全、同一batch；可直接传每场10天960点。算法只使用timeSeries=1，其他日不替代首日 |

预测调用只选取原模型35个测点，平台附带的其他测点不会送给原模型触发未知测点错误。

不新增 `actual`、`forecast_request`、`renewable_forecast` 等平台必填字段。不使用 `source_id` 逐站调用，携带该查询参数返回422。测点清单来自原预测交付样例，不是另拟的业务接口。

历史缺测保持原始输入给预测服务，由原模型处理；优化侧只对燃机功率沿用已有的前值修复规则。无合法前值时拒绝，不能把缺测造为实测零值。天气缺测由原模型原规则处理。

## 2. 时间对齐与预测初始化

设历史末帧为UTC `2026-09-21 10:00:00`，本次目标为UTC `10:15:00`，建议对应10:15—10:30时段。新版预测必须恰好返回该目标时刻的1点，该点原值进入本次求解；旧版96点输出会被拒绝。

新能源的 `predictedTime=202609211830` 表示北京时间18:15—18:30，减15分钟再转UTC得到10:15，与目标一致。不将未来新能源预测与过去96帧逐点拼接。

- timeSeries必须为正整数，严格选择1。被选记录必须完整覆盖目标所在北京时间日期的96个时段（包括次日00:00结束点），每个场站都有记录。
- 如果平台所选batch的timeSeries=1未覆盖目标日，拒绝该请求，不静默使用timeSeries=2或上一日尾值补整天。批次选择由平台负责；服务不擅自决定每天08:00及失败回退策略。
- 输入无时区时间按UTC；带偏移量按实际时刻归一UTC。输出为目标时刻，保留末帧时间字符串样式（空格/T、Z或偏移后缀、小数位），时区语义统一UTC。
- 原预测冷启动需要至少288个连续可用历史点，可使用已有 `/api/v1/fluxcast/forecast/compute` 代理按时间补传历史，每批仍为96帧。天气缺测可能需要更早真实历史。该初始化机制不改变正常平台请求格式。
- 联合平台入口在预测未就绪时返回HTTP 202和空结果；原预测及其初始化代理仍返回HTTP 200和空result_point及reason。`latest`仅供查询，不能以旧预测冒充本次结果。

## 3. 成功响应

```json
{
  "result_point": [
    {"varname":"GARD_MW", "timestamp":"2026-09-21 10:15:00", "value":125.0},
    {"varname":"totalPowerForecast", "timestamp":"2026-09-21 10:15:00", "value":1985.5},
    {"varname":"objectiveYuan", "timestamp":"2026-09-21 10:15:00", "value":12345.67},
    {"varname":"carbonTon", "timestamp":"2026-09-21 10:15:00", "value":89.12}
  ],
  "extra_info": [
    {"varname":"balanceStatus", "timestamp":"2026-09-21 10:15:00", "value":"供需平衡"},
    {"varname":"GARD_planStatus", "timestamp":"2026-09-21 10:15:00", "value":"运行"},
    {"varname":"JFRD_planStatus", "timestamp":"2026-09-21 10:15:00", "value":"停机"}
  ],
  "event_key":"JNH.Fluxcast.Compute"
}
```

以上为结构示例和响应节选，数值与状态不是实测数据。优化部分保持30个下一时段数值点；新增末帧实测合计与可计算的同刻偏差，齐全时32点。当天首次发布时再加96个totalPowerForecastDayAhead，齐全时128点。详情见[实测与偏差](实测合计与全天预测偏差.md)。原30点如下：

| varname | 数量 | 单位/含义 |
|---|---:|---|
| GARD_MW、JFRD_MW、JQRD_MW、JXRD_MW、JYRD_MW、SZRD_MW、WLRD_MW | 7 | 各燃机场站建议MW |
| farm_{farmId}_MW | 19 | 风光接纳MW；farmId为1、2、3、4、7、8、10、11、12、13、16、17、19、20、21、22、23、28、29 |
| grid_buy_MW | 1 | 主网购电MW |
| totalPowerForecast | 1 | 本次单时段优化实际采用的七站合计功率预测，MW；原预测值 |
| objectiveYuan | 1 | 下一15分钟综合目标成本，元 |
| carbonTon | 1 | 下一15分钟碳排放，吨 |
| totalPowerActual | 0或1 | 末帧19个原始功率测点之和，MW，缺测时省略 |
| totalPowerDeviation | 0或1 | 已发布全天曲线的同刻预测减实测，MW，无合格预测时省略 |

每个点只有varname、timestamp、value，value为有限浮点数；不包含null、布尔值、字符串、NaN或无穷。(varname,timestamp)唯一。成本已含燃料，不重复叠加天然气参考估值；电量按MW×0.25小时计算。两个指标不是全天汇总，也不是节省率。

`extra_info` 为同级数组，每项同样只有 `varname`、`timestamp`、`value`，但 `value` 必须是字符串。原数值字段名仍为单数 `result_point`，不是 `result_points`。请求字段保持不变；按2026-09-29最新要求，totalPowerForecast与27个功率建议、成本和碳排放共同返回，共30点。该值来自此断面保存的单点预测，不能从优化出力反推或另取latest；重试复用该断面的原值。全天96点现在由同一接口按自然日每日返回一次，变量名totalPowerForecastDayAhead，时间覆盖北京时间当天00:00—23:45；不与优化单点同名。其他成功请求不附带这96点，不以null/0占位。

| extra_info.varname | 数量 | value与依据 |
|---|---:|---|
| balanceStatus | 1 | `供需平衡`，仅对已通过求解约束校验的成功结果返回 |
| GARD_planStatus、JFRD_planStatus、JQRD_planStatus、JXRD_planStatus、JYRD_planStatus、SZRD_planStatus、WLRD_planStatus | 7 | `运行`或`停机`，来自该次求解的 `thermal_running`，不是历史实测状态或按出力临时推断 |
| deviationBasis | 0或1 | `initial_curve_comparison`，首次现算全天曲线时，对首次发布请求当前实测点的比较；不是提前发布预测的在线精度 |

上述8个计划字符串点的时间戳与原30个下一时段数值点一致。另增加实测时刻的dataStatus，必要时增加missingPoints、reason或deviationBasis；实测状态不能当作计划状态。首次发布96点也返回当前实测及可计算的同刻偏差；首次补算的例外与标记见[实测说明](实测合计与全天预测偏差.md)。各 `(varname,timestamp)` 唯一。原计划状态缺失或类型不合法时仍返回503及空结果；等待、过期及失败时仍为 `extra_info=[]`。重试复用同一断面的已保存结果。

本次新增范围是正式优化入口及算法自身统一错误返回。原预测代理仍原样透传上游的预测响应，24小时预测服务仅在容器内使用，不再公开第二端口；已弃用的详细调试入口保持原返回。初始化代理同时预热两模型，但不发布全天结果。平台读取正式优化结果时需保存或解析新增 `extra_info`；若原客户端禁止未知顶层字段，需同步更新解析规则。

## 4. 异常、重试及留痕

| HTTP | 处理 |
|---:|---|
| 200 | 成功，event_key、result_point和extra_info三个顶层字段 |
| 202 | 历史未就绪等等待状态，result_point=[]、extra_info=[]，含status和原因 |
| 400 | 非法JSON |
| 422 | 请求结构、测点、时间轴、长表场站/批次/数值、source_id等不符合约定 |
| 409 | 断面过期、被更新断面替代，或同一断面的输入冲突 |
| 502 | 原预测服务不可用或返回不合法 |
| 503 | 日志、配置、存储或求解失败等服务错误 |

错误返回固定event_key、空result_point、空extra_info与错误说明；不发布伪造功率或成功状态，不以null或零补成成功。过期状态返回状态说明及两个空数组。缺值有前值时按已有规则修复并写工作日志；新能源首值超容量且无前值时截至配置上限并记录原值。缺整条记录或整日不能用数值修复掩盖。

同一末帧时间构成同一断面，完全相同请求（含长表调换行顺序）重试复用结果，不重复求解。修改输入不能覆盖已保存断面。跨窗口保留已知启停状态起点及当日次数。未就绪批次可补齐预测历史后以相同请求重试。

原约定没有开停机遥信和完整事件历史，内部依据历史总功率大于1MW估计运行状态；此阈值沿用既有模型。数据库标记 `power_history_estimate`。96帧前更早事件不能由该接口准确恢复；这属于运行约束的输入边界。新能源实测未提供时保持未知，不伪造为零。

输入、预测来源、batch、时间对齐、异常替代和求解结果记录于SQLite及 `WORK_LOG_PATH`，默认output/logs/work.jsonl。线上求解不从随包业务档案补缺输入。服务时效保护以服务器UTC时钟为准，超过下一目标时刻不再发布旧建议。

## 5. 辅助接口与部署边界

| 路径 | 用途 |
|---|---|
| POST /api/v1/fluxcast/forecast/compute | 原预测历史初始化代理，仅point_table/frames |
| GET /api/v1/fluxcast/forecast/latest | 查询已有预测，不用于替代本批次 |
| GET /api/v1/fluxcast/single-period/status/{snapshot_id} | 运维查状态与来源；平台断面ID形如platform-20260921T100000Z |
| POST /api/v1/fluxcast/single-period/compute | 已弃用的r2详细调试入口；平台不需要迁移到这里 |
| GET /health | 进程健康，不代表历史就绪或求解成功 |
| GET /api/v1/fluxcast/config/prices | 读取七站14项发电成本/购电价及当前版本 |
| PUT /api/v1/fluxcast/config/prices | 全量保存14项价格，expected_version防止覆盖；不接收天然气价 |

价格接口独立于compute，返回结构不使用result_point或extra_info；错误只有error_code/detail，版本冲突另含current_version。详细请求、单位、初始化和生效边界见[价格接口约定](价格参数配置接口约定-20260929.md)。

旧 `/compute`、全部 `/api/v1/fluxcast/rolling/*` 仍为404，没有恢复8步或96步优化。当前包是Linux/amd64；ARM整包、麒麟系统性能和现场运行约束尚待实际验收。

静态[OpenAPI JSON Schema](platform-openapi.json)与服务 `/openapi.json` 同步，便于平台生成客户端或离线核对结构。

## 6. 内部全天服务

当前只有一个容器和18768一个公开端口。两套预测在容器内部8001/8002监听，18780是历史版本配置，不适用于当前版本。内部全天包装层增加history接收路径，只合并历史而不运行推理；原模型文件不变。日界线准备下一日曲线，漏调用时可用零点前历史补算，每个预测日期已有曲线后不再推理。全天结果在统一compute中按自然日发布一次，实测偏差按当前末帧每次计算。详见[新增规则](实测合计与全天预测偏差.md)和[部署说明](../deploy/forecast-dispatch/README.md)。
