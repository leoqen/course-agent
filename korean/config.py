from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv, dotenv_values

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
COURSES = {
    'K01': {'name': '韩语零基础入门班', 'price': 1680, 'lessons': 24, 'minutes': 50},
    'K02': {'name': '韩语日常交流班', 'price': 2480, 'lessons': 32, 'minutes': 50},
    'K03': {'name': 'TOPIK初级备考班', 'price': 2980, 'lessons': 36, 'minutes': 60},
}


@dataclass
class Settings:
    data: Path = ROOT / 'data'
    mode: str = 'live'
    model: str = ''
    api_key: str = ''
    base_url: str = 'https://api.openai.com/v1'
    tavily_key: str = ''
    rag_url: str = 'http://127.0.0.1:8897'
    rag_token: str = ''
    mysql_host: str = '127.0.0.1'
    mysql_port: int = 3307
    mysql_user: str = 'korean_reader'
    mysql_password: str = ''
    mysql_database: str = 'korean_sales_demo'
    max_seconds: int = 600
    max_models: int = 60
    max_tools: int = 40
    max_searches: int = 10
    input_price: float | None = None
    output_price: float | None = None

    @classmethod
    def env(cls):
        # Explicit local reference reuses the existing provider without copying
        # its API key into another project's .env or logs.
        model_source = os.getenv('RESEARCH_MODEL_ENV_FILE', '')
        linked = dotenv_values(model_source) if model_source else {}
        def price(name):
            value = os.getenv(name)
            return float(value) if value else None
        return cls(data=Path(os.getenv('RESEARCH_DATA_DIR', str(ROOT / 'data'))).resolve(),
                   mode=os.getenv('RESEARCH_MODE', 'live'), model=os.getenv('RESEARCH_MODEL') or linked.get('DEEPSEEK_MODEL', ''),
                   api_key=os.getenv('OPENAI_API_KEY') or linked.get('DEEPSEEK_API_KEY', ''), base_url=os.getenv('OPENAI_BASE_URL') or linked.get('DEEPSEEK_BASE_URL') or 'https://api.openai.com/v1',
                   tavily_key=os.getenv('TAVILY_API_KEY', ''), rag_url=os.getenv('RAG_BASE_URL', 'http://127.0.0.1:8897'),
                   rag_token=os.getenv('RAG_RESEARCH_TOKEN', ''), mysql_host=os.getenv('MYSQL_HOST', '127.0.0.1'),
                   mysql_port=int(os.getenv('MYSQL_PORT', '3307')), mysql_user=os.getenv('MYSQL_USER', 'korean_reader'),
                   mysql_password=os.getenv('MYSQL_PASSWORD', ''), mysql_database=os.getenv('MYSQL_DATABASE', 'korean_sales_demo'),
                   input_price=price('MODEL_INPUT_PRICE_PER_MILLION'), output_price=price('MODEL_OUTPUT_PRICE_PER_MILLION'))
