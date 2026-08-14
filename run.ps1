# 实验室信息管理系统 LIMS 启动脚本（PowerShell）
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "[提示] 首次运行，正在创建虚拟环境并安装依赖..."
    python -m venv .venv
    & .venv\Scripts\python.exe -m pip install --upgrade pip
    & .venv\Scripts\python.exe -m pip install -r requirements.txt
}

Write-Host ""
Write-Host "实验室信息管理系统 LIMS 正在启动..."
Write-Host "请在浏览器打开：http://127.0.0.1:8000"
Write-Host "默认账号：admin / admin123（实验员 fyy / 123456）"
Write-Host "按 Ctrl+C 停止服务。"
Write-Host ""
& .venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
