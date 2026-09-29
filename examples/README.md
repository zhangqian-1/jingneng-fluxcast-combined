# 原协议完整历史请求

本次新增字段见 [observations-output-fragment.json](observations-output-fragment.json)，这是说明用的新增字段节选，不是完整联合响应。输入不变；实测取末帧19个原始功率值。详细规则见[实测说明](../docs/实测合计与全天预测偏差.md)。下文platform-result.json保留为r5的历史容器验证证据，不包含本次实测字段，不能视为本次容器已通过验收。

[observations-initial-output-fragment.json](observations-initial-output-fragment.json) 是首次现算全天曲线时的实测与偏差节选，extra_info增加deviationBasis=initial_curve_comparison。完整首次响应还包含当天96点、下一15分钟预测及原调度结果；实测仅返回当前一点，不补发当天全部实测历史。

平台使用 `POST /api/v1/fluxcast/compute`，仅含 `point_table`、`frames`、`renewable_data`。见[当前接口说明](../docs/platform-api.md)。

本次容器验证的完整输入和输出随离线包放在 `联调记录/platform-request.json`、`联调记录/platform-result.json`。仓库的 `examples/platform-request.json`、`examples/platform-result.json` 保存同一份可审查样例。

历史功率与天气来自原始七站实际档案；新能源长表是明确标注的零出力测试情景，不是新能源实测或现场生产预测。时间为2025年10月，不能直接作为当前生产请求：生产服务会按时效规则返回409。测试脚本在隔离进程设置历史时钟，不提供生产时钟覆盖参数。

测点清单见 [forecast-measurement-points.csv](../docs/forecast-measurement-points.csv)。将样例用于平台实现时，应以当前真实历史与上游返回的当前batch长表替换数据；不要只改时间、复用过去功率冒充当前实测。

原来的 `combined-request.json` 只用于r2详细入口回归验证，不再作为平台接入样例。旧整日或8步请求生成器已删除。

## 原24小时预测模型样例（内部接口）

下述两个day-forecast样例保留原模型格式，仅供内部核验。当前20260929-r4仅公开18768一个端口，正式平台应调用上面的统一入口；历史20260926-r3曾在18780公开原路径POST `/api/v1/fluxcast/compute`。`day-forecast-request.json`为原35测点、96帧历史的两字段请求；`day-forecast-result.json`为对应的未来96点。该输出不进入优化。主平台18768端口仍采用上面的三字段约定。

两个样例使用相同的归档历史，不是当前生产数据。原长预测需先补足至少672点连续真实历史，再发送最后96帧；孤立发送该文件到空缓存不会产生96点预测。单点预测需至少288点。两个缓存分别初始化，原预测测点编码保留点号和冒号。

历史 platform-result.json 是r5实际隔离容器返回的126点示例。本次新增实测与偏差后，全部可用时为128点，不附带全天曲线时为32点；缺测或无匹配预测时相应减少。后续响应不清空平台已保存的当天曲线。
