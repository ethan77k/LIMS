"""初始化数据库：建表 + 种子数据（默认账号与计费设备）。

设备计价标准来源于公司内部《可靠性测试报价表-20260721.xlsx》
（计费标准 + 计费明细 两个 Sheet 合并）。
"""
from sqlalchemy import text

from .database import Base, SessionLocal, engine
from .models import EntrustOrder, Equipment, Notification, User
from .security import hash_password


def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _seed_users(db)
        _seed_equipment(db)
        _migrate_notifications(db)
        _migrate_criteria(db)
        _migrate_case_count_unit(db)
        _migrate_order_case_id(db)
        _migrate_entruster_user_id(db)
        db.commit()
    finally:
        db.close()


def _migrate_notifications(db):
    """把历史「按角色广播」通知（共享 is_read）转换为按用户各一条（独立已读）。幂等。"""
    broadcasts = (
        db.query(Notification)
        .filter(Notification.role != "", Notification.user_id.is_(None))
        .all()
    )
    for n in broadcasts:
        recipients = db.query(User).filter(User.role == n.role, User.is_active.is_(True)).all()
        for u in recipients:
            db.add(
                Notification(
                    user_id=u.id, role="", title=n.title, content=n.content,
                    order_id=n.order_id, is_read=n.is_read,
                )
            )
        db.delete(n)


def _migrate_entruster_user_id(db):
    """为 entrust_orders 增加 entruster_user_id 列并按委托人姓名回填（幂等）。"""
    cols = [row[1] for row in db.execute(text("PRAGMA table_info(entrust_orders)"))]
    if "entruster_user_id" not in cols:
        db.execute(text("ALTER TABLE entrust_orders ADD COLUMN entruster_user_id INTEGER REFERENCES users(id)"))
    for order in db.query(EntrustOrder).filter(EntrustOrder.entruster_user_id.is_(None)).all():
        if order.entruster:
            u = db.query(User).filter(User.name == order.entruster, User.role == "entruster").first()
            if u is not None:
                order.entruster_user_id = u.id


def _migrate_criteria(db):
    """为 entrust_orders 增加 criteria（判定标准）列（幂等）。"""
    cols = [row[1] for row in db.execute(text("PRAGMA table_info(entrust_orders)"))]
    if "criteria" not in cols:
        db.execute(text("ALTER TABLE entrust_orders ADD COLUMN criteria TEXT DEFAULT ''"))


def _migrate_case_count_unit(db):
    """为 test_cases 增加 count（数量）/ unit（单位）列（幂等）。"""
    cols = [row[1] for row in db.execute(text("PRAGMA table_info(test_cases)"))]
    if "count" not in cols:
        db.execute(text("ALTER TABLE test_cases ADD COLUMN count INTEGER DEFAULT 1"))
    if "unit" not in cols:
        db.execute(text("ALTER TABLE test_cases ADD COLUMN unit VARCHAR(16) DEFAULT '只'"))


def _migrate_order_case_id(db):
    """为 entrust_orders 增加 case_id 列（记录来源用例，审核时可带出图片）。幂等。"""
    cols = [row[1] for row in db.execute(text("PRAGMA table_info(entrust_orders)"))]
    if "case_id" not in cols:
        db.execute(text("ALTER TABLE entrust_orders ADD COLUMN case_id INTEGER REFERENCES test_cases(id)"))


def _seed_users(db):
    if db.query(User).count() > 0:
        return
    users = [
        User(username="Dhd2026", password_hash=hash_password("1234"),
             name="管理员", role="admin", department="检测中心", email=""),
        User(username="YH", password_hash=hash_password("1234"),
             name="YH", role="experimenter", department="检测中心", email=""),
        User(username="HW", password_hash=hash_password("1234"),
             name="HW", role="experimenter", department="检测中心", email=""),
        User(username="Dhd", password_hash=hash_password("123"),
             name="Dhd", role="entruster", department="", email=""),
    ]
    db.add_all(users)


def _seed_equipment(db):
    if db.query(Equipment).count() > 0:
        return
    # 依据公司内部计费标准（可靠性测试报价表-20260721）
    items = [
        Equipment(name="快速温变试验箱", exp_type="环境类测试", open_fee=500.0, power_fee=43.0,
                  depreciation_fee=6.63, consumable_fee=0.0, unit_price=206900.0, power_kw=50,
                  sort_order=1, remark="样品大小: 0.8m³‌以内"),
        Equipment(name="UV紫外线老化试验箱", exp_type="环境类测试", open_fee=300.0, power_fee=25.8,
                  depreciation_fee=0.9, consumable_fee=5.0, unit_price=28000.0, power_kw=30,
                  sort_order=2, remark="样品大小: 0.3m³‌以内"),
        Equipment(name="冷热冲击箱", exp_type="环境类测试", open_fee=500.0, power_fee=51.6,
                  depreciation_fee=8.13, consumable_fee=0.0, unit_price=253800.0, power_kw=60,
                  sort_order=3, remark="样品大小: 0.3m³‌以内，超出需分批进行"),
        Equipment(name="恒温恒湿箱", exp_type="环境类测试", open_fee=300.0, power_fee=13.76,
                  depreciation_fee=3.67, consumable_fee=0.0, unit_price=114500.0, power_kw=16,
                  sort_order=4, remark="样品大小: 0.8m³‌以内"),
        Equipment(name="立式高温烤箱", exp_type="环境类测试", open_fee=200.0, power_fee=1.72,
                  depreciation_fee=0.12, consumable_fee=0.0, unit_price=3894.0, power_kw=2,
                  sort_order=5, remark="样品大小: 0.8m³‌以内"),
        Equipment(name="盐雾试验机", exp_type="环境类测试", open_fee=200.0, power_fee=4.3,
                  depreciation_fee=0.13, consumable_fee=5.0, unit_price=4200.0, power_kw=5,
                  sort_order=6, remark="样品大小: 0.3m³‌以内"),
        Equipment(name="全自动纸箱抗压试验机", exp_type="运输类测试", open_fee=500.0, power_fee=0.43,
                  depreciation_fee=0.74, consumable_fee=0.0, unit_price=23000.0, power_kw=0.5,
                  sort_order=7, remark="样品大小: 1.5m³‌以内"),
        Equipment(name="跌落试验机", exp_type="运输类测试", open_fee=500.0, power_fee=0.43,
                  depreciation_fee=0.61, consumable_fee=0.0, unit_price=19000.0, power_kw=0.5,
                  sort_order=8, remark="样品大小: 0.5m³‌以内"),
        Equipment(name="电动振动仪", exp_type="运输类测试", open_fee=1000.0, power_fee=92.88,
                  depreciation_fee=6.28, consumable_fee=0.0, unit_price=196000.0, power_kw=108,
                  sort_order=9, remark="1次只做“1箱/1只/1批”，超出分次完成（台体尺寸800*800mm）"),
        Equipment(name="线材弯折试验机", exp_type="机械类测试", open_fee=400.0, power_fee=0.43,
                  depreciation_fee=0.22, consumable_fee=0.0, unit_price=7000.0, power_kw=0.5,
                  sort_order=10, remark="1次只做“1箱/1只/1批”，超出分次完成（台体尺寸500*800mm）"),
        Equipment(name="全自动插拔力试验机", exp_type="机械类测试", open_fee=400.0, power_fee=0.43,
                  depreciation_fee=0.9, consumable_fee=0.0, unit_price=28000.0, power_kw=0.5,
                  sort_order=11, remark="测试次数：每1个/箱样品一次。"),
        Equipment(name="微电脑拉力试验机", exp_type="机械类测试", open_fee=400.0, power_fee=0.43,
                  depreciation_fee=0.61, consumable_fee=1.0, unit_price=19000.0, power_kw=0.5,
                  sort_order=12, remark="测试次数：每1个/箱样品一次。"),
        Equipment(name="插拔寿命试验机", exp_type="机械类测试", open_fee=400.0, power_fee=0.43,
                  depreciation_fee=0.96, consumable_fee=0.0, unit_price=30000.0, power_kw=0.5,
                  sort_order=13, remark="测试次数：每6pcs一次\n（不足3pcs的算一次）"),
        Equipment(name="滚筒跌落试验机", exp_type="机械类测试", open_fee=300.0, power_fee=0.43,
                  depreciation_fee=0.38, consumable_fee=0.0, unit_price=12000.0, power_kw=0.5,
                  sort_order=14, remark="不需要用电，但要有0.7Mpa以上的气源"),
        Equipment(name="落球冲击试验机", exp_type="机械类测试", open_fee=300.0, power_fee=0.43,
                  depreciation_fee=0.07, consumable_fee=0.0, unit_price=2124.0, power_kw=0.5,
                  sort_order=15, remark="1次只做“1箱/1只/1批”，超出分次完成（台体尺寸800*800mm）"),
        Equipment(name="按键寿命试验机", exp_type="机械类测试", open_fee=400.0, power_fee=0.43,
                  depreciation_fee=0.36, consumable_fee=0.0, unit_price=11328.0, power_kw=0.5,
                  sort_order=16, remark="测试次数：每3pcs一次\n（不足3pcs的算一次）"),
        Equipment(name="头戴耳机支臂滑动试验机", exp_type="机械类测试", open_fee=400.0, power_fee=0.43,
                  depreciation_fee=0.4, consumable_fee=0.0, unit_price=12500.0, power_kw=0.5,
                  sort_order=17, remark="测试次数：每1个/箱样品一次。"),
        Equipment(name="头戴耳机夹持力试验机", exp_type="机械类测试", open_fee=400.0, power_fee=0.43,
                  depreciation_fee=0.18, consumable_fee=0.0, unit_price=5500.0, power_kw=0.5,
                  sort_order=18, remark="测试次数：每1个/箱样品一次。"),
        Equipment(name="头戴耳机扩张寿命试验机", exp_type="机械类测试", open_fee=400.0, power_fee=0.43,
                  depreciation_fee=0.18, consumable_fee=0.0, unit_price=5500.0, power_kw=0.5,
                  sort_order=19, remark="测试次数：每1个/箱样品一次。"),
        Equipment(name="耳机扭转寿命试验机", exp_type="机械类测试", open_fee=400.0, power_fee=0.43,
                  depreciation_fee=0.38, consumable_fee=0.0, unit_price=12000.0, power_kw=0.5,
                  sort_order=20, remark="测试次数：每1个/箱样品一次。"),
        Equipment(name="头戴耳机支臂弯折试验机", exp_type="机械类测试", open_fee=400.0, power_fee=0.43,
                  depreciation_fee=0.22, consumable_fee=0.0, unit_price=6800.0, power_kw=0.5,
                  sort_order=21, remark="测试次数：每1个/箱样品一次。"),
        Equipment(name="推拉力计", exp_type="机械类测试", open_fee=400.0, power_fee=0.43,
                  depreciation_fee=0.02, consumable_fee=0.0, unit_price=585.0, power_kw=0.5,
                  sort_order=22, remark="明细表补充设备（计费标准表未列）"),
        Equipment(name="耐磨试验机", exp_type="表面类测试", open_fee=300.0, power_fee=0.43,
                  depreciation_fee=0.21, consumable_fee=5.0, unit_price=6700.0, power_kw=0.5,
                  sort_order=23, remark="测试次数：每10pcs一次\n（不足3pcs的算一次）"),
        Equipment(name="纸带耐磨试验机", exp_type="表面类测试", open_fee=300.0, power_fee=0.43,
                  depreciation_fee=0.18, consumable_fee=3.0, unit_price=5500.0, power_kw=0.5,
                  sort_order=24, remark="测试次数：每10pcs一次\n（不足3pcs的算一次）"),
        Equipment(name="强冲水淋雨试验装置IPX5/6", exp_type="防水测试", open_fee=300.0, power_fee=0.43,
                  depreciation_fee=0.9, consumable_fee=0.0, unit_price=28000.0, power_kw=0.5,
                  sort_order=25, remark="测试次数：每3pcs一次\n（不足3pcs的算一次）"),
        Equipment(name="淋雨试验机IPX3/4", exp_type="防水测试", open_fee=300.0, power_fee=0.86,
                  depreciation_fee=0.58, consumable_fee=0.0, unit_price=18000.0, power_kw=1,
                  sort_order=26, remark="测试次数：每3pcs一次\n（不足3pcs的算一次）"),
        Equipment(name="潜水试验装置IPX7/8", exp_type="防水测试", open_fee=300.0, power_fee=0.43,
                  depreciation_fee=0.79, consumable_fee=0.0, unit_price=24735.0, power_kw=0.5,
                  sort_order=27, remark="测试次数：每3pcs一次\n（不足3pcs的算一次）"),
        Equipment(name="耐压测试仪", exp_type="电性能类", open_fee=400.0, power_fee=0.43,
                  depreciation_fee=1.9, consumable_fee=0.0, unit_price=59325.0, power_kw=0.5,
                  sort_order=28, remark="测试次数：每1个/箱样品一次。"),
        Equipment(name="数据采集器", exp_type="电性能类", open_fee=200.0, power_fee=0.43,
                  depreciation_fee=0.64, consumable_fee=0.0, unit_price=20000.0, power_kw=0.5,
                  sort_order=29, remark="测试次数：每1个/箱样品一次。"),
        Equipment(name="静电放电模拟器", exp_type="电性能类", open_fee=400.0, power_fee=0.43,
                  depreciation_fee=3.78, consumable_fee=0.0, unit_price=118000.0, power_kw=0.5,
                  sort_order=30, remark="测试次数：每1个/箱样品一次。"),
        Equipment(name="电池分容仪", exp_type="电性能类", open_fee=800.0, power_fee=0.43,
                  depreciation_fee=2.18, consumable_fee=0.0, unit_price=68000.0, power_kw=0.5,
                  sort_order=31, remark="测试次数：每1个/箱样品一次。"),
        Equipment(name="其它试验（非标/自定义试验）", exp_type="其它试验", open_fee=200.0, power_fee=0.0,
                  depreciation_fee=0.0, consumable_fee=0.0, unit_price=0.0, power_kw=0.0,
                  sort_order=32, remark="除1~34项外：如非标拉力试验、非标吊重试验、客户自定义试验等，按单个样品收费"),
        Equipment(name="外发测试（如危险鉴定等）", exp_type="其它试验", open_fee=0.0, power_fee=0.0,
                  depreciation_fee=0.0, consumable_fee=0.0, unit_price=0.0, power_kw=0.0,
                  sort_order=33, remark="按外部实验室实际价格收取，发票报帐后费用划分到委托的BU及机种当中"),
    ]
    db.add_all(items)
