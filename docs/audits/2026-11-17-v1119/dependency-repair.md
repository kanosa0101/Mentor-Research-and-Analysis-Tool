# 活动取证部署依赖修复

2026-11-17 02:53:05 至 02:53:20 UTC 的真实 `mentor-review-pipeline.service` 报告 `automatic: ModuleNotFoundError`。使用生产 Python 环境及公开队列、配置的隔离副本运行同一入口，完整堆栈定位到 `crawler/opportunity_attachments.py` 的 `parse_xlsx` 加载 `openpyxl`。项目根 `requirements.txt` 已声明该依赖，生产部署使用的 `deploy/requirements.txt` 缺少它。

部署清单加入 `openpyxl>=3.1,<4`，也补入生产已安装的 `pdfplumber`、`olefile`、`Pillow` 和 `zxing-cpp`。版本范围与项目根依赖一致，供新部署和重建环境时使用。

复验只在临时依赖目录安装 `openpyxl 3.1.5`。真实校方来源和生产公开队列副本通过同一自动入口运行，报告 67 条跳过、20 条需人工、0 条发布、0 条续核。检查器禁止模型调用，调用数为 0。内容入库与依赖启动相关测试 17 项通过、1 项跳过。

复验定位到中国科学院软件研究所公告 `be26850bf5aaae76be0a`，正文 SHA-256 为 `af7ab1ec85ff0e2994a5e6f792b8b601c07507f44cdc5ec00a86e34faffbe121`。它链接的官方文件 `P020261028618405519532.xlsx` 含外部链接，原取证门禁按 `evidence_error / incomplete_evidence` 记录“XLSX含外部链接，需核对关联证据”。该记录仍需核对，隔离运行没有产生公开活动增量。[中国科学院软件研究所官方公告](https://is.cas.cn/yjsjy/zsxx/202610/t20261028_8299649.html)
