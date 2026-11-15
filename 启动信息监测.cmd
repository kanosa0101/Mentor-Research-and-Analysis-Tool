@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 每 6 小时检查已配置的官方栏目。请保持此窗口运行；Ctrl+C 停止。
echo 电脑关闭、休眠或本程序退出期间不会更新。结果在“保研机会”页查看。
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 scripts\monitor_opportunities.py --watch
) else (
  python -X utf8 scripts\monitor_opportunities.py --watch
)
if errorlevel 1 echo 监测未正常完成，请检查上方错误。首次使用需安装 requirements.txt 中的依赖。
pause
