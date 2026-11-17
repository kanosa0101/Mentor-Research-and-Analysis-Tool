# 北邮官方入口获取失败展示 v0.20

仅交付`cache/policy_v20/blocked_entry/fragment.json`供root合并，未改中央或任何生产逻辑。分片包含`sources_new`一个`bupt_admissions_home_v20gap`（官方研究生招生首页`https://yzb.bupt.edu.cn/`，HTML/body），`checks`一项HTTP 412失败，以及`entries_new`一项学校层导航。没有新增政策或成功来源检查。

本任务未再次联网，复用root本轮真实请求证据`cache/policy_v20/integration/bupt-gap-probe.json`与`bupt-home-live.body`。核对请求及落地URL均为`https://yzb.bupt.edu.cn/`，响应HTTP 412，实际抓取时间`2026-10-15T12:18:56.198510+00:00`，2555字节，原始SHA-256为`467892bc717de01cf81005d7122b755627d7b8ce76bddfbe750e0fd84310c6bb`；已对保存字节重新计算并确认一致。原始失败响应的SHA只保留为证据，不能登记为成功政策正文hash。

新增check仅含`status:error`、`last_attempt:2026-10-15`、明确HTTP 412的错误说明，不给`hash/last_success`。entry为`school:bupt/dept:''/reviewed_at:2026-10-15`，不设置年度、学位或渠道。note说明官方入口、本轮412导致未核得2027规则，范围未知，仅供导航；没有宣称未发布或不招生。

`cache/policy_v20/blocked_entry/build_and_check.py`在内存影子合并数据后调用现有政策、检查、entry schema；临时站点使用现有admissions.js实际渲染，1440/390均通过。浏览器直接调用`entryStatus`得到`error`且`success:''`，`entryScope`对2027/master/exam得到`unknown`；该入口位于“范围待核对的官方导航”，不计入“年度、学位、渠道相符的入口”，政策卡数仍为0。卡片显示“最近回源失败”、HTTP 412、范围未标定和精确官方URL，未显示最近成功日期。没有外部请求、私人写入或JS异常，无横向溢出。

测试结果在`validation.json`，截图为`bupt-1440.png/bupt-390.png`与对应`bupt-entry-*`局部截图，均在该cache目录。已实际查看390px入口截图，错误状态及范围未知提示清晰可见。没有点击外部链接；精确URL已核对DOM href，不声称官网当前可读。

root合并后预期只增加1 source/check及1 entry，policy/action数量不变。无需生产代码变化，无Git提交。
