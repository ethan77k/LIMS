"""初始化数据库：建表 + 种子数据（默认账号与计费设备）。

设备计价标准来源于公司内部《可靠性测试报价表-20260721.xlsx》
（计费标准 + 计费明细 两个 Sheet 合并）。
"""
import sqlite3

from sqlalchemy import text

from .database import Base, SessionLocal, engine
from .models import EntrustOrder, Equipment, Notification, User
from .security import hash_password


def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate_samples_rebuild()  # 需先于任何 Session 事务执行（samples 表重建）
    _migrate_schedules_equipment_nullable()  # schedules 表重建：equipment_id 改可空（排期阶段不再选设备）
    db = SessionLocal()
    try:
        _seed_users(db)
        _seed_equipment(db)
        _migrate_notifications(db)
        _migrate_criteria(db)
        _migrate_case_count_unit(db)
        _migrate_order_case_id(db)
        _migrate_entruster_user_id(db)
        _migrate_cost_fields(db)
        _migrate_sample_batches_entruster(db)
        _migrate_sample_batches_sample_stage(db)
        _migrate_schedules_result(db)
        _migrate_sample_no_3digit(db)
        _migrate_schedules_experimenter(db)
        _migrate_report_content(db)
        _migrate_report_docx(db)
        _migrate_schedules_sample_prev_status(db)
        db.commit()
    finally:
        db.close()


def _migrate_samples_rebuild():
    """samples 表重建：order_id 改可空 + 新增 sn / batch_id 列（幂等）。

    SQLite 的 ALTER TABLE 无法修改列约束，故整表重建；用 raw sqlite3
    连接关闭外键约束后执行，重建完成后恢复。仅在 samples 尚无 sn 列时执行一次。
    """
    if engine.url.get_backend_name() != "sqlite":
        return
    path = engine.url.database
    conn = sqlite3.connect(path)
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(samples)").fetchall()]
        if "sn" in cols:
            return
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")
        try:
            conn.execute(
                "CREATE TABLE samples_new ("
                "id INTEGER NOT NULL PRIMARY KEY,"
                "sample_no VARCHAR(40) NOT NULL,"
                "order_id INTEGER,"
                "status VARCHAR(16) NOT NULL,"
                "condition VARCHAR(64) NOT NULL,"
                "result VARCHAR(8) NOT NULL,"
                "remark TEXT NOT NULL,"
                "sn VARCHAR(64),"
                "batch_id INTEGER,"
                "created_at DATETIME NOT NULL"
                ")"
            )
            conn.execute(
                "INSERT INTO samples_new (id, sample_no, order_id, status, condition, result, remark, created_at) "
                "SELECT id, sample_no, order_id, status, condition, result, remark, created_at FROM samples"
            )
            conn.execute("DROP TABLE samples")
            conn.execute("ALTER TABLE samples_new RENAME TO samples")
            conn.execute("CREATE INDEX ix_samples_id ON samples (id)")
            conn.execute("CREATE INDEX ix_samples_order_id ON samples (order_id)")
            conn.execute("CREATE INDEX ix_samples_status ON samples (status)")
            conn.execute("CREATE UNIQUE INDEX ix_samples_sample_no ON samples (sample_no)")
            conn.execute("CREATE INDEX ix_samples_batch_id ON samples (batch_id)")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.close()


def _migrate_schedules_equipment_nullable():
    """schedules 表重建：equipment_id 改可空（排期阶段不再选设备，设备留到「实验开始」时填）。幂等。

    SQLite 的 ALTER TABLE 无法修改列约束，故整表重建（与 samples 重建同理）。
    仅在 equipment_id 仍为 NOT NULL 时执行一次。
    """
    if engine.url.get_backend_name() != "sqlite":
        return
    path = engine.url.database
    conn = sqlite3.connect(path)
    try:
        cols = {row[1]: row for row in conn.execute("PRAGMA table_info(schedules)").fetchall()}
        if "equipment_id" not in cols or not cols["equipment_id"][3]:
            return  # equipment_id 已可空，无需迁移
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")
        try:
            conn.execute(
                "CREATE TABLE schedules_new ("
                "id INTEGER NOT NULL PRIMARY KEY,"
                "order_id INTEGER NOT NULL REFERENCES entrust_orders(id),"
                "sample_id INTEGER NOT NULL REFERENCES samples(id),"
                "equipment_id INTEGER REFERENCES equipments(id),"
                "experiment_hours FLOAT NOT NULL,"
                "transition_hours FLOAT NOT NULL,"
                "total_hours FLOAT NOT NULL,"
                "plan_start DATETIME,"
                "plan_end DATETIME,"
                "actual_start DATETIME,"
                "actual_end DATETIME,"
                "status VARCHAR(16) NOT NULL,"
                "created_at DATETIME NOT NULL,"
                "result VARCHAR(8) DEFAULT '',"
                "experimenter_id INTEGER REFERENCES users(id),"
                "is_draft BOOLEAN DEFAULT 0"
                ")"
            )
            conn.execute(
                "INSERT INTO schedules_new (id, order_id, sample_id, equipment_id, experiment_hours, transition_hours, total_hours, plan_start, plan_end, actual_start, actual_end, status, created_at, result, experimenter_id, is_draft) "
                "SELECT id, order_id, sample_id, equipment_id, experiment_hours, transition_hours, total_hours, plan_start, plan_end, actual_start, actual_end, status, created_at, result, experimenter_id, is_draft FROM schedules"
            )
            conn.execute("DROP TABLE schedules")
            conn.execute("ALTER TABLE schedules_new RENAME TO schedules")
            conn.execute("CREATE INDEX ix_schedules_id ON schedules (id)")
            conn.execute("CREATE INDEX ix_schedules_order_id ON schedules (order_id)")
            conn.execute("CREATE INDEX ix_schedules_sample_id ON schedules (sample_id)")
            conn.execute("CREATE INDEX ix_schedules_equipment_id ON schedules (equipment_id)")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.close()


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


def _migrate_cost_fields(db):
    """为 cost_items 增加 test_time / test_count / service_fee 列（幂等）。"""
    cols = [row[1] for row in db.execute(text("PRAGMA table_info(cost_items)"))]
    if "test_time" not in cols:
        db.execute(text("ALTER TABLE cost_items ADD COLUMN test_time FLOAT DEFAULT 0"))
    if "test_count" not in cols:
        db.execute(text("ALTER TABLE cost_items ADD COLUMN test_count INTEGER DEFAULT 1"))
    if "service_fee" not in cols:
        db.execute(text("ALTER TABLE cost_items ADD COLUMN service_fee FLOAT DEFAULT 0"))


def _migrate_sample_batches_entruster(db):
    """为 sample_batches 增加 entruster（委托人）列（幂等）。"""
    cols = [row[1] for row in db.execute(text("PRAGMA table_info(sample_batches)"))]
    if "entruster" not in cols:
        db.execute(text("ALTER TABLE sample_batches ADD COLUMN entruster VARCHAR(64) DEFAULT ''"))


def _migrate_sample_batches_sample_stage(db):
    """为 sample_batches 增加 sample_stage（样品阶段）列（幂等）。"""
    cols = [row[1] for row in db.execute(text("PRAGMA table_info(sample_batches)"))]
    if "sample_stage" not in cols:
        db.execute(text("ALTER TABLE sample_batches ADD COLUMN sample_stage VARCHAR(32) DEFAULT ''"))


def _migrate_schedules_result(db):
    """为 schedules 增加 result（测试位结果 OK/NG）列（幂等）。"""
    cols = [row[1] for row in db.execute(text("PRAGMA table_info(schedules)"))]
    if "result" not in cols:
        db.execute(text("ALTER TABLE schedules ADD COLUMN result VARCHAR(8) DEFAULT ''"))


def _migrate_sample_no_3digit(db):
    """样品编号尾号由两位扩展为三位（-01 → -001），幂等。"""
    db.execute(text(
        "UPDATE samples SET sample_no = substr(sample_no, 1, length(sample_no) - 2) || '0' || substr(sample_no, -2) "
        "WHERE substr(sample_no, -3, 1) = '-' AND substr(sample_no, -2) GLOB '[0-9][0-9]'"
    ))
    db.commit()


def _migrate_schedules_experimenter(db):
    """为 schedules 增加 experimenter_id（实验员）列，并把存量排期回填为委托单审核时指定的实验员（幂等）。"""
    cols = [row[1] for row in db.execute(text("PRAGMA table_info(schedules)"))]
    if "experimenter_id" not in cols:
        db.execute(text("ALTER TABLE schedules ADD COLUMN experimenter_id INTEGER"))
        db.execute(text(
            "UPDATE schedules SET experimenter_id = "
            "(SELECT reviewer_id FROM entrust_orders WHERE entrust_orders.id = schedules.order_id)"
        ))
        db.commit()


def _migrate_schedules_sample_prev_status(db):
    """为 schedules 增加 sample_prev_status（排期前样品状态）列，删除排期时按此回退样品状态（幂等）。"""
    cols = [row[1] for row in db.execute(text("PRAGMA table_info(schedules)"))]
    if "sample_prev_status" not in cols:
        db.execute(text("ALTER TABLE schedules ADD COLUMN sample_prev_status VARCHAR(16) DEFAULT ''"))
        db.commit()


def _migrate_report_content(db):
    """为 reports 增加 content（正文快照）列（幂等）。"""
    cols = [row[1] for row in db.execute(text("PRAGMA table_info(reports)"))]
    if "content" not in cols:
        db.execute(text("ALTER TABLE reports ADD COLUMN content TEXT DEFAULT ''"))


def _migrate_report_docx(db):
    """为 reports / report_drafts 增加 docx_content（.docx 正文快照，OnlyOffice 编辑后以它为准）。幂等。"""
    for table in ("reports", "report_drafts"):
        cols = [row[1] for row in db.execute(text(f"PRAGMA table_info({table})"))]
        if "docx_content" not in cols:
            db.execute(text(f"ALTER TABLE {table} ADD COLUMN docx_content BLOB"))


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
