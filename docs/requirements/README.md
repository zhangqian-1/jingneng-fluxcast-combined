# 本次修复依据

以上三份文件是用户提供的原文副本，供核对需求，未改写原文。

1. `platform-contract-20260919.md` 优先：POST /api/v1/fluxcast/compute，全场站单次发送，point_table、frames、renewable_data；按timeSeries=1读取新能源长表，输出result_point及固定event_key。
2. 用户在本次修复中明确确认：96帧为过去24小时实测，末帧当前；预测后优化下一时段。因此，不把历史frames与未来新能源预测逐点配对，而是将两种预测对齐到同一个下一时段。
3. 其余两份用于检查未冲突的要求，如测点点号转义、长表结束时刻、容量、异常处理和ARM部署。逐站source_id及按站事件键与第一份冲突，不恢复逐站聚合。
4. 原预测包的35测点清单来自未修改原包的examples/platform_input_example.json。新增配置仅用于外层校验及恢复点号，不修改预测模型或原镜像。

当前可执行约定见[平台接口说明](../platform-api.md)，逐项核对与未解决事项见[修复核对](../平台接口依据核对与修复-20260923.md)。
