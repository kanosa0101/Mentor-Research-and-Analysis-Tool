# 项目交接文档（HANDOVER）

> 写给下一个接手的 agent / 开发者。读完这篇应该能不问人直接干活。
> 最后更新：2026-09-05（晚），数据基线 31 校 37 院系 4908 人（`audit.py` 实测）。
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

## 2. 当前状态（2026-09-06 实测）

- **36 校 42 院系 5654 人**，全量 YAML 落盘 + 静态网站可浏览
- 全库字段覆盖：**邮箱 4515（80%）、职称 4219（75%）、简介 3539（62%）、博导硕导 2267（40%）**
- 各院系明细见 §3；各院系人数与覆盖率随时可跑 `audit.py` 复核
- git：`main` 分支，远端 `https://github.com/kanosa0101/Mentor-Research-and-Analysis-Tool`，已推送
- preflight 绿（0 PROBLEM）；open issues 均已人工复验标 `reviewed`（官网死链/外部主页被墙/官网字段确缺），如实留痕
- 环境：Windows + Python 3.14（anaconda），依赖 requests/pyyaml/jinja2/pydantic/bs4/pypinyin/playwright+chromium/openpyxl（浙大 xlsx 用）、**rapidocr-onnxruntime（图片邮箱 OCR，jlu_cs）**；**CDP 真实 Chrome 后端（crawler/fetch.py，破瑞数/网防）**
- **邮箱是最关键字段（仅次于姓名，用户明确要求）**。获取手段已六类齐备：① tsites 密文解密接口 ② WP meta description 字段兜底 ③ sudy generalQuery POST 接口 ④ 页面明文/简介正则 + tsites 明文四形态兜底（§7.30）⑤ CDP 真实浏览器穿透 WAF 后的明文字段（北邮 80%/重大 88%/电子科大 97%）⑥ **详情页图片邮箱 rapidocr 识别**（吉大 43→71%，§7.43）
  邮箱 <95% 的院系均已逐页核验：确认真缺失的留痕（csu/dlut 站点侧问题——dlut 解密接口已复测为挂死、hnu 70% 官网字段空白、scut 73% meta 截断、bupt 80% 主页无邮箱字段、neu 40 人/tongji 52 人正文确无邮箱）；仍有提升空间的（xjtu 68%、ruc/ai 67%）在 §9 列为下一步

## 3. 数据现状：已接入 36 个院系（audit.py 实测，2026-09-06）

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
| tongji/cs | wp | 156 | 100% | 66% | 6% | 78% | 0 |
| sdu/cs | simple_list | 17 | 94% | 64% | 0 | 100% | 0 |
| sysu/cs | sysu_cs(渲染) | 112 | 98% | 97% | 0 | 0 | 96% |
| neu/cs | neu_cs(委托wp) | 147 | 72% | 72% | 2% | 89% | 0 |
| jlu/cs | jlu_cs(simple_list+图片邮箱OCR) | 185 | 95% | 71% | 11% | 97% | 0 |
| ecnu/cs | ecnu_cs(改造wp) | 70 | 98% | 100% | 0 | 98% | 0 |
| nwpu/cs | simple_list | 23 | 0 | 0 | 0 | 0 | 0 |
| csu/cs | tsites | 108 | 85% | 71% | 80% | 73% | 52% |
| ruc/ai | simple_list | 31 | 100% | 67% | 0 | 41% | 0 |
| xidian/cs | xidian_cs(委托tsites) | 155 | 94% | 90% | 69% | 99% | 62% |
| bnu/ai | bnu_ai | 72 | 79% | 73% | 79% | 61% | 69% |
| xjtu/cs | xjtu_cs | 75 | 62% | 68% | 78% | 13% | 22% |
| scu/cs | scu_cs(委托tsites) | 166 | 71% | 90% | 0 | 65% | 42% |
| zju/cs | zju_cs(名录+xlsx+CDP person) | 438 | 37% | 33% | 99% | 35% | 38% |
| sustech/cs | sustech_cs | 39 | 100% | 100% | 0 | 28% | 0 |
| shanghaitech/cs | sist_cs | 149 | 65% | 98% | 59% | 0 | 59% |
| seu/cs | seu_cs | 128 | 100% | 85% | 86% | 67% | 97% |
| fudan/cs | fudan_cs(generalQuery) | 189 | 100% | 99% | 66% | 0 | 39% |
| xmu/cs | xmu_cs | 51 | 100% | 7% | 5% | 9% | 1% |
| dlut/cs | dlut_cs(委托tsites) | 12 | 100% | 8% | 83% | 83% | 100% |
| dlut/ss | dlut_cs(委托tsites) | 12 | 100% | 0 | 58% | 66% | 75% |
| buaa/cs | buaa_cs(卡片+目录翻页) | 82 | 100% | 96% | 8% | 98% | 0 |
| tju/cs | tju_cs(名录锚文字+wp) | 114 | 99% | 99% | 82% | 98% | 0 |
| bit/cs | bit_cs(渲染名录+summary) | 151 | 81% | 88% | 100% | 90% | 0 |
| ruc/info | ruc_info(hash名录+.content) | 67 | 94% | 95% | 46% | 62% | 0 |
| hnu/cs | hnu_cs(卡片表+people详情) | 187 | 94% | 70% | 0 | 82% | 0 |
| scut/cs | scut_cs(职称三栏目+meta) | 76 | 100% | 73% | 14% | 67% | 0 |
| bupt/cs | bupt_cs(CDP名录+tsites明文+jsxx子页) | 217 | 35% | 80% | 28% | 0 | 0 |
| cqu/cs | cqu_cs(CDP导师名单+faculty子页) | 77 | 68% | 88% | 100% | 85% | 0 |
| uestc/cs | uestc_cs(CDP筛选列表+info文章) | 189 | 100% | 97% | 5% | 62% | 0 |
| hit/cs | hit_cs(jsml+CDP导师名单) | 240 | 0 | 0 | 70% | 0 | 0 |
| **合计** | | **5654** | | | | | |

要点：
- hit 详情无源已定论（教师主页是内网穿透地址外网 404），但博导/硕导名单页（cs.hit.edu.cn/22195/22196，CDP 渲染）已补 supervisor 168/240；nwpu 是纯名单（roster 级，无详情）；ucas/iie 是导师名单文章（姓名+博导+研究室+邮箱来自文章表格）；zju 438 人中 374 人为 xlsx 名录级（只有姓名+导师资格+学科），person.zju.edu.cn 主页 CDP 已可抓（66 人名录链接者已富化 59 邮箱）；**门户搜索接口已逆向（§7.41）**：/server/api/front/psons/search 全校 5841 人可拉，计算机学院 169 人匹配入库 103 人 detail_url 修正为 person 主页（CDP 富化），邮箱 13→33%、职称 14→37%；剩余 271 名 xlsx 导师接口无记录（无 person 主页），拼音猜测全 404
- xidian/川大邮箱经 tsites 解密接口还原 + 明文四形态兜底；上科大/复旦走 generalQuery POST 接口；复旦 bio 经核实官网侧无源（generalQuery 无简介字段、exField5"个人主页"文章页是空壳），homepage 链接已入库（107 人）
- xmu 43 条详情死链是官网本身 404（已逐一留痕并 reviewed）；dlut tsites 解密接口已复测为**服务端挂死**（requests/CDP 三路超时，浏览器也显示为空），属站点侧故障、23 人留痕（§7.45）；tju 1 条官网死链留痕
- **存量低覆盖专项（2026-09-06 完成）**：scu 职称 23→71%（tsites bs 信息块"职务：教授"标签扫描，§tsites.py）；jlu 邮箱 43→71%（**图片邮箱 OCR** 52 人全目检，§7.43）；neu 邮箱 53→72%（简介正文标签变体搜索 +29 人，页脚公邮陷阱 40 人留痕，§7.44）；tongji 邮箱 58→66%（wp @ 扫描粘连修复 +13 人，52 人留痕，§7.44）；dlut 解密接口挂死定论（§7.45）
- bit 邮箱 88%/职称 81%：抽查确认 summary 卡片"职称：/E-mail："为空 = 官网没填；csu 剩余 31 人无邮箱经 tsites 主页+子页两轮核实为官网无邮箱字段
- **hnu（09-05 接入）**：域名是 **csee.hnu.edu.cn**（cs.hnu.edu.cn 是阻断主因——域名错了）；卡片表名录 6 页（按职称分类频道）+ /people/<id> 详情表；邮箱 70% 抽查确认为官网"电子邮件"字段真空白（页脚 xiaoban@hnu.edu.cn 是公邮，勿录）；无博导硕导字段
- **scut（09-05 接入）**：www2.scut.edu.cn/cs；师资按职称分三栏目（22284 教授/22285 副教授/22286 讲师），栏目名即 roster 级职称；正文只有介绍图片的页面字段全靠 meta description（§7.35），面包屑兜底职称；专职研究人员栏目（zzyjry）是 AJAX 空壳未接
- **CDP 三连（09-05 接入，§7.39）**：北邮 217（scs 名录 → teacher.bupt tsites 主页，邮箱明文、无密文 span，职称 30%=主页只有职务）；重大 77（cs.cqu.edu.cn 渲染导师名单 → faculty.cqu.edu.cn 个人信息在 yjgk 子页，导师资格 roster 级 100%）；电子科大 189（js_sz.jsp GET 筛选 FirstLetter+A-Z → info 文章页，职称 roster 级 100%、邮箱 97%）

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

已接入 36 校（清单见 §3）。范围内**未接入**的只剩：

- **华科**：09-06 复测直连+代理均 ConnectTimeout（TCP 层不通，纯网络阻断）——网络稳定后复测，通了可试 CDP
- **南开**：09-06 复测 cc/cs 两域直连+代理均 ConnectTimeout（TCP 层不通）——网络稳定后复测
- **放弃**（1 所）：国防科大（军队院校，用户明确不考虑）

**WAF 阻断组已全部攻克（2026-09-05，CDP 真实浏览器后端 §7.39）**：北邮（瑞数 412）→ 217 人、重大（瑞数 412 + JS 壳列表）→ 77 人、电子科大（网防 202）→ 189 人。原理：瑞数/网防拦的是客户端指纹，CDP 连本机真实 Chrome（真实插件/字体/历史 cookie）即放行；服务端代读通道曾证明内容可读但不可管线化，CDP 是管线化的正解。浙大 person.zju（瑞数）、哈工大教师系统也可用同一路径富化（§9）。

**重要**：此前一批"连不上"的学校其实是**官网域名用错了**（如北邮是 scs 不是 scse、西电是 cs 不是 computer、南科大是 cse 不是 cs、中南是 cse 不是 sca、**湖大是 csee 不是 cs（09-05 已验证接入）**、**华南理工是 www2（09-05 已验证接入）**、上科大是 sist 无 cs 前缀、人大是 ai.ruc.edu.cn、**浙大计算机是 www.cs.zju.edu.cn 且真实站点在 /csen/ 路径下**）。且"网络阻断"结论会过期——**北航/北理工/天大/人大信息学院 09-05 复测突然就通了**。接新校前先 websearch 核实官方域名 + 跑 retest 复测。

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

**2026-09-05 下午新增（四所新校 + tsites 二轮）**
30. **正则量词边界坑（两连）**：`电子?邮箱` 解析为"电(必选)+子(可选)+邮箱"，纯"邮箱"开头的行反而匹配不上——量词要括起来 `(?:电子)?邮箱`。北航 `电子邮箱`（先"电话"后"邮箱"交替都不命中开头"电"）同理。**写标签正则先拿真实样本验证**，别脑补
31. **tsites 明文邮箱四形态**（`sites/tsites.py` 兜底，全部只在 email 缺失时触发）：① 裸 `<p>xxx@yy</p>` 无任何标签（西交 gr.xjtu）→ 全页唯一邮箱才采用，多个时取与站点同校域的（官方域 vs QQ/163 并存）② `电子邮箱：` 标签行 + 值在下一个兄弟元素（西电 web.xidian 跨 `<p>`）③ mailto href 是明文但锚文本混淆（"hchgao AT xidian.edu.cn"）④ span id 即语义（`_tsites_encryp_tsteacher_tsemail`，父容器无标签文字）；另 `Email:`（无连字符）是 `E-mail` 之外的高频变体。战果：xjtu 29→68%、xidian 53→90%、csu 56→71%（csu 剩余经主页+子页两轮核实为官网无邮箱字段）
32. **VSB CMS 三级跳转**（天大/人大信院）：栏目首页是 807B 的 `window.location.href` 跳转壳，真实列表在 `azc/zgj/1.htm` 这类三层路径下，翻页是 `/N.htm` 目录形态；人大信院落地页是 hash 链接（32位hex.htm）+ index2.htm 翻页，锚文字粘连"姓名研究方向…讲授课程…"，姓名取开头汉字段即可
33. **北理工名录是渲染后注入**：原始 HTML 和渲染早期都没有人员链接，`fetch_rendered(wait_ms=6000, scroll=True)` 后出现（32 位 hash 链接）；详情页却是服务端渲染（直接 requests 可解析）。**渲染失败先怀疑等待不够**，别急着下"SPA"结论（§7.25 同款教训）。另外钩子返回的 url 必须 urljoin 成绝对路径——crawl.py 的别名提取 `rsplit("/",1)[1]` 对无斜杠相对路径会 IndexError
34. **crawl.py roster 拷贝字段**：`phase_roster` 只拷贝 title/email/phone/supervisor/subjects/research_direction_raw/photo_url/**homepage**——给 rec 塞其他字段（如 homepage 曾被静默丢弃）要先核对这个列表
35. **WP meta description 标签变体又添一例（华南理工）**：meta 里写的是 `E-mail：`（带连字符），`_meta_fields` 的 labels 只有 `Email` 匹配不上——labels 清单现已含 `E-mail`。**WP meta 标签拼写无穷变体，新站接入先 dump meta description 全文核对**。华南理工正文只有一张介绍图片（`wp_articlecontent` 空壳、无 `v_news_content`），字段全靠 meta；`box is None` 分支已改为 meta 兜底 + bio_raw
36. **WP 站师资按职称分栏目 = roster 级职称白送（华南理工）**：`22284/list.htm`（教授）、`22285`（副教授）、`22286`（讲师/助理教授）是三个栏目——只抓第一个会漏 57% 的人（华南理工 33→76 人、职称 57%→100%）。channel 带 `cat:` 字段进 `list_title`。**接 WP 站先翻全站导航找师资栏目树**。面包屑"师资队伍 > 教授"是详情页职称兜底信号（scut_cs 的 `_BREADCRUMB_TITLE`）
37. **页脚公共邮箱陷阱（湖大/华南理工）**：湖大详情页"电子邮件"字段为空但页脚备案区有 `xiaoban@hnu.edu.cn`，华南理工页脚有 `x2js@scut.edu.cn`——全页正则会吃到，**必须排除页脚/备案区，绝不能把学院公邮录成教师邮箱**（宁可缺）。湖大 55 人无邮箱经抽查为官网"电子邮件"字段真空白
38. **preflight issue 的 reviewed 语义**：官网死链（xmu 43 条 404、tju/bnu 各 1-2 条）和外部主页被墙（sustech scholar.google 403）是**如实记录**，不该删；preflight 只对未复验的 open issue 报 PROBLEM，人工复验后在 issue 条目加 `reviewed: true`。**"网络抖动"类 issue 先重跑再判**：sustech 两条 ConnectionError 复测时已恢复
39. **CDP 真实浏览器后端（破瑞数/网防的定论方案，crawler/fetch.py）**：① `_ensure_chrome_debug()` 启动本机真实 Chrome（独立 profile `cache/chrome-profile`，不动用户日常会话）监听 9222，playwright `connect_over_cdp` 接管，用默认上下文（保留指纹/cookie）新开页抓完即关 ② `fetch()` 对 **412/403/503** 抛错时自动降级 `fetch_cdp`；**网防 wengine 走 202 短响应（requests 视为成功）**，按 `status==202 且 body<10KB` 特征降级 ③ 两个大坑：**环境变量 http_proxy 是 SOCKS（127.0.0.1:10808）时 `proxies={"http":None}` 不禁用代理反而回退环境设置，探测回环 9222 必须 `trust_env=False`**；Chrome 启动要 15-30s，等待循环别设 10s ④ **两个爬虫进程不得同时用 CDP**（EPIPE：playwright driver 管道崩）——串行跑 ⑤ 列表页 requests 返回 200 的 JS 壳（重大）不会触发降级，hook 里必须**显式 `fetch_cdp(wait_ms=5000, scroll=True)`** ⑥ Chrome 走系统代理出口，瑞数照样放行（指纹优先于 IP）
41. **浙大 person 门户 API 逆向（appkey/sign 签名）**：前端 emitAjax 三件套——`appkey = Base64→Hex(反转的Base64串)`、`sign = MD5(salt + path + sorted_kv(data) + timestamp + " " + salt)`（salt 也是 Base64→Hex 固定串）、`timestamp` 毫秒。请求走 `/server/api/front/psons/search?size=100&page=N`（**/server 前缀**，不带它 403/Access denied——那是前端代理路径），返回 JSON（totalElements=5841 全校）。API 本身不被瑞数拦（裸 requests 也能调，缺签名头才 400），**页面内 fetch/XHR 反而 403**（瑞数 4 对 XHR 注动态 token，但应用层签名缺了照样 403——两层签名别混淆）。UI 路线注意：SPA 是 history 路由，服务端真实路径带 `/index` 前缀（/index/search），直接 goto 可渲染
42. **北邮 tsites 的 jsxx 子页才有 职称/导师资格**（主页只有职务/单位/邮箱/办公地点），链接形态 `/<py>/zh_CN/jsxx/<id>/jsxx/jsxx.htm`，字段标签与值常分两行（"职称：
教授"）——职称正则要带下一行兜底
43. **详情页"邮箱值是防爬 PNG 图片"（吉大）→ rapidocr 本地 OCR 管线（sites/jlu/jlu_cs.py）**：`<td>Email：</td><td><img …>` 值列是 18px 高的小图，rapidocr 的 **det 模型对细长低对比单行图会丢前段**——直接调 `ocr.text_recognizer(整行放大6x图)` 整行识别才稳。识别结果常把 @ 后域名拆碎/漏字，**修复策略是只信 @ 前的 local part + 已知域名重组**（该院邮箱域固定）；混淆形态"xxx at yyy/[AT]"在去空格前先还原为 @。**OCR 结果必须目检**：52 张图拼成大图逐一核对，揪出 l/1、l/I、c/e 字符级混淆 2 例（已改 manual origin 覆盖）。另注意 vsb CMS 的 img 真实路径在 **vurl 属性**（src 可能是丢目录的相对名），且 vurl 有 `/_vsl/…` 缩略图形态（OCR 必败），要 vurl→src 依次回退
44. **wp 邮箱提取两处新坑（同济/东北暴露）**：① `box.get_text("", strip=True)` 无分隔拼接会把中文标签和邮箱粘成一个 token（"系方式：a@b.c"），normalize 的 ASCII `\w` 拒收——@ 扫描窗口内先用正则剥出纯邮箱再归一；② 邮箱正则 TLD `[A-Za-z]{2,}` 会把后续标签词吞进域名（"jlu.edu.cnWechat"）——**右边界前瞻挡不住纯字母**，解法是标签切分处按"WeChat/QQ/Tel…+冒号"预截断 + `email_util._tld_ok` 尾标签长度/白名单校验兜底。东北正文邮箱标签变体多（电子邮件/电子邮箱/联系方式/邮件联系），且常被 span 隔断——**在 get_text 纯文本上按变体搜**（neu_cs），页脚公邮 neucse 由过滤兜底
45. **dlut tsites 解密接口挂死实锤（复测 2026-09-06）**：tsitesencrypt.jsp 在 requests 直连/代理/CDP 真浏览器三路下均 >20s 无响应挂起（页面本身 0.6s 可达），浏览器渲染同样空——**站点侧故障，唯一邮箱来源不可用**；英文版页面亦整体超时。23 人按 `email_missing_source_side` 留痕 reviewed，等站点恢复后 `crawl --refresh` 重跑即可
46. **重大 tsites 是"成果展示型"**：faculty.cqu.edu.cn 的 index.htm 只有论文/专利栏目，**个人信息（职称/导师/邮箱）在 yjgk 子页**（栏目 ID 每人不同，从主页导航正则找）；邮箱标签是"联系方式："不是"电子邮箱"。北邮 tsites 相反——无密文 span，邮箱明文在 `div#gerenxinxi`。电子科大师资卡片 `span.name` 第二个就是职称（roster 级白送）；列表分页参数是 **`&fromWenCountNo=99`**（GET 生效）

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

## 9. 后续计划（2026-09-05 制定，按价值排序）

**阶段一：远程渲染后端（✅ 已完成）**
- CDP 真实浏览器后端已上线（§7.39），北邮 217/重大 77/电子科大 189 三校接入，全库 33→36 校

**阶段二：CDP 红利扩收 + 存量第三轮补全（当前焦点）**
1. **浙大**：名录只链 66 人（已确认上限），59 人邮箱/简介已得；**374 名 xlsx 导师需逆向 person.zju 门户搜索接口**（Vue SPA + 瑞数，CDP 已过 WAF，剩接口逆向）——预期全库邮箱 +200~300
2. **哈工大 ✅ supervisor 168/240**：博导/硕导名单页（cs.hit.edu.cn/22195、22196）CDP 渲染按姓名合并；详情无源已定论——教师主页是内网穿透地址（homepage-hit-edu-cn.ivpn.hit.edu.cn:1080，外网 404），cs.hit 主站已通但教师详情只在校内
3. **北邮职称 30% → 子页挖掘**：teacher.bupt 主页"更多"子页（jsxx）可能有职称/方向
4. ~~scu 职称 23% / dlut 解密接口复测 / jlu 43% / neu 53% / tongji 58% 逐校专项~~ **✅ 2026-09-06 完成**（scu 职称 71%、jlu 邮箱 71%、neu 72%、tongji 66%、dlut 挂死定论，§3 要点）；xmu 邮箱 7% 死链已逐一留痕（官网 404，无绕行来源）——剩余 xjtu 68% / ruc-ai 67% 待挖
5. supervisor 全库 36% 排查：tsites 系详情页"博导/硕导"标注漏抓检查（套磁筛导师关键字段）
6. verified 人工核对启动：每校抽 10 人核对 provenance（需用户参与）
7. 华科/南开复测（通了可试 CDP）

**阶段三：产品层启动（顺序待用户定）**
1. 状态写回 + 套磁看板：意向/已发/已回状态管理——套磁工作流核心，建议最先做
2. 对比页（P3，已推迟）：3-5 位导师并排对比
3. AI 分析层：LLM 结构化研究方向/简介 → 学生画像匹配（需要 LLM API）
4. SOP/申请信生成

**运维常态**：月度 `crawl --refresh` 全量 + audit + preflight；CDP 后端注意 §7.39 的坑（串行、SOCKS 回环、启动等待）

**决策点**：① CDP 需要本机 Chrome（已自动化启动，无需用户配合）② AI 层需要 LLM API key ③ 阶段三内部顺序由用户按套磁工作流定

## 10. 给下一个 agent 的三句话

1. **先跑 `preflight.py` 和 `audit.py`，再动任何代码**——它们绿了才说明你理解的数据状态和真实状态一致
2. **接新校先 websearch 官方域名，再 dump 原始 HTML 找数据真实位置**（锚点属性/内文/script 变量/ajax 三选一），九连败的教训全在 §7
3. **所有 UI 改动用 Playwright 打开页面验证 console 无错 + DOM 断言**，`#count` 是全库总数不是筛选数
