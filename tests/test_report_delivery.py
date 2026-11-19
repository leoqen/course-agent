"""The rendered sales table is the same stored, streamed and exported answer."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from korean.config import Settings
from korean.report_tables import render_sales_tables
from korean.server import create_app
from test_research import wait_task


def test_direct_sales_table_survives_sse_markdown_pdf_and_export_without_model_calls(tmp_path):
    calls = []
    async def generate(s, store, task, tools, budget, saver):
        calls.append(task['id'])
        await tools.schema()
        await tools.monthly()
        report = render_sales_tables(tools.sales_tables, tools.sales_rules_id)
        store.answer_chunk(task['id'], report, reset=True)
        return report
    settings = Settings(data=tmp_path, mode='offline')
    # Seed the synthetic SQL fixture, then use the real tools through a live stub.
    from korean.sales import Sales
    Sales(settings, offline=True)
    settings.mode = 'live'; settings.model = 'test'; settings.api_key = 'test'
    with patch('korean.server.live_report', generate), patch('korean.tools.Sales',
            side_effect=lambda s, offline=False: Sales(s, offline=True)), TestClient(create_app(settings)) as client:
        tid = client.post('/api/task', json={'course_id': 'K01', 'research_scope': 'sales',
             'start_date': '2026-05-01', 'end_date': '2026-06-01'}).json()['task_id']
        task = wait_task(client, tid)
        assert task['status'] == 'SUCCEEDED'
        assert '[[SALES_TABLES]]' not in task['report']
        assert '| 2026-05-01～06-01 | 173 | 290640.00 | 10080.00 | 280560.00 |' in task['report']
        stream = client.get(f'/api/tasks/{tid}/stream').text
        assert 'snapshot' in stream and '280560.00' in stream
        for kind in ['markdown', 'pdf']:
            artifact = client.post(f'/api/tasks/{tid}/export', json={'format': kind}).json()
            data = client.get('/api/download/'+artifact['id']).content
            if kind == 'markdown':
                assert data.decode('utf-8').replace('\r\n', '\n') == task['report']
            else:
                assert data.startswith(b'%PDF')
            assert client.post(f'/api/tasks/{tid}/export', json={'format': kind}).json()['id'] == artifact['id']
        assert calls == [tid]
