# 平台对接接口约定修改 — 算法侧

> 收件方：算法开发团队  
> 发起方：平台对接方  
> 日期：2026-09-19  
> 项目：jn-algorithm-fluxcast（绿碳协同智慧调度）

## 平台请求算法接口约定

### 2.1 接口路由与调用方式

**请求路径**：

```
POST /api/v1/fluxcast/compute
```

- 平台按**全场站**发送数据、期望返回**全场站**的计算结果。

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
  ],
  "renewable_data": [预测系统原始返回，第一段描述的长表格式]
}
```

- `frames` 为 **96 个元素**的列表（15 分钟间隔 × 24 小时），每帧带当前时刻所有测点的值。
- 测点名作为 frame 对象的 key，值为浮点数。
- `timestamp` 支持 ISO8601 (如 2025-09-25 19:28:22) 或空格分隔 (如 2025-09-25 19:28:22), 服务端会归一化为 %Y-%m-%d %H:%M:%S（UTC）

**新能源预测数据 `renewable_data` 透传契约**：

| 阶段 | 预测系统 | 平台 | 算法 |
|---|---|---|---|
| 获取数据 | 维持现有 API：`GET /externalData/shortTermForecastsData?farmId={id}&batch={batch}` 返回长表（farmId、predictedTime 结束时刻、predictedPower、timeSeries、batch）| **调用预测系统 API**：每天一次按 `batch` 号和 19 个 farmId 逐个查询，汇总结果暂存 | - |
| 组装请求 | - | 按 source_id 逐站构造燃机请求体，在每站都附加相同的 `renewable_data` 字段（包含上一步的全部预测结果）| - |
| 处理数据 | - | - | 从 `renewable_data` 提取：解析长表、取 `timeSeries=1`（次日 96 点）、`predictedTime` 减 15 分钟转开始时刻、按 farmId 聚合成宽表、逐 farmId 校验容量、与 `frames` 时间轴逐点对齐 |

**平台侧处理细节**：

1. **何时获取**：每天预测系统发布批次后立即获取（建议 08:30，预留发布延迟）；若某天批次延迟或缺失，应用前一天 batch，并记录异常告警
2. **怎么获取**：依次调用预测系统 API `shortTermForecastsData?farmId=1&batch=YYYYMMDDHHMM`、`farmId=2&batch=...`...`farmId=29&batch=...`，共 19 次；每次返回 960 条（10 天数据）
3. **怎么组装 `renewable_data`**（这是关键）：
   - 预测系统单次查询返回格式（farmId=1）：
     ```json
     {
       "code": 200,
       "msg": "success",
       "data": [
         {"farmId": 1, "predictedTime": "202609190015", "predictedPower": 157.955, "timeSeries": 1, "batch": "202609180800"},
         {"farmId": 1, "predictedTime": "202609190030", "predictedPower": 149.334, "timeSeries": 1, "batch": "202609180800"},
         ...
       ]
     }
     ```
   - 平台把所有 19 个 farmId 的 `data` 数组合并为一个，作为 `renewable_data` 字段值：
     ```json
     "renewable_data": [
       {"farmId": 1, "predictedTime": "202609190015", "predictedPower": 157.955, "timeSeries": 1, "batch": "202609180800"},
       {"farmId": 1, "predictedTime": "202609190030", "predictedPower": 149.334, "timeSeries": 1, "batch": "202609180800"},
       ...（farmId=1 全部 960 条）...,
       {"farmId": 2, "predictedTime": "202609190015", "predictedPower": 0.0, "timeSeries": 1, "batch": "202609180800"},
       ...（farmId=2 全部 960 条）...,
       ...（farmId 3~29 依次追加）...
     ]
     ```
   - 即：**所有 19 个 farmId 的结果行拼在一起，去掉 `code`/`msg`，只保留 `data` 数组元素**
4. **怎么暂存**：所有 19 个 farmId 的结果合并后存储（上述 `renewable_data` 值），关键字为 batch ID；同一 batch 在该天内保持不变
5. **怎么附加**：在**所有 7 站**的请求中都附加相同的 `renewable_data` 值（即当前 batch 的完整合并结果），确保聚合时新能源数据一致

## 输出响应格式

```json
{
  "result_point": [
    {"varname": "objectiveYuan", "timestamp": "...", "value": 123456.78},
    {"varname": "carbonTon", "timestamp": "...", "value": 89.12}
  ],
  "event_key": "JNH.Fluxcast.Compute",
}
```

> **注意：** 时间戳 `timestamp` 格式应严格与请求 payload 中的时间戳格式保持一致，类似于 `2026-06-06 00:00:00`。不得随意变更返回时间戳格式和时区（UTC）。
> **注意：** `result_point` 中 `value` 字段返回值类型应为浮点值，不能出现其他类型值。
> **注意：** `result_point` 中 `{varname, timestamp}` 字段返回组合应唯一。
