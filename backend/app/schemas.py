"""รูปแบบข้อมูลที่ API ส่ง/รับ — แหล่งของ OpenAPI และ TypeScript types ของหน้าเว็บ

element tree มาจาก ui.PageRun (หนึ่ง element ต่อหนึ่งคำสั่ง st.* ของหน้าเดิม) ตรวจรูปแบบก่อนส่งทุกครั้ง
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Markdown(_M):
    type: Literal["markdown"]
    kind: Literal["markdown", "caption"]
    body: str
    allow_html: bool
    help: Optional[str] = None


class Alert(_M):
    type: Literal["alert"]
    kind: Literal["info", "success", "warning", "error"]
    body: str
    icon: Optional[str] = None


class Button(_M):
    type: Literal["button"]
    id: str
    label: str
    kind: str
    icon: Optional[str] = None
    help: Optional[str] = None
    disabled: bool
    use_container_width: bool
    form_id: Optional[str] = None
    is_form_submitter: bool = False


class DownloadButton(_M):
    type: Literal["download_button"]
    id: str
    label: str
    file_name: Optional[str] = None
    mime: str
    ref: str
    url: str
    kind: str
    icon: Optional[str] = None
    disabled: bool
    help: Optional[str] = None
    use_container_width: bool


class Selectbox(_M):
    type: Literal["selectbox"]
    id: str
    label: str
    options: list[str]
    index: Optional[int] = None
    default: Optional[int] = None
    help: Optional[str] = None
    disabled: bool
    label_visibility: str
    placeholder: Optional[str] = None
    form_id: Optional[str] = None


class Multiselect(_M):
    type: Literal["multiselect"]
    id: str
    label: str
    options: list[str]
    value: list[int]
    default: list[int]
    help: Optional[str] = None
    disabled: bool
    label_visibility: str
    placeholder: Optional[str] = None
    form_id: Optional[str] = None


class NumberInput(_M):
    type: Literal["number_input"]
    id: str
    label: str
    value: float
    default: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    step: float
    format: str
    int: bool
    help: Optional[str] = None
    disabled: bool
    label_visibility: str
    placeholder: Optional[str] = None
    form_id: Optional[str] = None


class Slider(_M):
    type: Literal["slider"]
    id: str
    label: str
    value: float
    default: float
    min: float
    max: float
    step: float
    format: Optional[str] = None
    int: bool
    help: Optional[str] = None
    disabled: bool
    label_visibility: str
    form_id: Optional[str] = None


class Toggle(_M):
    type: Literal["toggle"]
    id: str
    label: str
    value: bool
    default: bool
    help: Optional[str] = None
    disabled: bool
    label_visibility: str
    form_id: Optional[str] = None


class _Text(_M):
    id: str
    label: str
    value: str
    default: str
    max_chars: Optional[int] = None
    input_type: str
    help: Optional[str] = None
    placeholder: Optional[str] = None
    label_visibility: str
    disabled: bool
    autocomplete: Optional[str] = None
    height: Optional[int] = None
    form_id: Optional[str] = None


class TextInput(_Text):
    type: Literal["text_input"]


class TextArea(_Text):
    type: Literal["text_area"]


class VegaLiteChart(_M):
    type: Literal["vega_lite_chart"]
    spec: dict[str, Any]
    use_container_width: bool
    theme: Optional[str] = None


class DataFrame(_M):
    type: Literal["dataframe"]
    columns: list[str]
    index: Optional[list[Any]] = None
    rows: list[list[Any]]
    use_container_width: bool


class Spinner(_M):
    type: Literal["spinner"]
    text: str


class ExceptionEl(_M):
    type: Literal["exception"]
    ref: str


class Container(_M):
    type: Literal["container"]
    key: Optional[str] = None
    border: bool
    height: Optional[int] = None
    children: list[Element]


class Column(_M):
    type: Literal["column"]
    weight: float
    children: list[Element]


class Columns(_M):
    type: Literal["columns"]
    gap: str
    vertical_alignment: str
    border: bool
    children: list[Column]


class Expander(_M):
    type: Literal["expander"]
    label: str
    expanded: bool
    key: Optional[str] = None
    icon: Optional[str] = None
    children: list[Element]


class Form(_M):
    type: Literal["form"]
    form_id: str
    border: bool
    children: list[Element]


Element = Annotated[
    Union[Markdown, Alert, Button, DownloadButton, Selectbox, Multiselect, NumberInput, Slider, Toggle, TextInput,
          TextArea, VegaLiteChart, DataFrame, Spinner, ExceptionEl, Container, Columns, Expander, Form],
    Field(discriminator="type"),
]


class Root(_M):
    type: Literal["main", "sidebar"]
    children: list[Element]


class View(_M):
    main: Root
    sidebar: Root
    page_config: dict[str, Any]
    pending: bool = Field(description="หน้ากำลังรอ job ของ worker — ถาม /pending แล้วส่ง resume เมื่อเสร็จ")
    csrf_token: str


Value = Union[bool, int, float, str, list[int], None]


class Event(_M):
    trigger: Optional[str] = Field(None, max_length=400, description="id ของปุ่มที่กด")
    values: dict[str, Value] = Field(default_factory=dict, description="ค่าใหม่ของช่องต่าง ๆ ตาม id")
    resume: bool = Field(False, description="รันหน้าต่อหลัง job ที่รออยู่เสร็จ")


class PendingStatus(_M):
    pending: bool
    status: Optional[Literal["queued", "running", "succeeded", "failed"]] = None


class Health(_M):
    status: Literal["ok", "degraded"]
    database: bool
    worker_seen_seconds_ago: Optional[float] = None


for _m in (Container, Column, Expander, Form, Root, View):
    _m.model_rebuild()
