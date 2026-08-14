@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [提示] 首次运行，正在创建虚拟环境并安装依赖...
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)
echo.
echo 实验室信息管理系统 LIMS 正在启动...
echo 请在浏览器打开：http://127.0.0.1:8000
echo 默认账号：admin / admin123（实验员 fyy / 123456）
echo 按 Ctrl+C 停止服务。
echo.
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
