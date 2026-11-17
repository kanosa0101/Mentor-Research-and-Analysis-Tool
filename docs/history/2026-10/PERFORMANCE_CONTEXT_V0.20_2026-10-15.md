# 公开申请上下文加载性能修复 v0.20（2026-10-15）

只改`crawler/project_util.py`：增加安全loader常量`getattr(yaml, 'CSafeLoader', yaml.SafeLoader)`，将`load_context`中院系配置、学校配置、招生政策三处公开YAML解析改为显式使用该loader。每次调用仍重新读取文件；没有缓存、没有改私人存储或来源抓取，也未引入不安全的Loader/CLoader/FullLoader。

根任务实测主服务空材料GET约2.002/1.897/1.863秒（`cache/policy_v20/integration/read-latency.json`）；公开大YAML旧SafeLoader解析1.149秒、CSafeLoader0.0727秒且结果相等（`yaml-loader-pilot.json`）。据此优化反复解析成本。安全loader选择依据根任务核对的[PyYAML官方文档](https://pyyaml.org/wiki/PyYAMLDocumentation)，并由本地两分支行为测试确认。

新增`tests/test_public_context_loader_v20.py`，没有修改其他tests。红灯先运行选择测试，旧实现实际回落为SafeLoader而CSafeLoader本地可用，出现预期失败。优化后6项全过（2.706秒）：

- 与独立复制的旧safe_load上下文读取函数比较真实公开数据，C与纯Python结果完全相等。
- 临时根目录依次修改院系、学校、招生政策三种公开文件，下一次load立即反映变更。
- 测试期从yaml模块暂移除CSafeLoader并独立载入模块，确认SafeLoader fallback正常。
- 对两种安全loader及三类公开配置分别注入python/object/apply标签，拒绝且临时标记文件未生成。
- 两种安全loader面对语法错误均抛YAMLError，不吞错或接受异常文档。

红灯命令：`python -m unittest discover -s tests -p test_public_context_loader_v20.py -k test_available_c_safe_loader_is_selected -v`。
绿灯命令：`python -m unittest discover -s tests -p test_public_context_loader_v20.py -v`。
日志分别为`cache/policy_v20/north/public-loader-red.log`、`public-loader-green.log`。

关键回归按unittest加载`test_project_model`、`test_project_api`、`test_material_tasks_v19`、`test_conditional_deadlines_v20`，31项全通过（22.331秒）。覆盖项目日期适用性、历史恢复、材料条件/来源冲突、文件版本、备份、提醒及特殊身份截止保护。日志`public-loader-key-regressions.log`。全部写操作仅测试临时根目录；没有读写真实private。

完整`load_context`在同一公开数据连续3次只读计时：SafeLoader 1.0829/1.1215/1.6446秒，CSafeLoader 0.2980/0.2668/0.2691秒，中位数从1.1215降至0.2691秒，约4.17倍。该次包含59院系文件和公开学校/招生数据，且和关键回归并行进行，只作为上下文解析观察；不能代替主服务重启后的API端到端时延。原始结果`cache/policy_v20/north/public-loader-timing.json`。根任务负责后续全套验证、重启主服及API重新计时。

交付未commit。冻结后不继续改实现，等待根任务集成复核。
