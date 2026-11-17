from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator


SCOPE_SOURCES = {
    'full': {'network', 'rag', 'sales'},
    'comparison': {'network', 'rag'},
    'network': {'network'},
    'course': {'rag'},
    'sales': {'sales'},
}


class TaskRequest(BaseModel):
    query: str = Field(default='', max_length=4000)
    thread_id: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    course_id: Literal['K01', 'K02', 'K03'] | None = None
    competitors: list[str] = Field(default_factory=list, max_length=3)
    start_date: date = date(2026, 8, 1)
    end_date: date = date(2026, 11, 1)
    output_format: Literal['none', 'markdown', 'pdf', 'both'] = 'none'
    analysis_mode: Literal['multi', 'single'] = 'multi'
    research_scope: Literal['full', 'comparison', 'network', 'course', 'sales'] = 'full'

    @field_validator('competitors')
    @classmethod
    def names(cls, v):
        values = list(dict.fromkeys(x.strip() for x in v if x.strip()))
        if any(len(x) > 300 for x in values):
            raise ValueError('机构名称或官网链接过长')
        return values

    @model_validator(mode='after')
    def dates(self):
        if self.end_date <= self.start_date:
            raise ValueError('结束日期必须晚于开始日期；结束日期不计入区间')
        return self


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    course_id: Literal['K01', 'K02', 'K03'] | None = None
    competitors: list[str] | None = Field(default=None, max_length=3)
    start_date: date | None = None
    end_date: date | None = None
    output_format: Literal['none', 'markdown', 'pdf', 'both'] = 'none'


class ExportRequest(BaseModel):
    format: Literal['markdown', 'pdf']
