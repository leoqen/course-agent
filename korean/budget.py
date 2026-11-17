"""Per-task model, tool, search and time budgets with usage accounting."""
from dataclasses import dataclass, field
import time


class BudgetExceeded(Exception):
    pass


@dataclass
class Budget:
    settings: object
    started: float = field(default_factory=time.monotonic)
    models: int = 0
    tools: int = 0
    searches: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    unknown_usage: int = 0

    def take(self, kind):
        if time.monotonic()-self.started >= self.settings.max_seconds:
            raise BudgetExceeded('任务时间预算已耗尽')
        limit = {'models': self.settings.max_models, 'tools': self.settings.max_tools, 'searches': self.settings.max_searches}[kind]
        if getattr(self, kind) >= limit:
            raise BudgetExceeded(f'{kind} 调用预算已耗尽')
        setattr(self, kind, getattr(self, kind)+1)

    def metrics(self):
        s = self.settings
        cost = None if s.input_price is None or s.output_price is None or self.unknown_usage else (
            self.input_tokens*s.input_price + self.output_tokens*s.output_price)/1_000_000
        return {'model_calls': self.models, 'tool_calls': self.tools, 'search_calls': self.searches,
                'input_tokens': self.input_tokens, 'output_tokens': self.output_tokens, 'unknown_usage_calls': self.unknown_usage,
                'estimated_model_cost': cost, 'cost_note': '仅模型估算费用，币种由配置决定，不含搜索费用；未知为null',
                'seconds': round(time.monotonic()-self.started, 2), 'model': s.model or None}
