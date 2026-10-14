# 学校、院系与招生政策 0.4 实施计划

**Goal:** 用户从学校院系查到适用年度/学位/渠道的学校通用与院系专业规则，看到来源、信息年龄及缺失，再进入导师发现和申请管理。

**Architecture:** 继续静态站与本机私人API；新增独立公开 `data/admissions.yaml`（官方来源登记与人工摘要）及 `data/admissions_checks.json`（来源检查状态）。不迁移私人schema，不自动把政策变为个人符合/导师有名额。共用0.3 UI，新增学校政策入口及上下文链接。

**Tech Stack:** Python、YAML、requests/现有fetch、Jinja2、原生JS、unittest、Node、Playwright。

## 已决定的设计与边界

用户已授权连续推进，包括学校院系政策；采用人工核验摘要+原文变化检查这一最小方案。纯外链不能展示要求/缺失，全库自动解析PDF/AI判定当前风险与维护成本过高。先做清华学校硕士统考/推免、计算机系推免与电子信息统考科目四条上下文规则，覆盖1校1院系；学校目录继续覆盖36校42院系，不把两种覆盖率混同。

政策固定年度/学位/渠道/学校/院系/专业范围。字段按报名资格、材料、考核、时间、学费、奖助、名额、联系/报名入口分类；没有整理的字段显式显示“未整理，需查原文”，原文另行通知也不能标成已知截止日期。学校规则与院系规则并列，不无条件覆盖或合并。原文定位、短引文、摘要、发布时间、人工核对时间与指纹分别保留。来源检查关注正文和附件链接；抓取成功不等于新版本已核验。

## 执行与验收

- [x] 1. 新 `tests/test_admissions.py`：错误字段/范围/出处拒绝、原文指纹稳定/变化、缓存不推进日期、失败保留旧成功状态、检查变化不改人工摘要。运行 `python -m unittest discover -s tests -p test_admissions.py`，先红再绿。
- [x] 2. `crawler/admissions_util.py`：公开数据校验与来源正文指纹；`scripts/check_admissions.py`：限登记官方URL检查，失败非零，状态原子写入，保留旧成功观测。`data/admissions.yaml`：3份原文及2个附件落地页，4条人工规则；不写真实私人记录。
- [x] 3. `site/admissions-core.js` + `tests/admissions_rules.cjs`：学校通用规则在院系查询仍可见，渠道/年份不跨用，校级与专业适用范围保留，过期/失败/变化状态区分，不把未知当不符合。`node tests/admissions_rules.cjs` 先红再绿。
- [x] 4. `site/templates/admissions.html.j2` / `site/admissions.js`：全量学校院系目录、申请目标筛选、规则层级、逐字段证据/缺失、覆盖与年龄、官方入口。`scripts/build_site.py` 生成公开 admissions-data.js；仅公开材料。导航增“学校与政策”，详情/发现/通知带上下文；项目新建预填可审阅的政策参考备注，不自动保存。
- [x] 5. `scripts/admissions_ui_check.py` 使用临时私人存储：年度/渠道/院系筛选、未知院系不借用规则、政策→导师范围/申请项目预填、显式提交、转义、390px布局/静态模式。旧3组+条件发现浏览器回归；全量重建与preflight0。
- [x] 6. 记录同类产品字段/来源/新鲜度/覆盖边界，交付证据；独立代码复核并修复；5729原data SHA256不变，仅新增2份公开政策文件；本地提交，不推送。

## 主要命令

```powershell
python scripts/check_admissions.py --refresh
python scripts/build_site.py
python -m unittest discover -s tests
node tests/admissions_rules.cjs
node tests/discovery_rules.cjs
python scripts/admissions_ui_check.py
python scripts/discovery_ui_check.py
python scripts/ui_check.py
python scripts/application_ui_check.py
python scripts/contact_ui_check.py
python scripts/preflight.py
```

调研来源：研招网专业目录/信息公开说明、Mastersportal具体项目、Studyportals2025数据维护说明、FindAPhD项目列表，以及清华2027学校简章与计算机系官方通知。具体URL与观察将在产品调研记录中保留；没有检查第三方全数据库，不能确认其全量新鲜度或完整率。
