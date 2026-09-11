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
    inspections,
    notifications,
    onlyoffice_router,
    orders,
    qrcode,
    reports,
    review,
    samples,
    schedule,
    statistics,
    templates,
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
app.include_router(qrcode.router)
app.include_router(schedule.router)
app.include_router(experiment.router)
app.include_router(inspections.router)
app.include_router(reports.router)
app.include_router(onlyoffice_router.router)
app.include_router(equipment.router)
app.include_router(dashboard.router)
app.include_router(statistics.router)
app.include_router(audit.router)
app.include_router(notifications.router)
app.include_router(customers.router)
app.include_router(cases.router)
app.include_router(export.router)
app.include_router(templates.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# 前端静态资源禁用缓存：SPA 手工更新频繁，浏览器缓存旧 index.html/app.js 会导致看不到更新
@app.middleware("http")
async def no_cache_frontend(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if not path.startswith("/api/") and not path.startswith("/uploads/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# 托管前端静态文件（放在最后，避免拦截 /api）
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
