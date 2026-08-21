"""ORM 数据模型。

对应同行系统的核心业务实体：用户、委托单、样品、设备、排期、费用明细、操作记录、交接班。
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


# ---------------------------------------------------------------------------
# 用户
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    name: Mapped[str] = mapped_column(String(64))          # 姓名
    role: Mapped[str] = mapped_column(String(16), default="entruster")  # admin / experimenter / entruster
    department: Mapped[str] = mapped_column(String(128), default="")     # 部门 / 委托单位
    email: Mapped[str] = mapped_column(String(128), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ---------------------------------------------------------------------------
# 委托单
# ---------------------------------------------------------------------------
class EntrustOrder(Base):
    __tablename__ = "entrust_orders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)    # 委托单编号（提交自动生成）
    experiment_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=True)  # 实验编号（审核通过后生成）

    # 状态：待审核 / 已否决 / 已审核 / 实验中 / 已完成
    status: Mapped[str] = mapped_column(String(16), default="待审核", index=True)

    # —— 双语字段 ——
    entrust_org: Mapped[str] = mapped_column(String(128), default="")      # 委托单位
    entrust_org_en: Mapped[str] = mapped_column(String(128), default="")
    entruster: Mapped[str] = mapped_column(String(64), default="")         # 委托人
    entruster_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # 绑定委托人账号（同名隔离）
    case_id: Mapped[int | None] = mapped_column(ForeignKey("test_cases.id"), nullable=True)  # 来源用例（从用例库勾选生成时）
    entruster_en: Mapped[str] = mapped_column(String(64), default="")
    sample_name: Mapped[str] = mapped_column(String(128), default="")      # 样品名称
    sample_name_en: Mapped[str] = mapped_column(String(128), default="")
    test_item: Mapped[str] = mapped_column(String(128), default="")        # 检测项目
    test_item_en: Mapped[str] = mapped_column(String(128), default="")
    test_basis: Mapped[str] = mapped_column(String(256), default="")       # 检测依据
    test_basis_en: Mapped[str] = mapped_column(String(256), default="")

    # —— 样品信息 ——
    test_stage: Mapped[str] = mapped_column(String(32), default="")        # 测试阶段
    sample_model: Mapped[str] = mapped_column(String(128), default="")     # 样品型号
    customer_model: Mapped[str] = mapped_column(String(128), default="")   # 客户型号
    sample_count: Mapped[int] = mapped_column(Integer, default=1)          # 样品数量
    sample_unit: Mapped[str] = mapped_column(String(16), default="只")      # 单位

    # —— 联系方式 ——
    phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(128), default="")            # 内网邮箱
    tracker: Mapped[str] = mapped_column(String(64), default="")           # 跟踪人
    tracker_email: Mapped[str] = mapped_column(String(256), default="")    # 跟踪人邮箱

    # —— 其他 ——
    test_reason: Mapped[str] = mapped_column(String(64), default="例行试验")  # 试验原因
    report_lang: Mapped[str] = mapped_column(String(16), default="中文")      # 报告要求
    sample_status: Mapped[str] = mapped_column(String(64), default="样品正常")
    storage_require: Mapped[str] = mapped_column(String(64), default="常温存放")
    sample_dispose: Mapped[str] = mapped_column(String(16), default="退还")    # 样品处理：退还/报废/留存
    test_condition: Mapped[str] = mapped_column(Text, default="")            # 试验条件
    criteria: Mapped[str] = mapped_column(Text, default="")                  # 判定标准
    remark: Mapped[str] = mapped_column(Text, default="")                    # 备注

    required_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 要求开始时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)       # 委托时间

    # —— 审核信息 ——
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewer: Mapped["User | None"] = relationship("User", foreign_keys=[reviewer_id])
    review_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reject_reason: Mapped[str] = mapped_column(Text, default="")            # 否决原因

    # —— 实验结束信息 ——
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)           # 费用总额
    finish_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    samples: Mapped[list["Sample"]] = relationship("Sample", back_populates="order", cascade="all, delete-orphan")
    schedules: Mapped[list["Schedule"]] = relationship("Schedule", back_populates="order", cascade="all, delete-orphan")
    costs: Mapped[list["CostItem"]] = relationship("CostItem", back_populates="order", cascade="all, delete-orphan")
    case: Mapped["TestCase | None"] = relationship("TestCase", foreign_keys=[case_id])


# ---------------------------------------------------------------------------
# 样品
# ---------------------------------------------------------------------------
class Sample(Base):
    __tablename__ = "samples"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    sample_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # 样品编号
    order_id: Mapped[int] = mapped_column(ForeignKey("entrust_orders.id"), index=True)
    order: Mapped["EntrustOrder"] = relationship("EntrustOrder", back_populates="samples")

    # 状态：待接收 / 已接收 / 已排期 / 实验中 / 已完成 / 已退还 / 已报废 / 已留存
    status: Mapped[str] = mapped_column(String(16), default="待接收", index=True)
    condition: Mapped[str] = mapped_column(String(64), default="未检查")   # 样品状况
    result: Mapped[str] = mapped_column(String(8), default="")             # 实验结果 OK / NG
    remark: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    operations: Mapped[list["SampleOperation"]] = relationship(
        "SampleOperation", back_populates="sample", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# 设备
# ---------------------------------------------------------------------------
class Equipment(Base):
    __tablename__ = "equipments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)      # 设备名称
    model: Mapped[str] = mapped_column(String(64), default="")      # 型号
    code: Mapped[str] = mapped_column(String(64), default="")       # 编号
    exp_type: Mapped[str] = mapped_column(String(16), default="其它试验")  # 实验类型：功率试验/环境试验/其它试验
    status: Mapped[str] = mapped_column(String(16), default="可用")  # 可用 / 使用中 / 停用 / 报废
    sort_order: Mapped[int] = mapped_column(Integer, default=0)      # 排序
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 计价参数
    open_fee: Mapped[float] = mapped_column(Float, default=0.0)       # 开机费
    power_fee: Mapped[float] = mapped_column(Float, default=0.0)      # 电费/小时
    depreciation_fee: Mapped[float] = mapped_column(Float, default=0.0)  # 折旧费/小时
    consumable_fee: Mapped[float] = mapped_column(Float, default=0.0) # 辅耗材/小时
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)     # 设备单价(元)
    power_kw: Mapped[float] = mapped_column(Float, default=0.0)       # 设备功率(千瓦)

    remark: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ---------------------------------------------------------------------------
# 排期计划
# ---------------------------------------------------------------------------
class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("entrust_orders.id"), index=True)
    order: Mapped["EntrustOrder"] = relationship("EntrustOrder", back_populates="schedules")
    sample_id: Mapped[int] = mapped_column(ForeignKey("samples.id"), index=True)
    sample: Mapped["Sample"] = relationship("Sample")
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipments.id"), index=True)
    equipment: Mapped["Equipment"] = relationship("Equipment")

    experiment_hours: Mapped[float] = mapped_column(Float, default=0.0)   # 实验用时（小时）
    transition_hours: Mapped[float] = mapped_column(Float, default=0.0)   # 过渡用时（小时）
    total_hours: Mapped[float] = mapped_column(Float, default=0.0)        # 总用时

    plan_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 预计开始
    plan_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)    # 预计结束
    actual_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="已排期")  # 已排期 / 实验中 / 已完成
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ---------------------------------------------------------------------------
# 费用明细
# ---------------------------------------------------------------------------
class CostItem(Base):
    __tablename__ = "cost_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("entrust_orders.id"), index=True)
    order: Mapped["EntrustOrder"] = relationship("EntrustOrder", back_populates="costs")
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey("equipments.id"), nullable=True)
    equipment: Mapped["Equipment | None"] = relationship("Equipment")

    test_item: Mapped[str] = mapped_column(String(128), default="")    # 试验项目
    equipment_name: Mapped[str] = mapped_column(String(128), default="")  # 设备名称（冗余，防止设备被删）
    open_fee: Mapped[float] = mapped_column(Float, default=0.0)        # 开机费
    power_fee: Mapped[float] = mapped_column(Float, default=0.0)       # 电费/小时
    depreciation_fee: Mapped[float] = mapped_column(Float, default=0.0)  # 折旧费/小时
    consumable_fee: Mapped[float] = mapped_column(Float, default=0.0)  # 辅耗材/小时
    count: Mapped[int] = mapped_column(Integer, default=1)             # 次数
    quantity: Mapped[int] = mapped_column(Integer, default=1)          # 数量
    discount: Mapped[float] = mapped_column(Float, default=1.0)        # 折扣
    amount: Mapped[float] = mapped_column(Float, default=0.0)          # 费用


# ---------------------------------------------------------------------------
# 样品操作明细
# ---------------------------------------------------------------------------
class SampleOperation(Base):
    __tablename__ = "sample_operations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    sample_id: Mapped[int] = mapped_column(ForeignKey("samples.id"), index=True)
    sample: Mapped["Sample"] = relationship("Sample", back_populates="operations")
    action: Mapped[str] = mapped_column(String(32), default="")       # 接收/排期/开始/结束/退还/报废/留存
    operator: Mapped[str] = mapped_column(String(64), default="")
    remark: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ---------------------------------------------------------------------------
# 日夜班交接
# ---------------------------------------------------------------------------
class ShiftHandover(Base):
    __tablename__ = "shift_handovers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("entrust_orders.id"), nullable=True)
    order_no: Mapped[str] = mapped_column(String(32), default="")      # 冗余，便于查询
    note: Mapped[str] = mapped_column(Text, default="")
    operator: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ---------------------------------------------------------------------------
# 审计日志
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64), index=True)       # 登录/创建/修改/删除/审核/接收/排期/开始实验/…
    target_type: Mapped[str] = mapped_column(String(32), default="")   # order/sample/equipment/user/report/customer
    target_id: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------
class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)  # 指定人（空=按角色广播）
    role: Mapped[str] = mapped_column(String(16), default="")          # 目标角色（空=不限）
    title: Mapped[str] = mapped_column(String(128), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    order_id: Mapped[int | None] = mapped_column(ForeignKey("entrust_orders.id"), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


# ---------------------------------------------------------------------------
# 设备校准 / 维保记录
# ---------------------------------------------------------------------------
class EquipmentMaintenance(Base):
    __tablename__ = "equipment_maintenances"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipments.id"), index=True)
    equipment: Mapped["Equipment"] = relationship("Equipment")
    type: Mapped[str] = mapped_column(String(16), default="校准")       # 校准 / 维修 / 保养
    date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)      # 本次日期
    next_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 下次到期
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str] = mapped_column(Text, default="")
    operator: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ---------------------------------------------------------------------------
# 客户 / 委托单位档案
# ---------------------------------------------------------------------------
class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)   # 委托单位名称
    contact: Mapped[str] = mapped_column(String(64), default="")              # 联系人
    phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    address: Mapped[str] = mapped_column(String(256), default="")
    remark: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ---------------------------------------------------------------------------
# 报告留档
# ---------------------------------------------------------------------------
class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("entrust_orders.id"), index=True)
    order: Mapped["EntrustOrder"] = relationship("EntrustOrder")
    report_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # 报告编号
    report_type: Mapped[str] = mapped_column(String(32), default="")  # 委托记录单 / 检测报告
    version: Mapped[str] = mapped_column(String(16), default="")      # 常规 / 检测（检测报告用）
    status: Mapped[str] = mapped_column(String(16), default="已签发")  # 草稿 / 已签发 / 已作废
    issuer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    issuer: Mapped["User | None"] = relationship("User", foreign_keys=[issuer_id])
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ---------------------------------------------------------------------------
# 测试用例库（委托人维护，全实验室共享）
# ---------------------------------------------------------------------------
class TestCaseGroup(Base):
    __tablename__ = "test_case_groups"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)   # 客户名 / 分组名
    remark: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    cases: Mapped[list["TestCase"]] = relationship(
        "TestCase", back_populates="group", cascade="all, delete-orphan")


class TestCase(Base):
    __tablename__ = "test_cases"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("test_case_groups.id"), index=True)
    group: Mapped["TestCaseGroup"] = relationship("TestCaseGroup", back_populates="cases")

    test_item: Mapped[str] = mapped_column(String(128), default="")      # 检测项目
    test_condition: Mapped[str] = mapped_column(Text, default="")        # 试验条件
    criteria: Mapped[str] = mapped_column(Text, default="")              # 判定标准
    count: Mapped[int] = mapped_column(Integer, default=1)               # 数量
    unit: Mapped[str] = mapped_column(String(16), default="只")           # 单位
    remark: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    images: Mapped[list["TestCaseImage"]] = relationship(
        "TestCaseImage", back_populates="case", cascade="all, delete-orphan")


class TestCaseImage(Base):
    __tablename__ = "test_case_images"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("test_cases.id"), index=True)
    case: Mapped["TestCase"] = relationship("TestCase", back_populates="images")
    filename: Mapped[str] = mapped_column(String(256), default="")   # 原始文件名
    path: Mapped[str] = mapped_column(String(512), default="")       # 相对访问路径 /uploads/cases/xxx
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
