# 项目交接文档（HANDOVER）

> 写给下一个接手的 agent / 开发者。读完这篇应该能不问人直接干活。
> 最后更新：2026-09-03，对应 git 基线 `ac37058`。
> 配套阅读：`README.md`（用户视角速览）、`REQUIREMENTS.md`（v0.5 需求与决策记录）。

---

## 1. 这个项目是什么

**一句话**：把国内目标院校 CS 相关院系官网上的师资信息，抓成一张全量、可浏览、可筛选、逐字段可溯源的导师表，最终服务于"给导师写套磁信"这件事。

**用户场景**：用户在准备 2027 年入学的研究生申请（推免/考研/申请考核），需要在数百所学校的上千名导师里找到"方向对得上、今年有名额"的人，然后逐一联系。工具的核心价值：**汇聚（全量名单）→ 筛选（方向/职称/博导）→ 溯源（每个字段点回官网原文）→ 未来再补（联系状态跟踪、信件草稿）**。

**明确的边界**（需求 v0.5 第 9 节有完整决策记录）：
- 不爬口碑内容（知乎/一亩三分地），不批量群发，不编造数据
- AI 归纳层、学术数据层（DBLP/OpenAlex）、学生画像、SOP+信件、状态写回看板 → 全部设计保留在 REQUIREMENTS.md 附录 A，**延后未做**
- 原则：官网没写的就是没有，值留空显示"官网未提供"，绝不推测填充

## 2. 当前状态

- **18 校 22 院系 2913 人**，全量 YAML 落盘 + 静态网站可浏览
- git：`main` 分支，远端 `https://github.com/kanosa0101/Mentor-Research-and-Analysis-Tool`，已推送至 `ac37058`
- preflight（发布前检查）0 问题；issues 队列仅 1 条 open（西电一个官网死链 404，有意留痕）
- 环境：Windows + Python 3.14（anaconda），依赖 requests/pyyaml/jinja2/pydantic/bs4/pypinyin/playwright+chromium

## 3. 架构与目录

```
crawler/            核心库（与具体学校无关）
  fetch.py          HTTP 层：缓存优先/限速0.5s/3次重试/渲染抓取/直连开关
  model.py          pydantic 模型：Professor / Provenance / Facet / Issue
  store.py          YAML 读写 / issues / changes(JSONL追加) / 手改保护
  email_util.py     邮箱混淆还原 + 严格校验（re.A，防 CJK 混入）
sites/              每校一层
  wp.py             博达/WP CMS 通用钩子（分类频道+listN翻页+person_href）
  simple_list.py    单页静态名录通用钩子（person_href 精确匹配）
  tsites.py         tsites 教师系统通用钩子（渲染版，目前仅中南成功）
  <school>/<dept>.yaml   一院系一配置（入口URL/person_href/钩子名/direct/roster_only）
  <school>/<hook>.py     该校解析钩子（通用钩子覆盖不了时才写）
scripts/            入口与工具（见 §8）
data/               产出（进 git）
  schools.yaml      33 校清单（tier/include）——T3 已解冻
  professors/<school>/<dept>/<slug>.yaml   一人一文件
  issues/<school>-<dept>.yaml              解析失败/名单消失队列
  changes/<school>-<dept>.jsonl            字段变更日志（只追加）
cache/http/         原始响应缓存（gitignore，重跑零新请求的关键）
site/               生成的静态网站（进 git）：index.html + p/<school-dept-slug>.html
```

数据流：`配置+钩子 → fetch(缓存) → 解析 → roster(名单) → enrich(详情富化) → YAML；build_site.py → 静态站`。

## 4. 数据模型要点

一位导师的 YAML 长这样（节选）：

```yaml
slug: zangbinyu            # 拼音，同院系撞名加 -2；跨院系同名是合法双聘，不去重
name: 臧斌宇
school: sjtu
dept: cs
status: enriched           # roster(仅名单) → enriched(已富化) → verified(人工核对，尚未启用)
title: 长聘教授
supervisor: 博导            # 博导/硕导，需求 4.4 的字段
email: byzang@sjtu.edu.cn
institutes: [并行与分布式系统研究所]
bio_raw: "..."             # 官网简介原文，原样保存
first_seen: '2026-09-02'   # 首次入库 / 最近核对（每次 enrich 成功刷新）
last_verified: '2026-09-02'
facets:                    # 方向标签，origin=computed 可随时重算
  - {id: topic.systems, origin: computed, confidence: auto, evidence: [keyword:操作系统]}
provenance:                # 每字段出处——工具的立身之本
  title: {origin: crawled, source: https://..., fetched_at: '2026-09-02', confidence: auto}
```

**三条铁律**：
1. `origin: manual` 的字段重跑不覆盖（用户手改受保护）
2. 无效邮箱（`normalize_email` 返回 None）不覆盖有效值
3. 官网名单里消失的人记 issue（missing_in_list），恢复出现自动销账；绝不静默删除

## 5. 爬取框架（crawler/fetch.py + sites/）

### fetch.py 的能力
- **缓存优先**：`cache/http/<sha1>.body + .meta.json`，重跑零新请求；`--refresh` 才回源
- **限速 0.5s + 3 次重试**（递增退避 3s/6s）——重试是后补的，对 flaky 站必备
- **direct 模式**：配置 `direct: true` → requests 绕过环境代理 + Chromium `--no-proxy-server`（注意：playwright 的 `proxy={direct://}` 在本机不可靠，必须用 --no-proxy-server 参数，这是踩过坑的）
- **渲染抓取** `fetch_rendered`：networkidle 超时自动降级、可选滚动加载（懒列表必需）

### 五种已打通的站点范式（新学校先对号入座）
| 范式 | 学校 | 钩子 |
| ---- | ---- | ---- |
| AJAX 返回 HTML 片段（POST+JSON包裹） | 上交计算机学院 | sjtu_cs.py |
| 纯 JSON API | 上交 AI 研究院 | sjtu_ai.py |
| CAS 网站群（含"JS 变量内嵌数据"人才库 var xm="..."） | 计算/自动化/软件/信工所 | cas_lists.py, ucas_*.py |
| WP/博达 CMS（list.htm 翻页 + cNNNaNNN/page.htm 或 /info/N/N.htm） | 清华/中科大/南大/武大/同济/山大/北大/东北/吉大/华东师大 | wp.py, simple_list.py, pku_cs.py |
| JS 渲染名录（requests 拿到空壳） | 哈工大（tbody 网格）、中大（懒加载卡片）、中南 | hit_cs.py, sysu_cs.py, tsites.py |

### 加新学校三步
1. 写 `sites/<school>/<dept>.yaml`（school/dept/dept_name/base_url/hook/list 入口 + person_href 精确正则）
2. 通用钩子不够时写 `<hook>.py`（iter_roster + parse_detail 两个函数；现有 8 个钩子都有样板可抄）
3. `python scripts\crawl.py --school X --dept Y` → `build_site.py`
- 配置可用的开关：`direct: true`（绕代理）、`roster_only: true`（详情页不可抓时只收名单）

## 6. 已接入 22 个院系（数据实测，hook=所用钩子）

| 院系 | hook | 人数 | 职称 | 邮箱 | 博导硕导 | 简介 | facets |
| ---- | ---- | ---- | ---- | ---- | ---- | ---- | ---- |
| sjtu/cs | sjtu_cs | 289 | 289 | 285 | 0 | 249 | 230 |
| sjtu/ai | sjtu_ai | 1 | 1 | 0 | 0 | 1 | 0 |
| tsinghua/cs | tsinghua_cs | 134 | 134 | 134 | 0 | 134 | 123 |
| pku/cs | pku_cs | 119 | 119 | 118 | 2 | 119 | 100 |
| hit/cs | hit_cs | 240 | 0 | 0 | 0 | 0 | 0 |
| ucas/ict | ucas_ict | 283 | 283 | 261 | 213 | 279 | 180 |
| ucas/ia | ucas_ia | 345 | 343 | 342 | 0 | 345 | 274 |
| ucas/iscas | ucas_iscas | 182 | 0 | 179 | 182 | 115 | 141 |
| ucas/iie | ucas_iie | 230 | 0 | 0 | 230 | 0 | 0 |
| ustc/cs | ustc_cs | 72 | 72 | 46 | 0 | 71 | 70 |
| nju/cs | nju_cs | 102 | 102 | 90 | 67 | 92 | 52 |
| whu/cs | simple_list | 109 | 97 | 97 | 58 | 108 | 72 |
| tongji/cs | simple_list | 156 | 42 | 39 | 7 | 156 | 116 |
| sdu/cs | simple_list | 11 | 0 | 4 | 0 | 11 | 10 |
| sysu/cs | sysu_cs | 112 | 110 | 109 | 0 | 0 | 95 |
| neu/cs | wp | 147 | 107 | 70 | 4 | 133 | 113 |
| jlu/cs | simple_list | 36 | 29 | 17 | 0 | 36 | 34 |
| ecnu/cs | wp | 28 | 0 | 28 | 0 | 28 | 27 |
| nwpu/cs | simple_list | 23 | 0 | 0 | 0 | 0 | 0 |
| csu/cs | tsites | 108 | 0 | 0 | 0 | 0 | 0 |
| ruc/ai | simple_list | 31 | 0 | 0 | 0 | 0 | 0 |
| xidian/cs | xidian_cs | 155 | 65 | 0 | 42 | 154 | 120 |
| **合计** | | **2913** | | | **805** | | **1757** |

要点：hit/nwpu/csu/ruc 是纯名单（官网无详情可抓，roster 级）；ucas/iie 是导师名单文章（只有姓名+博导+研究室）；xidian 邮箱是官网 JS 混淆无法还原，如实留空。facets 覆盖 1757/2913（60%），无标签的 1150 条全是 roster 级或官网无方向文字。

## 7. 网站

- **列表页**：搜索、学校→院系级联、职称/导师资格/方向（多选 facet）筛选、全列排序、列显示开关（localStorage `adv_cols_v2`）、分页（每页 50 可调 20/50/100/500）
- **详情页**：字段卡片 + 简介原文 + provenance 出处表（每个字段点回官网原文）+ 新鲜度（first_seen/last_verified/官网 updatedAt）
- 表头表体由同一份 `HEADERS` 数组生成——**这是两次错位事故后的铁律，别改回两套**
- 零构建：Jinja2 模板 `site/templates/` → `build_site.py` 生成

## 8. 工具脚本

| 脚本 | 用途 | 何时跑 |
| ---- | ---- | ---- |
| scripts/crawl.py | 抓取入口（--school --dept [--phase roster/enrich] [--refresh]） | 加新校/更新数据 |
| scripts/build_site.py | 重建静态站 | 每次数据变化后 |
| scripts/audit.py | 覆盖率审计（各院系字段覆盖%） | 每轮迭代后 |
| scripts/preflight.py | 发布前体检（schema/邮箱/站点一致性/issues） | 提交前 |
| scripts/tag_facets.py | 重算方向 facet（13 类关键词规则） | 改规则后 |
| scripts/retest_direct.py | 重测"连不上"学校的直连连通性 | 网络环境变化后 |
| scripts/probe_direct_render.py | 对通了的学校直接看名录渲染结构 | retest 通过后 |
| scripts/verify_site.py | 站点抽查（页面数/关键内容/server） | build 后 |

## 9. 未接入的 28 所学校（全部已定位处理方式，见 README 同类清单）

- **SPA/JS 懒加载，需逆向前端 API**（8 所）：浙大、南科大（cse.sustech.edu.cn/faculty/ 子页卡片 JS 加载）、上科大（sist szdwx 列表 JS）、复旦（登录墙）、北师大（博导/硕导频道已定位，列表 ajax）、西交（gr.xjtu.edu.cn 教师列表 ajax）、川大（faculty.scu.edu.cn 21 页 ajax）、华侨类无
- **WAF 拦截（412/202），需会话/cookie 重试**（4 所）：北邮（**scs.bupt.edu.cn**）、川大（cs.scu.edu.cn）、重大、湖大
- **待定位名录页**（3 所）：东南（dsxx 导师库混合外链）、厦大、大工软件学院（ss.dlut.edu.cn，注意大工计算机学部另有域名）
- **网络层阻断**（13 所，直连+代理都重置）：北邮已确认域名但同样被拦、人大信息学院、华南理工已确认域名 www2.scut.edu.cn 可达……详见 README 网络说明
- **放弃**（1 所）：国防科大（军队院校）

**重要**：此前一批"连不上"的学校其实是**官网域名用错了**（如北邮是 scs 不是 scse、西电是 cs 不是 computer、南科大是 cse 不是 cs、中南是 cse 不是 sca、湖大是 csee、华南理工是 www2、上科大是 sist 无 cs 前缀、人大是 ai.ruc.edu.cn）。**接新校前先 websearch 核实官方域名**，这个教训花了一轮才学到。

## 10. 踩坑记录（每条都是真金白银的时间，接手前必读）

**解析层**
1. 锚点的 `title` 属性和内文**都可能被官网滥用**：哈工大姓名在 title、中南职称在 title——先 dump 卡片原始 HTML 再决定取哪个，别凭感觉
2. 列表数据可能藏在 `<script>` 模板字符串里（中科院 casasypage、上交 AJAX），BeautifulSoup 看不到，要对 raw html 正则提 `<a>` 标签属性
3. 同一人可能有多条历史 URL（计算所 sourcedb 按日期多版本）——按**姓名**去重、保留 URL 日期目录最新的
4. 官网名单链接可能是裸相对路径（`ALL/9.htm`、`9.htm` 两种都见过），翻页正则要兼容
5. tsites（教师主页系统）的列表页 ajax 动态加载，渲染后也只有导航——需逆向其 XHR，别硬解析
6. 官网邮箱混淆格式大全：`bulei # nju.edu.cn`、`yangxubo [AT] sjtu.edu.cn`、`1051065502 AT QQ DOT COM`、`changwen(at)iscas.ac.cn`、标签和值跨行、span 碎片、`▇` 代替 @、分号双邮箱。`email_util.normalize_email` 全覆盖，**新混淆格式出现时在 normalize_email 加分支，并在 crawl 的 _merge 保证无效值不覆盖有效值**
7. pydantic 正则注意 `re.A`：`\w` 默认匹配中文，邮箱校验不放开

**工程层**
8. PowerShell 里写内联 `python -c "..."` 引号必炸——**一律写脚本文件再跑**
9. Windows 控制台中文乱码是显示问题：命令前加 `$env:PYTHONIOENCODING='utf-8'`
10. `Set-Content` 写文件会带 BOM（曾毁过 crawl.py）；`nul` 是 Windows 保留设备名，glob 出来是假象
11. **表头表体必须同一份 HEADERS 数组生成**——两套来源两次错位事故
12. UI 验证的正确姿势：Playwright 打开页面抓 console/pageerror + 读 DOM 断言；`#count` 永远显示全库总数，**过滤效果看 pager 的 `.info`（共 X 人）**
13. git push 大包经代理 408：`git config http.version HTTP/1.1` 已配置，别删
14. 代理在 `127.0.0.1:10808`，"连不上"先区分：域名错（websearch 核实）vs 代理拦截（direct 模式）vs 真阻断（直连也重置）

## 11. 操作手册

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

## 12. 建议的下一步（按价值排序）

1. **tsites/SPA 逆向**：北师大/西交/川大/浙大/南科大/上科大/复旦/东南 —— 每校需逆向 ajax 接口（Playwright 监听 network 或读打包 JS），单校约 1-2 小时；`probe_direct_render.py`/XHR 监听脚本是起点
2. **facet 细化**：13 类关键词规则可继续调；`topic.*` 标签的 evidence 目前只记关键词，可升级为记录命中原文片段
3. **附录 A 延后项**（需求文档有完整设计）：学术数据层 → AI 分析层 → 学生画像+匹配+SOP+信件；对比页；状态写回+看板
4. **verified 人工核对流程**：从未启用；最小方案=每校抽 10 人人工核对 provenance 并置 verified
5. 官网改版是常态：`crawl --refresh` + changes 日志会告诉你哪里变了；改版导致解析失效会进 issues 队列

## 13. 给下一个 agent 的三句话

1. **先跑 `preflight.py` 和 `audit.py`，再动任何代码**——它们绿了才说明你理解的数据状态和真实状态一致
2. **接新校先 websearch 官方域名，再 dump 原始 HTML 找数据真实位置**（锚点属性/内文/script 变量/ajax 三选一），九连败的教训全在 §10
3. **所有 UI 改动用 Playwright 打开页面验证 console 无错 + DOM 断言**，`#count` 是全库总数不是筛选数
