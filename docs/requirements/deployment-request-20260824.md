# 平台对接改造需求 — 算法侧

> 收件方：算法开发团队  
> 发起方：平台对接方  
> 日期：2026-08-24  
> 项目：jn-algorithm-fluxcast（绿碳协同智慧调度）

---

## 一、背景

当前算法以"读离线文件包 → 批处理出结果"的方式运行。平台上线后，接口将由平台实时推送 96 点量测/预测数据来触发调度计算，不再依赖本地挂载文件。本文档列出算法侧需要配合完成的改造工作与交付物。

---

## 二、核心改造：接口数据驱动替代文件读取

### 2.1 接口路由与调用方式

**请求路径**（平台规范）：

```
POST /api/v1/fluxcast/compute?source_id={场站编码}
```

- `source_id`：查询参数，标识本次触发对应的场站编码（与平台场站管理系统中的编码一一对应）。
- 平台按**单场站**发送数据、期望返回**该场站**的计算结果。
- 算法侧需解析 `source_id`，确定当前请求对应哪个场站，返回该场站维度的调度结果。

目前已有 `source_id` 与厂站标识映射关系（`id` 字段即为 `source_id`）：

```json
[
  {
    "id": 2,
    "name": "JYRD",
    "description": "京阳热电",
    "created_at": "2025-09-06 03:25:49.021",
    "updated_at": "2025-09-06 03:25:50.144",
    "deleted_at": null
  },
  {
    "id": 3,
    "name": "JQRD",
    "description": "京桥热电",
    "created_at": "2025-09-06 03:25:49.021",
    "updated_at": "2025-09-06 03:25:50.144",
    "deleted_at": null
  },
  {
    "id": 4,
    "name": "JFRD",
    "description": "京丰燃气",
    "created_at": "2026-06-17 19:20:39.83",
    "updated_at": "2026-06-17 19:20:43.838",
    "deleted_at": null
  },
  {
    "id": 5,
    "name": "GARD",
    "description": "高安屯热电",
    "created_at": "2026-07-15 02:17:49.327",
    "updated_at": "2026-07-15 02:17:50.651",
    "deleted_at": null
  }
]
```

> **架构决策点（需算法侧确认）**：当前算法模型为 7 站联合优化（功率平衡约束跨站、电网买卖电是全局变量），若平台按单站触发，有以下可选方案：
>
> | 方案 | 描述 | 优劣 |
> |------|------|------|
> | A. 全局求解 + 按站筛选返回 | 任一站触发时，用全部 7 站最新数据做一次联合优化，但只返回 `source_id` 对应站的结果 | 结果最优；但需缓存其他站数据，且触发频率高时重复计算 |
> | B. 聚合触发 | 收齐 7 站数据后再统一求解（内部设超时窗口），按站拆分返回 | 结果最优；但引入等待延迟 |
> | C. 单站独立模型 | 将联合优化拆为 7 个独立的单站调度子问题 | 无跨站依赖；但丢失全局最优性（买卖电分配无法协调） |
>
> **请算法侧评估并选择方案，这直接影响接口设计和数据缓存策略。**

### 2.2 请求体格式

平台约定的请求 Body 格式（已确定）：

```json
{
  "point_table": ["GARD_11MBY0100000BJ01XQ01", "GARD_12MBY0100000BJ01XQ01", "GARD_13MKA01CE903BJ01XQ01"],
  "frames": [
    {
      "timestamp": "2026-06-06 00:00:00",
      "GARD_11MBY0100000BJ01XQ01": 125.3,
      "GARD_12MBY0100000BJ01XQ01": 130.1,
      "GARD_13MKA01CE903BJ01XQ01": 180.5
      "...": "..."
    },
    {
      "timestamp": "2026-06-06 00:15:00",
      "...": "..."
    }
  ]
}
```

- `frames` 为 **96 个元素**的列表（15 分钟间隔 × 24 小时），每帧带当前时刻所有测点的值。
- 测点名作为 frame 对象的 key，值为浮点数。
- `timestamp` 支持 ISO8601 (如 2025-09-25 19:28:22) 或空格分隔 (如 2025-09-25 19:28:22), 服务端会归一化为 %Y-%m-%d %H:%M:%S（UTC）

### 2.3 需要算法侧提供的测点清单

当前代码硬编码了以下测点（来源：`dispatch_engine.py` L81-143），算法侧需确认并**正式输出给平台，作为测点订阅需求**：

#### A. 负荷/燃机测点（7 场站，共 17 个点，用于构建 `demand_mw` 和 `base_gas_mw` 96 点曲线）

| 场站代码 | 场站名称 | 原始测点编码 | 平台传入时的 key（`.` 替换为 `_`） |
|---------|---------|-------------|--------------------------------------|
| GARD | 高安屯热电 | `GARD_11MBY0100000BJ01XQ01` | `GARD_11MBY0100000BJ01XQ01`（无变化） |
| GARD | 高安屯热电 | `GARD_12MBY0100000BJ01XQ01` | `GARD_12MBY0100000BJ01XQ01`（无变化） |
| GARD | 高安屯热电 | `GARD_13MKA01CE903BJ01XQ01` | `GARD_13MKA01CE903BJ01XQ01`（无变化） |
| JFRD | 京丰燃气 | `JFRD_11MKA01GA001BJ40XQ01` | `JFRD_11MKA01GA001BJ40XQ01`（无变化） |
| JQRD | 京桥热电 | `JQRD_10CBA00FA107XQ93` | `JQRD_10CBA00FA107XQ93`（无变化） |
| JQRD | 京桥热电 | `JQRD_10CBA00FA108XQ93` | `JQRD_10CBA00FA108XQ93`（无变化） |
| JQRD | 京桥热电 | `JQRD_10CBA00FA109XQ93` | `JQRD_10CBA00FA109XQ93`（无变化） |
| JXRD | 京西热电 | `JXRD_11MBY0100000BJ01XQ01` | `JXRD_11MBY0100000BJ01XQ01`（无变化） |
| JXRD | 京西热电 | `JXRD_12MBY0100000BJ01XQ01` | `JXRD_12MBY0100000BJ01XQ01`（无变化） |
| JXRD | 京西热电 | `JXRD_13MKA01GA001BJ02XQ01` | `JXRD_13MKA01GA001BJ02XQ01`（无变化） |
| JXRD | 京西热电 | `JXRD_15MKA01GA001BJ02XQ01` | `JXRD_15MKA01GA001BJ02XQ01`（无变化） |
| JXRD | 京西热电 | `JXRD_14MBY0100000BJ01XQ01` | `JXRD_14MBY0100000BJ01XQ01`（无变化） |
| JYRD | 京阳热电 | `JYRD_LOADCTL:GTMWSEL1_1.OUT` | **`JYRD_LOADCTL:GTMWSEL1_1_OUT`** |
| JYRD | 京阳热电 | `JYRD_LOADCTL:GTMWSEL1_2.OUT` | **`JYRD_LOADCTL:GTMWSEL1_2_OUT`** |
| JYRD | 京阳热电 | `JYRD_30DCS01:FU101.PNT` | **`JYRD_30DCS01:FU101_PNT`** |
| SZRD | 上庄热电 | `SZRD_10DCS02FA133` | `SZRD_10DCS02FA133`（无变化） |
| SZRD | 上庄热电 | `SZRD_10DCS02FA134` | `SZRD_10DCS02FA134`（无变化） |
| WLRD | 未来热电 | `WLRD_13MKA0100000BJ01XQ01` | `WLRD_13MKA0100000BJ01XQ01`（无变化） |
| WLRD | 未来热电 | `WLRD_11MBY10CE901XQ01` | `WLRD_11MBY10CE901XQ01`（无变化） |

> **注意 — 测点名转义规则**：平台在传入 frames 时会将测点编码中的 **点号 `.`** 统一替换为 **下划线 `_`**。算法侧在解析 frames key 时需要适配这一转换。
>
> 建议处理方式：统一在内部也使用转义后的名称。

#### B. 新能源预测测点（19 个场站，每站 1 个功率预测值）

> **重要说明**：下表中的 `farm_{id}_predictedPower` 并非场站的原始量测测点，而是来源于**上游另一个新能源功率预测算法的输出变量名**。算法侧需核实：
> 1. 能源功率预测算法是否包含到代码仓库内。
> 2. 算法直接调用能源功率预测结果，平台不负责传递这些结果值。

| farmId | 场站名称 | 当前代码使用的标识 | 需核实的平台传入 key |
|--------|---------|-------------------|-------------------|
| 1 | 康保风电 | farm_1 (farm_1.json) | `farm_1_predictedPower`（待确认） |
| 2 | 孟家房子光伏电站（一期） | farm_2 | `farm_2_predictedPower`（待确认） |
| 3 | 孟家房子光伏电站（二期） | farm_3 | `farm_3_predictedPower`（待确认） |
| 4 | 孟家房子光伏电站（三期） | farm_4 | `farm_4_predictedPower`（待确认） |
| 7 | 后杨庄光伏电站 | farm_7 | `farm_7_predictedPower`（待确认） |
| 8 | 宁河光伏电站 | farm_8 | `farm_8_predictedPower`（待确认） |
| 10 | 杨津庄风电场 | farm_10 | `farm_10_predictedPower`（待确认） |
| 11 | 苗庄风电场 | farm_11 | `farm_11_predictedPower`（待确认） |
| 12 | 板桥风电站 | farm_12 | `farm_12_predictedPower`（待确认） |
| 13 | 郝家营风电场（二期） | farm_13 | `farm_13_predictedPower`（待确认） |
| 16 | 郝家营风电场（一期） | farm_16 | `farm_16_predictedPower`（待确认） |
| 17 | 大囫囵风电场（一期） | farm_17 | `farm_17_predictedPower`（待确认） |
| 19 | 大囫囵风电场（二期） | farm_19 | `farm_19_predictedPower`（待确认） |
| 20 | 官厅风电场 | farm_20 | `farm_20_predictedPower`（待确认） |
| 21 | 麻黄峪风电站 | farm_21 | `farm_21_predictedPower`（待确认） |
| 22 | 延庆光伏电站（一期） | farm_22 | `farm_22_predictedPower`（待确认） |
| 23 | 峻盛风电场 | farm_23 | `farm_23_predictedPower`（待确认） |
| 28 | 东棘坨风电场 | farm_28 | `farm_28_predictedPower`（待确认） |
| 29 | 延庆光伏电站（二期） | farm_29 | `farm_29_predictedPower`（待确认） |

---

## 三、ARM (aarch64) 部署兼容性

**生产部署环境为 ARM 架构（aarch64 Kylin V10 SP3）**，以下为各依赖的兼容性核查结果：

| 依赖包 | 版本约束 | aarch64 支持情况 | 风险等级 |
|--------|---------|-----------------|---------|
| **gurobipy** | >=10.0,<11.0 | ⚠️ 有条件支持 | **高** |
| numpy | >=1.26,<3.0 | ✅ 官方 aarch64 wheel | 无 |
| pandas | >=2.1,<3.0 | ✅ 官方 aarch64 wheel | 无 |
| matplotlib | >=3.8,<4.0 | ✅ 官方 aarch64 wheel | 无 |
| openpyxl | >=3.1,<4.0 | ✅ 纯 Python | 无 |
| fastapi | >=0.115,<1.0 | ✅ 纯 Python | 无 |
| uvicorn | >=0.30,<1.0 | ✅ 纯 Python | 无 |
| python-dotenv | >=1.0,<2.0 | ✅ 纯 Python | 无 |

### gurobipy 在 ARM 上的具体情况

PyPI 上 `gurobipy` 10.0.x 版本**已提供 `manylinux2014_aarch64` wheel**，但需确认：

1. **Gurobi 许可证**：ARM 服务器的许可证是否需单独申请/激活（`grbprobe` 生成的机器指纹是否与架构相关），能否直接复用 x86 机器的许可文件。
2. **求解性能差异**：Gurobi 在 ARM 上的 MIP 求解性能与 x86 可能有差异，算法侧需确认是否满足分钟级响应要求。

---

## 四、需要算法侧确认/决策的问题

| # | 问题 | 背景 | 影响 |
|---|------|------|------|
| 1 | **source_id 与联合优化的关系** | 平台按单站发数据、期望单站结果；但算法是 7 站联合优化 | 见 2.1 方案 A/B/C，需算法侧选择 |
| 2 | 新能源预测变量名核实 | `farm_{id}_predictedPower` 是否为上游预测算法的真实输出字段名 | 直接影响 frames 解析 |
| 3 | `load_day` / `renewable_day` 怎么确定？ | 现在硬编码为 `2025-06-05` / `2026-06-06`，实时化后如何映射到 frames 的时间范围 | 建议由 frames 里 timestamp 自动推导，算法侧确认逻辑 |
| 4 | 缺测点/数据质量异常时的降级策略 | 某个 frame 缺字段、NaN、负值 | 需算法侧定义：拒绝计算 vs 用上一时刻填充 vs 标记降级 |
| 5 | 新能源装机容量校验上限来源 | 现在从 Excel 读取 | 实时化后这个校验仍保留？上限从配置读还是去掉？ |
| 6 | 分钟级响应时间可行性 | 平台要求分钟级返回结果 | 算法侧需实测 Gurobi **在 ARM 服务器上**的求解耗时，确认是否满足 |
| 7 | gurobipy ARM 许可证 | ARM 机器指纹与 x86 不同，许可文件不通用 | 需提前在目标机器上激活，否则容器启动后求解报许可错误 |

---

## 五、输出响应格式（现状与建议扩展）

### 5.1 当前响应结构

```json
{
  "result_point": [
    {"varname": "objectiveYuan", "timestamp": "...", "value": 123456.78, "period": 1},
    {"varname": "carbonTon", "timestamp": "...", "value": 89.12, "period": 1}
  ],
  "event_key": "JNH.Fluxcast.Compute",
  "metadata": {
    "solver_mode": "gurobi",
    "thermal_model": {...},
    "figure_files": [...]
  }
}
```

### 5.2 建议扩展（按单站返回）

平台按 `source_id` 触发、期望该场站维度的结果。建议响应结构调整为：

```json
{
  "source_id": 2,
  "result_point": [
    {"varname": "objectiveYuan", "timestamp": "...", "value": 123456.78},
    {"varname": "carbonTon", "timestamp": "...", "value": 89.12}
  ],
  "event_key": "JNH.Fluxcast.Compute",
}
```

> **注意：** 时间戳 `timestamp` 格式应严格与请求 payload 中的时间戳格式保持一致，类似于 `2026-06-06 00:00:00`。不得随意变更返回时间戳格式。
> **注意：** `result_point` 中 `value` 字段返回值类型应为浮点值，不能出现其他类型值。
> **注意：** `result_point` 中 `varname` 字段返回值应唯一。

---

## 六、交付物清单

算法侧需输出以下文档/代码：

| # | 交付物 | 说明 |
|---|--------|------|
| 1 | **测点需求清单**（正式版） | 包含全部测点编码（含转义后名称）、单位、采样频率、是否必填；新能源预测变量名需核实后确认 |
| 2 | **接口使用文档** | 完整 API 文档：路由、查询参数、请求/响应 JSON Schema、字段说明、调用示例、错误码清单 |
| 3 | **改造后的代码** | 支持从 frames 接收实时数据 + source_id 路由，同时保留离线文件模式用于本地调试 |
| 4 | **性能报告** | Gurobi 求解耗时实测数据（不同规模 case），确认满足分钟级要求 |
| 5 | **降级策略说明** | 数据异常时的处理方式，供平台侧做上游容错设计 |
| 6 | **gurobipy ARM 许可证** | 许可证文件，或者离线激活方式 |

---

## 七、event_key 命名规则

平台约定：`{场站标识}.Fluxcast.Compute`

示例：`JNH.Fluxcast.Compute`

算法侧需将现有默认值 `JNH.Dispatch` 改为按此规则生成。
