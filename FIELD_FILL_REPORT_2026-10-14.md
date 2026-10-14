# 明确研究栏目缺字段补齐试点 · 2026-10-14

以本地版本 `b1985e304` 为基线，只补清华自动化、上交自动化与感知原为空的字段。官方个人页面重抓、姓名一致性校验、明确栏目提取、dry-run 逐条核对后实写；未重爬整批、未推断方向、未调整导师ID或已有值。

## 覆盖变化

|院系|记录数|研究方向原有→补齐后|公开邮箱原有→补齐后|
|---|---:|---:|---:|
|清华自动化|110|0 → 20|98 → 98|
|上交自动化与感知|203|0 → 20|199 → 199|

共查 55 个官方页面，补齐 40 条明确研究方向，16条原缺邮箱的记录均优先检查，本轮没有新增邮箱；无公开且可明确归属的邮箱时继续留空。15条没有取得可补空字段的明确栏目，未写入。

## 来源与产品边界

清华使用个人页 `.leader_d .fl02 .t-tag` 的“研究领域/研究方向”，截到下一栏目；上交使用 `.js-item` 内明确“研究方向”栏目，遇栏目内部的“个人简介/招生及招聘”等标题即停止。研究栏目中其余原文附注仍保留，不转成招生资格、当前名额或申请政策。字段来源保留完整个人页链接及抓取日 `2026-10-14`；这是抓取日，不能代替官网原文更新时间。

公开个人页属于学校官网；本轮未发现可据以声称整站数据开放授权的许可说明。这里只记录有限栏目原文及来源，不宣称原始师资数据具有开源许可证；未上传数据或发送邮件。

## 验证

- `python -m unittest discover -s tests -p test_fill_related_fields.py`：7项通过，包含无栏目不猜测、范围约束、人工保护、既有来源保留、明确边界、姓名匹配。
- dry-run 计划：`cache/field_fill/plan.json`；40条改动的源片段全部在抓取原文中查到，实写后 SHA-256 与预审差异一致。
- 与基线逐字段比对：两院系的其他记录值与旧 provenance 全部保留，且本轮邮箱值无变更。
- 留痕：`data/changes/tsinghua-auto.jsonl` / `data/changes/sjtu-auto.jsonl`，新增字段记录含原值、新值、来源、抓取日、栏目定位。
- 原来缺邮箱的16条中清华12条、上交4条，官方已注册个人页未提取到明确个人邮箱，本轮没有从外部同名网页猜测。

## 逐条变更

|院系 / slug|字段|新增原文|官方来源|
|---|---|---|---|
|tsinghua / hexiao|research_direction_raw|[1] 机器人的群智能自主控制<br>主要包括旋翼无人机群通信约束下的故障诊断；旋翼无人机群的容错编队；多仿人机器人的协作控制等<br>[2] 高速列车信息控制系统的故障诊断<br>主要包括面向间歇故障的诊断；闭环系统的鲁棒故障诊断；数据驱动的故障诊断技术等<br>[3] 深海载人潜水器的容错控制与自救<br>主要包括动态系统的主动故障诊断；微小故障的诊断与识别；人在回路复杂系统的安全性评估等|[个人页](https://www.au.tsinghua.edu.cn/info/1077/3189.htm)|
|tsinghua / liuyunhao|research_direction_raw|物联网与无线传感网，室内定位与网络诊断，RFID，工业互联网与云计算|[个人页](https://www.au.tsinghua.edu.cn/info/1076/3158.htm)|
|tsinghua / baiyuqi|research_direction_raw|多智能体系统协同控制，控制类课程实验教学，智能机器人|[个人页](https://www.au.tsinghua.edu.cn/info/1082/3915.htm)|
|tsinghua / chaiyueting|research_direction_raw|1.电子商务理论、技术及应用<br>2.区块链基础技术研发与应用<br>3.众智科学、数据科学、服务科学及应用<br>4.智能制造<br>5.云制造|[个人页](https://www.au.tsinghua.edu.cn/info/1075/3205.htm)|
|tsinghua / chenfeng|research_direction_raw|类脑计算,机器学习,概率图模型,计算机视觉,视频分析|[个人页](https://www.au.tsinghua.edu.cn/info/1080/3113.htm)|
|tsinghua / chenlei|research_direction_raw|计算机视觉、模式识别|[个人页](https://www.au.tsinghua.edu.cn/info/1078/3594.htm)|
|tsinghua / chenzhang|research_direction_raw|1. 机器人遥操作控制；<br>2. 机器人运动控制；<br>3. 智能控制与规划|[个人页](https://www.au.tsinghua.edu.cn/info/1081/3094.htm)|
|tsinghua / daiqionghai|research_direction_raw|成像与智能|[个人页](https://www.au.tsinghua.edu.cn/info/1080/3225.htm)|
|tsinghua / dengxiaojiao|research_direction_raw|太赫兹检测技术、光谱分析|[个人页](https://www.au.tsinghua.edu.cn/info/1079/3188.htm)|
|tsinghua / dengyang|research_direction_raw|1. 机器人敏捷机动控制<br>2. 时滞系统、网络化控制系统<br>3. 滑模控制、固定时间控制、预定时间控制|[个人页](https://www.au.tsinghua.edu.cn/info/1081/3924.htm)|
|tsinghua / diyanwang|research_direction_raw|光场成像，光场调控，智能光子学|[个人页](https://www.au.tsinghua.edu.cn/info/1080/3652.htm)|
|tsinghua / fanjingtao|research_direction_raw|计算摄像、立体视觉|[个人页](https://www.au.tsinghua.edu.cn/info/1080/3221.htm)|
|tsinghua / fanyushun|research_direction_raw|企业信息化战略管理、现代服务科学与技术、计算机集成制造系统、智能制造与工业<br>4.0<br>、业务流程建模与优化、大数据与智能服务平台|[个人页](https://www.au.tsinghua.edu.cn/info/1075/3202.htm)|
|tsinghua / fengjianjiang|research_direction_raw|指纹识别、计算机视觉、医学图像分析|[个人页](https://www.au.tsinghua.edu.cn/info/1078/3262.htm)|
|tsinghua / genghua|research_direction_raw|1 强化学习、大模型理论方法与应用<br>2 可再生能源系统优化控制<br>3 新型电力系统稳定控制<br>4 海上风电机组运维<br>5 月面能源系统|[个人页](https://www.au.tsinghua.edu.cn/info/1079/3102.htm)|
|tsinghua / gujin|research_direction_raw|1、生物信息学<br>2、机器学习<br>3、系统与精准医学|[个人页](https://www.au.tsinghua.edu.cn/info/1078/3255.htm)|
|tsinghua / hanjungong|research_direction_raw|脑启发的人工智能、计算机视觉、模式识别、机器学习|[个人页](https://www.au.tsinghua.edu.cn/info/1080/3854.htm)|
|tsinghua / huangbiqing|research_direction_raw|鲁棒、安全可解释第三代人工智能研究，及其在工业和现代服务业的应用<br>1. 基于视觉智能的工业表面缺陷检测核心算法<br>2. 基于运动轨迹的车间作业合规性监测算法<br>3. 数据驱动的工业装备（风电、核电）健康评估与故障诊断<br>4. 云边协同（云计算与边缘计算）的算法和任务优化<br>5. 智能制造中的工业互联网与智能控制<br>6. 医疗领域的人工智能方法<br>7. 数据科学与服务科学<br>8. 制造业和服务业知识图谱技术<br>在以上方向招收：工学博士、创新领军工程博士、工学硕士、深圳研究生院工程硕士、贵州大数据工程硕士<br>注：工程博士重点招收方向：人工智能在智能制造、社会治理、健康医疗等领域的落地应用|[个人页](https://www.au.tsinghua.edu.cn/info/1075/3209.htm)|
|tsinghua / huanggao|research_direction_raw|深度学习、多模态学习、具身智能、强化学习|[个人页](https://www.au.tsinghua.edu.cn/info/1075/3183.htm)|
|tsinghua / huangshuangxi|research_direction_raw|企业信息化工程<br>复杂系统建模与分析<br>协同工程|[个人页](https://www.au.tsinghua.edu.cn/info/1075/3214.htm)|
|sjtu / quyuan|research_direction_raw|光学检测|[个人页](https://sais.sjtu.edu.cn/faculty/quyuan.html)|
|sjtu / yugan|research_direction_raw|空海无人系统自主控制与协同作业，包括不完备信息下的状态估计与鲁棒控制、柔性绳系约束下的协同操控与构型重构，以及动态环境下异构系统的任务协同与自主作业|[个人页](https://sais.sjtu.edu.cn/faculty/yugan.html)|
|sjtu / zhanghonglu|research_direction_raw|生物界面感知与分析；生物测量与信息存储；人工智能+|[个人页](https://sais.sjtu.edu.cn/faculty/zhanghonglu.html)|
|sjtu / zhushanying|research_direction_raw|工业物联网，工业网络系统，实时控制系统，多智能体系统，综合能源系统|[个人页](https://sais.sjtu.edu.cn/faculty/zhushanying.html)|
|sjtu / baiting|research_direction_raw|信息物理系统、大规模网络化系统、智能交通系统的协同优化<br>最优控制理论、分布式模型预测控制、强化学习理论与方法|[个人页](https://sais.sjtu.edu.cn/faculty/1611.html)|
|sjtu / baiyang|research_direction_raw|移动智能、边缘计算，智能网络资源优化|[个人页](https://sais.sjtu.edu.cn/faculty/baiyang.html)|
|sjtu / baoqilian|research_direction_raw|组合导航,数据融合技术,智能控制。|[个人页](https://sais.sjtu.edu.cn/faculty/baoqilian.html)|
|sjtu / caiyunze|research_direction_raw|智能感知和决策优化，包括： 1. 多传感器信息融合，目标检测、定位与跟踪； 2. 多智能体强化学习，博弈对抗； 3. 智能控制和协同规划|[个人页](https://sais.sjtu.edu.cn/faculty/caiyunze.html)|
|sjtu / caochengxi|research_direction_raw|POCT诊断技术,糖尿病地贫诊断技术,自由流电泳技术,界面电泳与传感|[个人页](https://sais.sjtu.edu.cn/faculty/caochengxi.html)|
|sjtu / cengguihua|research_direction_raw|量子密码通信技术、量子传感技术、量子成像技术以及智能量子信息技术|[个人页](https://sais.sjtu.edu.cn/faculty/zengguihua.html)|
|sjtu / chencailian|research_direction_raw|工业互联网与工业具身智能（VTLA）<br>先进运载装备（纯电飞机、垂直起降飞行器eVTOL、无人机等）信息互联<br>低轨卫星星座网络确定性传输<br>感知-传输-控制一体化设计理论与方法|[个人页](https://sais.sjtu.edu.cn/faculty/chencailian.html)|
|sjtu / chenghao|research_direction_raw|机器学习、医学图像处理、智能诊断仪器开发|[个人页](https://sais.sjtu.edu.cn/faculty/chenghao.html)|
|sjtu / chenhongtian|research_direction_raw|故障诊断与容错控制<br>水下机器人<br>可解释性人工智能技术<br>海-陆-空系统<br>在上述研究基础上，获得<br>国家高层次青年人才、上海市高等教育优才揽蓄人才、玛丽·居里学者、上海市高层次人才、浦江学者<br>等。|[个人页](https://sais.sjtu.edu.cn/faculty/chenhongtian.html)|
|sjtu / chenweidong|research_direction_raw|移动机器人<br>多机器人系统<br>移动操作臂<br>医疗机器人|[个人页](https://sais.sjtu.edu.cn/faculty/chenweidong.html)|
|sjtu / chenxin|research_direction_raw|AI+PNT；GNSS信号处理技术；导航安全与对抗；电磁信号大模型及应用<br>课题组长期招收：博士生、硕士生（含中电科联培）|[个人页](https://sais.sjtu.edu.cn/faculty/chenxin.html)|
|sjtu / chenyongbo|research_direction_raw|机器人室内导航，不确定下规划，机器人系统学习算法应用|[个人页](https://sais.sjtu.edu.cn/faculty/chenyongbo.html)|
|sjtu / chenyouren|research_direction_raw|智能交通系统，信息融合,绿色能源|[个人页](https://sais.sjtu.edu.cn/faculty/chenyouren.html)|
|sjtu / cuidaxiang|research_direction_raw|基于纳米效应的胃癌预警与早期诊断系统;智能纳米传感检测技术;智能纳米药物递送系统、纳米细胞治疗技术。|[个人页](https://sais.sjtu.edu.cn/faculty/cuidaxiang.html)|
|sjtu / daibin|research_direction_raw|多肽/蛋白自组装, 生物灵感材料、高分子材料, 生物智能传感器|[个人页](https://sais.sjtu.edu.cn/faculty/daibin.html)|
|sjtu / daiwenbin|research_direction_raw|工业控制软件（IEC 61131-3，IEC 61499）<br>工业操作系统<br>代码自动构造|[个人页](https://sais.sjtu.edu.cn/faculty/daiwenbin.html)|

## 未写记录

- tsinghua / chenliping：no_missing_field_with_explicit_section。[官方页](https://www.au.tsinghua.edu.cn/info/1082/3229.htm)
- tsinghua / dongmingyu：no_missing_field_with_explicit_section。[官方页](https://www.au.tsinghua.edu.cn/info/1075/3216.htm)
- tsinghua / liuliyang：no_missing_field_with_explicit_section。[官方页](https://www.au.tsinghua.edu.cn/info/1078/3253.htm)
- tsinghua / lizhengang：no_missing_field_with_explicit_section。[官方页](https://www.au.tsinghua.edu.cn/info/1082/3231.htm)
- tsinghua / lvwenxiang：no_missing_field_with_explicit_section。[官方页](https://www.au.tsinghua.edu.cn/info/1082/3233.htm)
- tsinghua / maxichun：no_missing_field_with_explicit_section。[官方页](https://www.au.tsinghua.edu.cn/info/1082/3227.htm)
- tsinghua / qinjian：no_missing_field_with_explicit_section。[官方页](https://www.au.tsinghua.edu.cn/info/1082/3228.htm)
- tsinghua / xuewenxuan：no_missing_field_with_explicit_section。[官方页](https://www.au.tsinghua.edu.cn/info/1082/3232.htm)
- tsinghua / yangjianhua：no_missing_field_with_explicit_section。[官方页](https://www.au.tsinghua.edu.cn/info/1082/3234.htm)
- tsinghua / zhangjun：no_missing_field_with_explicit_section。[官方页](https://www.au.tsinghua.edu.cn/info/1080/4225.htm)
- tsinghua / fanwenhui：no_missing_field_with_explicit_section。[官方页](https://www.au.tsinghua.edu.cn/info/1075/3208.htm)
- tsinghua / fengshuo：no_missing_field_with_explicit_section。[官方页](https://www.au.tsinghua.edu.cn/info/1076/3247.htm)
- tsinghua / gaofeifei：no_missing_field_with_explicit_section。[官方页](https://www.au.tsinghua.edu.cn/info/1078/3261.htm)
- tsinghua / guanxiaohong：no_missing_field_with_explicit_section。[官方页](https://www.au.tsinghua.edu.cn/info/1076/3185.htm)
- tsinghua / hexiuqiang：no_missing_field_with_explicit_section。[官方页](https://www.au.tsinghua.edu.cn/info/1079/4192.htm)

## 后续建议

先验证字段试点能改善方向筛选与详情阅读，再按已注册官网模板扩大；每轮保留缺失原因与检查日。自动化与感知目录中存在生物传感、医疗仪器等跨学科方向，应让学生看到原文并判断研究匹配，不把整个院系视为全部适合CS申请。
