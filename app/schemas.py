"""Pydantic 请求/响应模型。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


# ---------------------------------------------------------------------------
# 认证
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    name: str
    username: str


# ---------------------------------------------------------------------------
# 用户
# ---------------------------------------------------------------------------
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    name: str
    role: str
    department: str
    email: str
    phone: str
    is_active: bool


class UserCreate(BaseModel):
    username: str
    password: str = "123456"
    name: str
    role: str = "experimenter"
    department: str = ""
    email: str = ""
    phone: str = ""


class UserUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    department: str | None = None
    email: str | None = None
    phone: str | None = None
    is_active: bool | None = None
    password: str | None = None


# ---------------------------------------------------------------------------
# 委托单
# ---------------------------------------------------------------------------
class OrderCreate(BaseModel):
    entrust_org: str = ""
    entrust_org_en: str = ""
    entruster: str = ""
    entruster_en: str = ""
    sample_name: str = ""
    sample_name_en: str = ""
    test_item: str = ""
    test_item_en: str = ""
    test_basis: str = ""
    test_basis_en: str = ""
    test_stage: str = ""
    sample_model: str = ""
    customer_model: str = ""
    sample_count: int = 1
    sample_unit: str = "只"
    phone: str = ""
    email: str = ""
    tracker: str = ""
    tracker_email: str = ""
    test_reason: str = "例行试验"
    report_lang: str = "中文"
    sample_status: str = "样品正常"
    storage_require: str = "常温存放"
    sample_dispose: str = "退还"
    test_condition: str = ""
    remark: str = ""
    required_start: datetime | None = None


class OrderUpdate(BaseModel):
    """仅未审核的委托单可修改，字段同创建。"""
    entrust_org: str | None = None
    entrust_org_en: str | None = None
    entruster: str | None = None
    entruster_en: str | None = None
    sample_name: str | None = None
    sample_name_en: str | None = None
    test_item: str | None = None
    test_item_en: str | None = None
    test_basis: str | None = None
    test_basis_en: str | None = None
    test_stage: str | None = None
    sample_model: str | None = None
    customer_model: str | None = None
    sample_count: int | None = None
    sample_unit: str | None = None
    phone: str | None = None
    email: str | None = None
    tracker: str | None = None
    tracker_email: str | None = None
    test_reason: str | None = None
    report_lang: str | None = None
    sample_status: str | None = None
    storage_require: str | None = None
    sample_dispose: str | None = None
    test_condition: str | None = None
    remark: str | None = None
    required_start: datetime | None = None


class SampleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sample_no: str
    order_id: int
    status: str
    condition: str
    result: str
    remark: str


class CostItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    equipment_id: int | None
    test_item: str
    equipment_name: str
    open_fee: float
    power_fee: float
    depreciation_fee: float
    consumable_fee: float
    count: int
    quantity: int
    discount: float
    amount: float


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int
    sample_id: int
    sample_no: str = ""
    equipment_id: int
    equipment_name: str = ""
    experiment_hours: float
    transition_hours: float
    total_hours: float
    plan_start: datetime | None
    plan_end: datetime | None
    actual_start: datetime | None
    actual_end: datetime | None
    status: str


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_no: str
    experiment_no: str | None
    status: str
    entrust_org: str
    entrust_org_en: str
    entruster: str
    entruster_en: str
    sample_name: str
    sample_name_en: str
    test_item: str
    test_item_en: str
    test_basis: str
    test_basis_en: str
    test_stage: str
    sample_model: str
    customer_model: str
    sample_count: int
    sample_unit: str
    phone: str
    email: str
    tracker: str
    tracker_email: str
    test_reason: str
    report_lang: str
    sample_status: str
    storage_require: str
    sample_dispose: str
    test_condition: str
    remark: str
    required_start: datetime | None
    created_at: datetime
    reviewer_id: int | None
    review_at: datetime | None
    reject_reason: str
    total_cost: float
    finish_at: datetime | None
    samples: list[SampleOut] = []
    costs: list[CostItemOut] = []
    schedules: list[ScheduleOut] = []


class ReviewRequest(BaseModel):
    approve: bool = True
    reviewer_id: int | None = None      # 实验员（可动态选择）
    reject_reason: str = ""
    required_start: datetime | None = None
    costs: list[dict] = []              # 费用明细 [{test_item, equipment_id, count, quantity, discount}]


# ---------------------------------------------------------------------------
# 样品
# ---------------------------------------------------------------------------
class SampleReceiveRequest(BaseModel):
    condition: str = "样品正常"
    remark: str = ""


class SampleDisposeRequest(BaseModel):
    action: str          # 退还 / 报废 / 留存
    remark: str = ""


class SampleOperationRequest(BaseModel):
    action: str
    remark: str = ""


# ---------------------------------------------------------------------------
# 排期
# ---------------------------------------------------------------------------
class ScheduleCreate(BaseModel):
    sample_id: int
    equipment_id: int
    experiment_hours: float = 0.0
    transition_hours: float = 0.0
    plan_start: datetime | None = None


# ---------------------------------------------------------------------------
# 实验
# ---------------------------------------------------------------------------
class ResultUpdate(BaseModel):
    sample_id: int
    result: str        # OK / NG
    condition: str = ""
    remark: str = ""


class ExperimentStartRequest(BaseModel):
    schedule_id: int


class ExperimentEndRequest(BaseModel):
    schedule_id: int


# ---------------------------------------------------------------------------
# 设备
# ---------------------------------------------------------------------------
class EquipmentCreate(BaseModel):
    name: str
    model: str = ""
    code: str = ""
    exp_type: str = "其它试验"
    sort_order: int = 0
    status: Literal["可用", "使用中", "停用", "报废"] = "可用"
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    open_fee: float = 0.0
    power_fee: float = 0.0
    depreciation_fee: float = 0.0
    consumable_fee: float = 0.0
    unit_price: float = 0.0
    power_kw: float = 0.0
    remark: str = ""


class EquipmentUpdate(BaseModel):
    name: str | None = None
    model: str | None = None
    code: str | None = None
    exp_type: str | None = None
    sort_order: int | None = None
    status: Literal["可用", "使用中", "停用", "报废"] | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    open_fee: float | None = None
    power_fee: float | None = None
    depreciation_fee: float | None = None
    consumable_fee: float | None = None
    unit_price: float | None = None
    power_kw: float | None = None
    remark: str | None = None


class EquipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    model: str
    code: str
    exp_type: str
    status: str
    sort_order: int
    valid_from: datetime | None
    valid_to: datetime | None
    open_fee: float
    power_fee: float
    depreciation_fee: float
    consumable_fee: float
    unit_price: float
    power_kw: float
    remark: str


# ---------------------------------------------------------------------------
# 交接班
# ---------------------------------------------------------------------------
class HandoverCreate(BaseModel):
    order_id: int | None = None
    note: str


# ---------------------------------------------------------------------------
# 修改密码
# ---------------------------------------------------------------------------
class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


# ---------------------------------------------------------------------------
# 设备校准 / 维保
# ---------------------------------------------------------------------------
class MaintenanceCreate(BaseModel):
    type: str = "校准"                 # 校准 / 维修 / 保养
    date: datetime | None = None
    next_date: datetime | None = None
    cost: float = 0.0
    note: str = ""
    operator: str = ""


class MaintenanceUpdate(BaseModel):
    type: str | None = None
    date: datetime | None = None
    next_date: datetime | None = None
    cost: float | None = None
    note: str | None = None
    operator: str | None = None


# ---------------------------------------------------------------------------
# 客户档案
# ---------------------------------------------------------------------------
class CustomerCreate(BaseModel):
    name: str
    contact: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    remark: str = ""


class CustomerUpdate(BaseModel):
    name: str | None = None
    contact: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    remark: str | None = None


# ---------------------------------------------------------------------------
# 报告签发
# ---------------------------------------------------------------------------
class ReportIssueRequest(BaseModel):
    report_type: str = "检测报告"      # 委托记录单 / 检测报告
    version: str = "常规"              # 常规 / 检测（检测报告用）
