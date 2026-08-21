"""LIMS 主入口。启动时自动建表 + 种子数据，并托管前端静态文件。"""
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import STATIC_DIR
from .routers import (
    audit,
    auth,
    cases,
    customers,
    dashboard,
    equipment,
    experiment,
    export,
    notifications,
    orders,
    reports,
    review,
    samples,
    schedule,
    statistics,
)
from .seed import init_db

app = FastAPI(title="实验室信息管理系统 LIMS", version="1.0.0")

# 启动时初始化数据库
init_db()

# 注册 API 路由
app.include_router(auth.router)
app.include_router(orders.router)
app.include_router(review.router)
app.include_router(samples.router)
app.include_router(schedule.router)
app.include_router(experiment.router)
app.include_router(reports.router)
app.include_router(equipment.router)
app.include_router(dashboard.router)
app.include_router(statistics.router)
app.include_router(audit.router)
app.include_router(notifications.router)
app.include_router(customers.router)
app.include_router(cases.router)
app.include_router(export.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# 托管前端静态文件（放在最后，避免拦截 /api）
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
