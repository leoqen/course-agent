import { useEffect, useState } from 'react';
import { API, api } from '../api';
import type { Task, Event, Source } from '../types';
import { terminal, status } from '../status';
import { MarkdownRenderer } from './MarkdownRenderer';

export function Answer({
  task,
  onExport,
  progress,
}: {
  task: Task;
  onExport: (task: Task, format: string) => Promise<void>;
  progress: string;
}) {
  const [events, setEvents] = useState<Event[]>([]),
    [sources, setSources] = useState<Source[]>([]),
    [error, setError] = useState(''),
    [exporting, setExporting] = useState('');
  const done = terminal.has(task.status);
  useEffect(() => {
    let alive = true;
    Promise.all([
      api<Event[]>(`/api/tasks/${task.id}/events`),
      api<Source[]>(`/api/tasks/${task.id}/evidence`),
    ])
      .then(([e, s]) => {
        if (alive) {
          setEvents(e);
          setSources(s);
        }
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [task.id, task.status]);
  async function save(format: string) {
    setExporting(format);
    setError('');
    try {
      await onExport(task, format);
    } catch (e) {
      setError(String(e));
    } finally {
      setExporting('');
    }
  }
  return (
    <article className="assistant-message" aria-label="助手回答">
      <div className="assistant-avatar">研</div>
      <div className="answer-content">
        <div className="answer-label">
          课程研究助手{' '}
          <span className={!done ? 'working' : ''}>
            {!done && <i />}
            {status[task.status]}
          </span>
        </div>
        {!done && (
          <div className="thinking" role="status">
            {task.draft ? '正在生成回答…' : '正在检索资料，回答生成后会逐步显示。'}
            <small>
              {progress || events.filter((e) => e.message).at(-1)?.message || '正在准备调研…'}
            </small>
          </div>
        )}
        {(task.report || task.draft) && (
          <div className={!task.report ? 'streaming-answer' : ''}>
            <MarkdownRenderer
              content={(task.report || task.draft || '').split('\n## 本次来源与查询附录')[0]}
            />
          </div>
        )}
        {done && !task.report && task.draft && (
          <p className="muted">以上为未完成草稿，尚未完成引用检查。</p>
        )}
        {task.error && <p className="inline-error">{task.error}</p>}
        {done && !task.report && !task.draft && !task.error && (
          <p className="muted">本次没有形成回答，你可以继续发送消息重试。</p>
        )}
        {done && task.report && (
          <div className="answer-actions">
            <button disabled={!!exporting} onClick={() => save('markdown')}>
              {exporting === 'markdown' ? '正在生成…' : '导出 Markdown'}
            </button>
            <button disabled={!!exporting} onClick={() => save('pdf')}>
              {exporting === 'pdf' ? '正在生成…' : '导出 PDF'}
            </button>
            {task.files?.map((f) => (
              <a key={f.id} href={`${API}/api/download/${f.id}`}>
                {f.name}
              </a>
            ))}
          </div>
        )}
        {error && (
          <p role="alert" className="inline-error">
            {error}
          </p>
        )}
        <details className="research-details">
          <summary>查看调研过程与来源{sources.length ? ` · ${sources.length} 项证据` : ''}</summary>
          <div className="detail-metrics">
            模型调用 {String(task.metrics.model_calls ?? '—')} · 工具调用{' '}
            {String(task.metrics.tool_calls ?? '—')} · 耗时 {String(task.metrics.seconds ?? '—')}s
          </div>
          <ol>
            {events
              .filter((e) => e.message)
              .map((e) => (
                <li key={e.seq}>{e.message}</li>
              ))}
          </ol>
          {sources.map((s) => (
            <details key={s.evidence_id}>
              <summary>
                [{s.evidence_id}] {s.title || s.document_name || '销售查询'}
              </summary>
              <pre>{JSON.stringify(s, null, 2)}</pre>
            </details>
          ))}
        </details>
      </div>
    </article>
  );
}
