# 项目交接文档（HANDOVER）

> 写给下一个接手的 agent / 开发者。读完这篇应该能不问人直接干活。
> 最后更新：2026-09-05，对应 git 基线 `698788e`。
> 配套阅读：`REQUIREMENTS.md`（需求与决策）、`ARCHITECTURE.md`（架构与数据模型）、`README.md`（用户视角速览）。
> 架构、数据模型、七种站点范式、目录结构 → 全部在 ARCHITECTURE.md，本篇只讲**现状、踩坑、操作**。

---

## 1. 这个项目是什么

**一句话**：把国内目标院校 CS 相关院系官网上的师资信息，抓成一张全量、可浏览、可筛选、逐字段可溯源的导师表，最终服务于"给导师写套磁信"这件事。

**用户场景**：用户在准备 2027 年入学的研究生申请（推免/考研/申请考核），需要在数百所学校的上千名导师里找到"方向对得上、今年有名额"的人，然后逐一联系。工具的核心价值：**汇聚（全量名单）→ 筛选（方向/职称/博导）→ 溯源（每个字段点回官网原文）→ 未来再补（联系状态跟踪、信件草稿）**。

**明确的边界**（需求 v0.6 §8 有完整决策记录）：
- 不爬口碑内容（知乎/一亩三分地），不批量群发，不编造数据
- AI 归纳层、学术数据层（DBLP/OpenAlex）、学生画像、SOP+信件、状态写回看板 → 全部设计保留在 REQUIREMENTS.md §8，**延后未做**
- 原则：官网没写的就是没有，值留空显示"官网未提供"，绝不推测填充

## 2. 当前状态（2026-09-05 实测）

- **28 校 33 院系 4494 人**，全量 YAML 落盘 + 静态网站可浏览
- 全库字段覆盖：**邮箱 3227（72%）、职称 3084（69%）、简介 2662（59%）、博导硕导 1655（37%）**
- 各院系明细见 §6；各院系人数与覆盖率随时可跑 `audit.py` 复核
- git：`main` 分支，远端 `https://github.com/kanosa0101/Mentor-Research-and-Analysis-Tool`，已推送（最新 `698788e`）
- preflight 仅 48 条 open issues：北师大 2 条官网死链 + 南科大 3 条教师外链 + 厦大 43 条详情死链（官方 404，留痕）
- 环境：Windows + Python 3.14（anaconda），依赖 requests/pyyaml/jinja2/pydantic/bs4/pypinyin/playwright+chromium/openpyxl（浙大 xlsx 用）
- **邮箱是最关键字段（仅次于姓名，用户明确要求）**。获取手段已四类齐备：① tsites 密文解密接口 ② WP meta description 字段兜底 ③ sudy generalQuery POST 接口 ④ 页面明文/简介正则。
  **邮箱 <95% 的院系基本都查过问题**（用户教训：低覆盖大概率是找错页/解析漏，不能断言"官网没有"——已修复 5 类系统性漏提取，见 §10.27）；剩余低覆盖院系逐一核实为官网侧原因，但接手后建议对 xjtu/csu/xidian 的 tsites 联系方式子页再抽查一轮。

## 3. 数据现状：已接入 33 个院系（audit.py 实测，2026-09-05）

| 院系 | hook | 人数 | 职称 | 邮箱 | 博导硕导 | 简介 | facets |
| ---- | ---- | ---- | ---- | ---- | ---- | ---- | ---- |
| sjtu/cs | sjtu_cs | 289 | 100% | 98% | 0 | 85% | 0 |
| sjtu/ai | sjtu_ai | 1 | 100% | 0 | 0 | 100% | 100% |
| tsinghua/cs | wp | 134 | 100% | 100% | 1% | 99% | 82% |
| pku/cs | pku_cs | 119 | 100% | 99% | 3% | 71% | 100% |
| hit/cs | hit_cs(渲染) | 240 | 0 | 0 | 0 | 0 | 0 |
| ucas/ict | ucas_ict | 283 | 100% | 92% | 75% | 98% | 60% |
| ucas/ia | ucas_ia | 345 | 99% | 99% | 0 | 100% | 0 |
| ucas/iscas | ucas_iscas | 182 | 0 | 98% | 100% | 63% | 98% |
| ucas/iie | ucas_iie | 283 | 1% | 96% | 0 | 0 | 69% |
| ustc/cs | wp | 72 | 100% | 97% | 0 | 98% | 0 |
| nju/cs | wp | 102 | 100% | 88% | 65% | 81% | 0 |
| whu/cs | simple_list | 109 | 89% | 88% | 53% | 91% | 0 |
| tongji/cs | simple_list | 156 | 100% | 58% | 6% | 78% | 0 |
| sdu/cs | simple_list | 17 | 94% | 64% | 0 | 100% | 0 |
| sysu/cs | sysu_cs(渲染) | 112 | 98% | 97% | 0 | 0 | 96% |
| neu/cs | neu_cs(委托wp) | 147 | 72% | 53% | 2% | 89% | 0 |
| jlu/cs | simple_list | 185 | 95% | 43% | 11% | 97% | 0 |
| ecnu/cs | ecnu_cs(改造wp) | 70 | 98% | 100% | 0 | 98% | 0 |
| nwpu/cs | simple_list | 23 | 0 | 0 | 0 | 0 | 0 |
| csu/cs | tsites | 108 | 85% | 56% | 80% | 73% | 45% |
| ruc/ai | simple_list | 31 | 100% | 67% | 0 | 41% | 0 |
| xidian/cs | xidian_cs(委托tsites) | 155 | 94% | 53% | 69% | 99% | 62% |
| bnu/ai | bnu_ai | 72 | 79% | 73% | 79% | 61% | 69% |
| xjtu/cs | xjtu_cs | 75 | 62% | 29% | 78% | 13% | 22% |
| scu/cs | scu_cs(委托tsites) | 166 | 23% | 90% | 0 | 65% | 42% |
| zju/cs | zju_cs | 438 | 14% | 13% | 99% | 13% | 14% |
| sustech/cs | sustech_cs | 39 | 100% | 100% | 0 | 28% | 0 |
| shanghaitech/cs | sist_cs | 149 | 65% | 98% | 59% | 0 | 59% |
| seu/cs | seu_cs | 128 | 100% | 85% | 86% | 67% | 97% |
| fudan/cs | fudan_cs(generalQuery) | 189 | 100% | 99% | 66% | 0 | 39% |
| xmu/cs | xmu_cs | 51 | 100% | 7% | 5% | 9% | 1% |
| dlut/cs | dlut_cs(委托tsites) | 12 | 100% | 8% | 83% | 83% | 100% |
| dlut/ss | dlut_cs(委托tsites) | 12 | 100% | 0 | 58% | 66% | 75% |
| **合计** | | **4494** | | | | | |

要点：
- hit/nwpu 是纯名单（roster 级，详情页网络不可达/无详情）；ucas/iie 是导师名单文章（姓名+博导+研究室+邮箱来自文章表格）；zju 438 人中 374 人为 xlsx 名录级（只有姓名+导师资格+学科），person.zju.edu.cn 简介在瑞数反爬后如实留空
- xidian/川大邮箱经 tsites 解密接口还原；上科大/复旦走 generalQuery POST 接口
- xmu 43 条详情死链是官网本身 404（已逐一留痕）；dlut tsites 解密接口返回截断值（浏览器也显示为空），属站点侧故障
- scu 职称 23%、zju/xjtu/xmu 低覆盖：已抽样核实为官网详情页无该字段，但符合"低覆盖=可疑"规律的，接手后可再抽查

## 4. 网站

- **列表页**：搜索、学校→院系级联、职称/导师资格/方向（多选 facet）筛选、全列排序、列显示开关（localStorage `adv_cols_v2`）、分页（每页 50 可调 20/50/100/500）
- **详情页**：字段卡片 + 简介原文 + provenance 出处表（每个字段点回官网原文）+ 新鲜度（first_seen/last_verified/官网 updatedAt）
- 表头表体由同一份 `HEADERS` 数组生成——**这是两次错位事故后的铁律，别改回两套**
- 零构建：Jinja2 模板 `site/templates/` → `build_site.py` 生成；UI 风格：白底紧凑工具栏（CSRankings/Linear 风），用户明确否决渐变横幅

## 5. 工具脚本

| 脚本 | 用途 | 何时跑 |
| ---- | ---- | ---- |
| scripts/crawl.py | 抓取入口（--school --dept [--phase roster/enrich] [--refresh]） | 加新校/更新数据 |
| scripts/build_site.py | 重建静态站（自动清理失效详情页） | 每次数据变化后 |
| scripts/audit.py | 覆盖率审计（各院系字段覆盖%） | 每轮迭代后 |
| scripts/preflight.py | 发布前体检（schema/邮箱/站点一致性/issues） | 提交前 |
| scripts/tag_facets.py | 重算方向 facet（13 类关键词规则） | 改规则后 |
| scripts/retest_direct.py | 重测"连不上"学校的直连连通性 | 网络环境变化后 |
| scripts/probe_direct_render.py | 对通了的学校直接看名录渲染结构 | retest 通过后 |
| scripts/verify_site.py | 站点抽查（页面数/关键内容/server） | build 后 |
| scripts/email_spotcheck.py / title_survey.py | 邮箱/职称抽查工具 | 回归排查 |
| scripts/probe_*.py | 一次性探针（历史调试用，可不看） | - |

## 6. 未接入的学校与剩余难点

已接入 28 校（清单见 §3）。范围内**未接入**的只剩网络/WAF 阻断组：

- **华科**：间歇性网络阻断（直连+代理都超时，间歇通断）——网络稳定后用 `retest_direct.py` 复测
- **WAF 拦截，需会话/cookie 重试**：北邮（**scs.bupt.edu.cn**，注意不是 scse）、重大、湖大（csee）
- **网络层阻断**：人大信息学院、华南理工（www2.scut.edu.cn 间歇）、南开、电子科大等
- **放弃**（1 所）：国防科大（军队院校）
- **低覆盖待挖**：xjtu/csu/xidian 的 tsites 联系方式子页可能藏邮箱；scu 职称、xmu 详情死链后无替代源；复旦 bio 0%（generalQuery 无简介字段，可试教师主页）

**重要**：此前一批"连不上"的学校其实是**官网域名用错了**（如北邮是 scs 不是 scse、西电是 cs 不是 computer、南科大是 cse 不是 cs、中南是 cse 不是 sca、湖大是 csee、华南理工是 www2、上科大是 sist 无 cs 前缀、人大是 ai.ruc.edu.cn、**浙大计算机是 www.cs.zju.edu.cn 且真实站点在 /csen/ 路径下**）。**接新校前先 websearch 核实官方域名**，这个教训花了一轮才学到。

## 7. 踩坑记录（每条都是真金白银的时间，接手前必读）

**解析层**
1. 锚点的 `title` 属性和内文**都可能被官网滥用**：哈工大姓名在 title、中南职称在 title——先 dump 卡片原始 HTML 再决定取哪个，别凭感觉
2. 列表数据可能藏在 `<script>` 模板字符串里（中科院 casasypage、上交 AJAX、川大 ImageScale 调用），BeautifulSoup 看不到，要对 raw html 正则提
3. 同一人可能有多条历史 URL（计算所 sourcedb 按日期多版本）——按**姓名**去重、保留 URL 日期目录最新的
4. 官网名单链接可能是裸相对路径（`ALL/9.htm`、`9.htm` 两种都见过），翻页正则要兼容
5. tsites（教师主页系统）的列表页 ajax 动态加载，渲染后也只有导航——需逆向其 XHR，别硬解析
6. 官网邮箱混淆格式大全：`bulei # nju.edu.cn`、`yangxubo [AT] sjtu.edu.cn`、`1051065502 AT QQ DOT COM`、`changwen(at)iscas.ac.cn`、标签和值跨行、span 碎片、`▇` 代替 @、分号双邮箱。`email_util.normalize_email` 全覆盖，**新混淆格式出现时在 normalize_email 加分支，并在 crawl 的 _merge 保证无效值不覆盖有效值**
7. pydantic 正则注意 `re.A`：`\w` 默认匹配中文，邮箱校验不放开

**工程层**
8. PowerShell 里写内联 `python -c "..."` 引号必炸——**一律写脚本文件再跑**（Git Bash 里 `python -c` 单引号包住可用）
9. Windows 控制台中文乱码是显示问题：命令前加 `$env:PYTHONIOENCODING='utf-8'`
10. `Set-Content` 写文件会带 BOM（曾毁过 crawl.py）；`nul` 是 Windows 保留设备名，glob 出来是假象
11. **表头表体必须同一份 HEADERS 数组生成**——两套来源两次错位事故
12. UI 验证的正确姿势：Playwright 打开页面抓 console/pageerror + 读 DOM 断言；`#count` 永远显示全库总数，**过滤效果看 pager 的 `.info`（共 X 人）**
13. git push 大包经代理 408：`git config http.version HTTP/1.1` 已配置，别删
14. 代理在 `127.0.0.1:10808`，"连不上"先区分：域名错（websearch 核实）vs 代理拦截（direct 模式）vs 真阻断（直连也重置）

**tsites 家族与近年战役（2026-09-04 ~ 09-05）**
15. **tsites 邮箱/电话密文可直接解**：页面里 `<span _tsites_encrypt_field>` 存密文，前端请求 `/system/resource/tsites/tsitesencrypt.jsp?id=..&content=..&mode=..` 服务端解密——直接调同一接口即可还原。已用于中南/西电/川大。实现见 `sites/tsites.py: decrypt_encrypted_fields`（注意：标签载体容器必须恰好只含一个密文 span，否则会串味——安莹邮箱被邮编污染过）
16. tsites 详情页有 4+ 种模板变体（字段块 h4/jbqk/data、散落行、`职务：X` 替代 `职称：`、标题带英文后缀 `<span>Personal Profile`），`_section_text` 匹配标题时要先剥掉英文字母
17. **西交**：列表页 requestUrl 是 http 混合内容，浏览器/渲染都加载不出；逆向 `getsitecontentlist.js` 得到 `getsitelistcontent.jsp` 数据接口，collegeId/treeid/siteOwner/viewid 参数从页面 `load_p` JS 对象里抄
18. **川大**：教师名单内嵌在列表页 `<script>` 的 `ImageScale(...).addimg(照片,主页URL,姓名,uid)` 调用里，raw html 正则提取
19. **浙大**：www.cs.zju.edu.cn 根路径只是引导壳，真实站点在 **/csen/** 路径下；教师名录页是 JS 渲染的表格；博导硕导直接用官方 xlsx 附件（418 人，openpyxl 解析）；person.zju.edu.cn 的简介在瑞数(frms-fingerprint)反爬后，如实留空——**但简介栏目可通过"同 Session 先取页再取 apiColumn 新鲜签名"绕过**（fetch.py 每次 new Session 会丢 cookie，必须在一个钩子函数里用 requests.Session 连着做）
20. **crawl.py 别名 bug**：`url.rsplit("/",1)[1][:-5]` 把 index.htm/page.htm 截成 inde/pag/lis/te 垃圾别名（全库 315 条已清理）；已改为剥真实扩展名 + 文件名无信息量时回退上一级目录名
21. **build_site.py 孤儿页**：slug 变更后旧详情页残留（中南事故 100 个）——重建时按当前名单清理失效页面，已修
22. 北师大列表形态：博导/硕导频道是**文章列表**（每学科一篇文章、表格按方向分组），不是教师列表；师资 zgj/fgj/zj 频道才是静态名单
23. **WP meta description 兜底**：很多 WP 站把 姓名/职称/电话/Email 压进 `<meta name="description">`（标签间无分隔符、全角空格），按已知标签切位置取值（`sites/wp.py: _meta_fields`）——吉大职称 80→95%、山大 0→94% 靠它。标签清单要含"联系电话/学科/导师类型/通讯地址"等无值边界，否则切片会串到下一字段
24. **sudy WP 通用查询接口**：上科大/复旦 `/_wp3services/generalQuery?queryObj=teacherHome` 是 **POST** 表单（siteId/conditions(exField8=分类)/returnInfos/rows=999），GET 会 500；请求须 trust_env=False + X-Requested-With 头。上科字段：title=姓名、exField1=职称+博导、exField4=方向、exField5=研究中心；复旦字段：exField1=职称+博导、exField4=方向、exField5=faculty 主页、exField8=博导硕导
25. **"SPA"结论要复检**：南科大被记为"JS 卡片加载"，实际是服务端渲染卡片（.teacherlist）——旧结论是渲染没等够/选择器没匹配上的误报。复旦"登录墙"也是错的（站点改名"计算与智能创新学院"，公开）。接手时先重新核实再信文档
26. 东南师资三频道（按职称/按方向/按系别）是纯文本名单（h2 + div.ry-md>p.ry-xm），无教师链接——三页按姓名合并出 职称/方向/系别；师资博士后（ry-bz 标注）不入库；博导库（dsxx）链接 cs.seu.edu.cn/<py>/main.htm 主页，详页有邮箱/职称/方向
27. **邮箱回归（2026-09-05 两轮，用户指正驱动）**：低覆盖院系必须抽查页面验证，不能凭解析结果断言"官网没有"。第一轮误判教训：北师大/同济/中科大的邮箱明明在页面里（电子邮箱变体/同行多字段/E-Mail 带空格/mailto 编码双邮箱/meta 无冒号标签），解析器没吃到。修复后 bnu 32→73%、ustc 64→97%、tongji 30→58%、sdu 52→64%、jlu 34→43%、fudan 0→99%、iie 0→96%、ecnu 100%。**确认真缺失的**：hit（jsml 无链接且教师系统网络不可达）、seu 名单页（主页有但未全接）、xjtu（页面无密文 span）、zju（瑞数）。**neu 注意**：页脚邮箱 neucse@cse.neu.edu.cn 是学院公邮（neu_cs 钩子已排除），本人邮箱在简介"电子邮件 xxx"句式里（53% 上限）
28. **职称归一化**：`crawler/title_util.py` 的 `normalize_title` 统一处理（括号导师资格拆进 supervisor、"、"分段、副高→副高级、前缀词表）；管线在 `_merge` 自动接入；存量 297 处已修。新职称词出现时在词表加一行
29. **preflight 的 payload↔data 一致性**：site/p/ 里残留孤儿页会报错——build_site.py 已自动清理，但手改 site/ 后要重跑 build

## 8. 操作手册

```powershell
# 日常
python scripts\crawl.py --school <s> --dept <d>            # 抓取（缓存优先）
python scripts\crawl.py --school <s> --dept <d> --refresh  # 强制回源（检测官网变化）
python scripts\build_site.py                               # 重建静态站
python -m http.server 8000 --directory site                # 本地预览 :8000

# 质量与检查
python scripts\audit.py        # 覆盖率审计
python scripts\preflight.py    # 提交前体检
python scripts\tag_facets.py   # 重算方向标签（改规则后）

# 扩展新校（先 websearch 核实官方域名！）
# 1) sites/<school>/<dept>.yaml  2) 钩子（或复用 wp/simple_list/tsites）  3) crawl → build_site
```

## 9. 建议的下一步（按价值排序）

1. **华科接入**：网络间歇阻断，用 `retest_direct.py` 复测，通了先抓计算机学院
2. **低覆盖院系二轮抽查**（用户教训：<95% 邮箱大概率有问题）：xjtu/csu/xidian 的 tsites 联系方式子页、seu 名单页邮箱、tongji 剩余 42%、jlu 剩余 57%
3. **复旦补全**：bio 0%（generalQuery 无简介），exField5 有 faculty 主页链接可跟进（注意"只存 URL 不抓正文"边界——faculty.fudan.edu.cn 属官网页面，可按需解边界）
4. **浙大补全**：xlsx 名录级 374 人可尝试 person.zju.edu.cn 主页富化（session cookie 方案已在 zju_cs.py 验证）
5. **facet 细化**：13 类关键词规则可继续调；evidence 可升级为记录命中原文片段
6. **附录 A 延后项**：学术数据层 → AI 分析层 → 学生画像+匹配+SOP+信件；对比页；状态写回+看板
7. **verified 人工核对**：未启动；最小方案=每校抽 10 人核对 provenance
8. 官网改版是常态：`crawl --refresh` + changes 日志；南科大"SPA"误报的教训（§7.25）——文档结论要复检

## 10. 给下一个 agent 的三句话

1. **先跑 `preflight.py` 和 `audit.py`，再动任何代码**——它们绿了才说明你理解的数据状态和真实状态一致
2. **接新校先 websearch 官方域名，再 dump 原始 HTML 找数据真实位置**（锚点属性/内文/script 变量/ajax 三选一），九连败的教训全在 §7
3. **所有 UI 改动用 Playwright 打开页面验证 console 无错 + DOM 断言**，`#count` 是全库总数不是筛选数
