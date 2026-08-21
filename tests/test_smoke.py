"""端到端冒烟测试：健康检查 + 完整委托实验闭环 + 关键 bug 回归。"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _login(username="Dhd2026", password="1234"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_full_flow():
    admin = _login()
    h = _auth(admin["access_token"])

    # 1. 提交委托
    r = client.post("/api/orders", json={
        "entrust_org": "测试单位", "entruster": "张三", "sample_name": "测试样品",
        "test_item": "环境测试", "phone": "13800000000", "email": "a@b.com",
        "sample_count": 1,
    })
    assert r.status_code == 200, r.text
    order_id = r.json()["id"]
    assert r.json()["order_no"]

    # 2. 审核通过（B4：reviewer_id 指向不存在用户应 400）
    r = client.post(f"/api/review/{order_id}", json={"approve": True, "reviewer_id": 999999, "costs": []}, headers=h)
    assert r.status_code == 400
    r = client.post(f"/api/review/{order_id}", json={"approve": True, "costs": []}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["experiment_no"]

    # 3. 取样品与设备
    detail = client.get(f"/api/orders/{order_id}", headers=h).json()
    assert len(detail["samples"]) == 1
    sample_id = detail["samples"][0]["id"]
    equipment = client.get("/api/equipment", headers=h).json()
    assert equipment
    equipment_id = equipment[0]["id"]

    # 4. 排期
    r = client.post("/api/schedules", json={
        "sample_id": sample_id, "equipment_id": equipment_id,
        "experiment_hours": 1.0, "transition_hours": 0.0,
    }, headers=h)
    assert r.status_code == 200, r.text
    schedule_id = r.json()["id"]
    assert r.json()["status"] == "已排期"

    # 5. 开始实验
    r = client.post(f"/api/experiment/schedule/{schedule_id}/start", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "实验中"

    # 6. 结束实验（B3：样品状态 实验中 → 已完成）
    r = client.post(f"/api/experiment/schedule/{schedule_id}/end", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "已完成"
    sample = client.get(f"/api/samples/{sample_id}", headers=h).json()
    assert sample["status"] == "已完成"

    # 7. 完成委托（B1：已有排期可完成）
    r = client.post(f"/api/experiment/order/{order_id}/finish", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "已完成"

    # 8. 签发报告
    r = client.post(f"/api/reports/{order_id}/issue", json={"report_type": "检测报告", "version": "常规"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["report_no"].startswith("BG")

    # 报告可渲染（报告接口 200）
    r = client.get(f"/api/reports/test/{order_id}", headers=h)
    assert r.status_code == 200
    assert "检测报告" in r.text


def test_delete_schedule_rollback():
    """B2：删除排期后样品回退已接收、委托单回退已审核。"""
    admin = _login()
    h = _auth(admin["access_token"])
    o = client.post("/api/orders", json={
        "entrust_org": "单位", "entruster": "李四", "sample_name": "样品",
        "test_item": "测试", "phone": "13800000001", "email": "c@d.com", "sample_count": 1,
    }).json()
    order_id = o["id"]
    client.post(f"/api/review/{order_id}", json={"approve": True, "costs": []}, headers=h)
    detail = client.get(f"/api/orders/{order_id}", headers=h).json()
    sample_id = detail["samples"][0]["id"]
    eq = client.get("/api/equipment", headers=h).json()[0]["id"]

    # 先接收样品（待接收 → 已接收），再排期（已接收 → 已排期）
    client.post(f"/api/samples/{sample_id}/receive", json={"condition": "样品正常"}, headers=h)
    sch = client.post("/api/schedules", json={"sample_id": sample_id, "equipment_id": eq}, headers=h).json()
    sch_id = sch["id"]

    r = client.delete(f"/api/schedules/{sch_id}", headers=h)
    assert r.status_code == 200, r.text
    sample = client.get(f"/api/samples/{sample_id}", headers=h).json()
    assert sample["status"] == "已接收"
    order = client.get(f"/api/orders/{order_id}", headers=h).json()
    assert order["status"] == "已审核"


def test_xss_escaped_in_report():
    """A3：报告渲染对用户输入的 HTML 特殊字符转义。"""
    admin = _login()
    h = _auth(admin["access_token"])
    o = client.post("/api/orders", json={
        "entrust_org": "单位", "entruster": "王五", "sample_name": "<b>危险</b><script>alert(1)</script>",
        "test_item": "测试", "phone": "13800000002", "email": "e@f.com", "sample_count": 1,
    }).json()
    order_id = o["id"]
    client.post(f"/api/review/{order_id}", json={"approve": True, "costs": []}, headers=h)
    r = client.get(f"/api/reports/entrust/{order_id}", headers=h)
    assert r.status_code == 200
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text
