import { useEffect, useRef, useState } from 'react';
import { API, api } from './api';
import type { Task, Conversation, Session, Event } from './types';
import { terminal } from './status';
import { MarkdownRenderer } from './components/MarkdownRenderer';
import { Icon } from './components/Icon';
import { Answer } from './components/Answer';
import './research.css';

export default function ResearchApp() {
  const [sessions, setSessions] = useState<Session[]>([]),
    [thread, setThread] = useState<string | null>(() => localStorage.getItem('research-chat'));
  const [conversation, setConversation] = useState<Conversation>({ messages: [], tasks: [] }),
    [health, setHealth] = useState<Record<string, unknown>>({});
  const [query, setQuery] = useState('');
  const [progress, setProgress] = useState<Record<string, string>>({});
  const [sidebar, setSidebar] = useState(false),
    [sending, setSending] = useState(false),
    [loading, setLoading] = useState(false),
    [error, setError] = useState('');
  const generation = useRef(0),
    messagesEnd = useRef<HTMLDivElement>(null),
    textarea = useRef<HTMLTextAreaElement>(null),
    pendingThread = useRef<string | null>(null),
    currentThread = useRef(thread),
    loadedThread = useRef<string | null>(null);
  const followBottom = useRef(true);
  currentThread.current = thread;
  const active = conversation.tasks.find((t) => !terminal.has(t.status));
  const offline = health.mode === 'offline';
  async function refreshSessions() {
    setSessions(await api<Session[]>('/api/conversations'));
  }
  useEffect(() => {
    api<Record<string, unknown>>('/api/health')
      .then(setHealth)
      .catch((e) => setError(String(e)));
    refreshSessions().catch((e) => setError(String(e)));
  }, []);
  useEffect(() => {
    const token = ++generation.current;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const switching = loadedThread.current !== thread;
    if (switching) {
      setConversation({ messages: [], tasks: [] });
      loadedThread.current = thread;
    }
    if (!thread) {
      localStorage.removeItem('research-chat');
      setLoading(false);
      return;
    }
    localStorage.setItem('research-chat', thread);
    setLoading(switching);
    async function load() {
      try {
        const value = await api<Conversation>(`/api/conversations/${thread}`);
        if (disposed || token !== generation.current) return;
        setConversation(value);
        setLoading(false);
        if (pendingThread.current === thread) timer = setTimeout(load, 1000);
      } catch (e) {
        if (!disposed) {
          setError(String(e));
          setLoading(false);
          timer = setTimeout(load, 2000);
        }
      }
    }
    load();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [thread, sending]);
  useEffect(() => {
    if (!active) return;
    const id = active.id;
    const connection = new EventSource(`${API}/api/tasks/${id}/stream`);
    let disposed = false,
      lastSeq = 0;
    connection.addEventListener('snapshot', (raw) => {
      if (disposed) return;
      const snapshot = JSON.parse((raw as MessageEvent).data) as { task: Task; after: number };
      lastSeq = snapshot.after;
      setConversation((prev) => ({
        ...prev,
        tasks: prev.tasks.map((t) => (t.id === id ? snapshot.task : t)),
      }));
      if (terminal.has(snapshot.task.status)) connection.close();
    });
    connection.addEventListener('update', (raw) => {
      if (disposed) return;
      const event = JSON.parse((raw as MessageEvent).data) as Event;
      if (event.seq <= lastSeq) return;
      lastSeq = event.seq;
      if (event.message) setProgress((prev) => ({ ...prev, [id]: event.message }));
      if (event.event === 'answer_delta' || event.event === 'answer_reset') {
        setConversation((prev) => ({
          ...prev,
          tasks: prev.tasks.map((t) =>
            t.id === id && !terminal.has(t.status)
              ? {
                  ...t,
                  draft:
                    event.event === 'answer_reset'
                      ? event.data.text || ''
                      : (t.draft || '') + (event.data.text || ''),
                }
              : t,
          ),
        }));
      }
    });
    connection.onerror = () => {
      // EventSource reconnects automatically; terminal snapshots also recover cleanly.
      api<Task>(`/api/tasks/${id}`)
        .then((task) => {
          if (!disposed && terminal.has(task.status)) {
            setConversation((prev) => ({
              ...prev,
              tasks: prev.tasks.map((t) => (t.id === id ? task : t)),
            }));
            connection.close();
          }
        })
        .catch(() => {});
    };
    return () => {
      disposed = true;
      connection.close();
    };
  }, [active?.id]);
  useEffect(() => {
    if (conversation.messages.length) messagesEnd.current?.scrollIntoView({ behavior: 'smooth' });
  }, [conversation.messages.length, active?.id]);
  useEffect(() => {
    if (followBottom.current) messagesEnd.current?.scrollIntoView({ behavior: 'instant' });
  }, [active?.draft, conversation.tasks.find((t) => t.report)?.report]);
  useEffect(() => {
    if (textarea.current) {
      textarea.current.style.height = 'auto';
      textarea.current.style.height = Math.min(textarea.current.scrollHeight, 180) + 'px';
    }
  }, [query]);
  function selectSession(id: string) {
    setThread(id);
    setSidebar(false);
    setQuery('');
    setError('');
  }
  function newChat() {
    setThread(null);
    setConversation({ messages: [], tasks: [] });
    setQuery('');
    setError('');
    setSidebar(false);
    textarea.current?.focus();
  }
  async function send() {
    if (!query.trim() || sending || active) return;
    const message = query.trim(),
      tid = thread || crypto.randomUUID();
    pendingThread.current = tid;
    setSending(true);
    setError('');
    try {
      const body = { message, thread_id: tid, output_format: 'none' };
      await api<{ thread_id: string }>('/api/chat', { method: 'POST', body: JSON.stringify(body) });
      if (currentThread.current === thread) {
        setThread(tid);
        setQuery('');
      }
      await refreshSessions();
    } catch (e) {
      setError(String(e));
    } finally {
      pendingThread.current = null;
      setSending(false);
    }
  }
  async function stop() {
    if (!active) return;
    try {
      await api(`/api/task/${active.id}/cancel`, { method: 'POST' });
    } catch (e) {
      setError(String(e));
    }
  }
  async function exportAnswer(task: Task, kind: string) {
    const file = await api<{ id: string; name: string }>(`/api/tasks/${task.id}/export`, {
      method: 'POST',
      body: JSON.stringify({ format: kind }),
    });
    if (currentThread.current === task.thread_id)
      setConversation((prev) => ({
        ...prev,
        tasks: prev.tasks.map((t) =>
          t.id === task.id
            ? { ...t, files: [...(t.files || []).filter((f) => f.id !== file.id), file] }
            : t,
        ),
      }));
    const a = document.createElement('a');
    a.href = `${API}/api/download/${file.id}`;
    a.download = file.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
  const taskMap = new Map(conversation.tasks.map((t) => [t.id, t]));
  const examples = [
    {
      title: '课程对比',
      text: `课程对比，K01与竞品的价格、课时与服务，不查销售。\n竞品：${offline ? '离线示例机构' : '沪江网校'}`,
    },
    {
      title: '销售复盘',
      text: '只查销售，分析K01在2026-08-01至2026-11-01的收款、退款和渠道表现。',
    },
    { title: '课程答疑', text: '只查课程，K03适合什么基础的学员？能否备考TOPIK II？' },
  ];
  return (
    <div className="chat-app">
      {sidebar && (
        <button className="sidebar-scrim" aria-label="关闭侧栏" onClick={() => setSidebar(false)} />
      )}
      <aside className={`chat-sidebar ${sidebar ? 'is-open' : ''}`}>
        <div className="sidebar-brand">
          <span className="brand-mark">研</span>
          <strong>课程研究助手</strong>
          <button
            className="mobile-close icon-button"
            aria-label="关闭侧栏"
            onClick={() => setSidebar(false)}
          >
            <Icon name="close" />
          </button>
        </div>
        <button className="new-chat" onClick={newChat}>
          <Icon name="plus" />
          新对话<span>↗</span>
        </button>
        <div className="history-label">最近对话</div>
        <nav aria-label="会话历史">
          {sessions.map((s) => (
            <button
              title={s.title}
              className={`session-item ${thread === s.thread_id ? 'selected' : ''}`}
              key={s.thread_id}
              onClick={() => selectSession(s.thread_id)}
            >
              <Icon name="chat" />
              <span>{s.title}</span>
            </button>
          ))}
          {!sessions.length && <p className="history-empty">你的调研对话会保存在这里</p>}
        </nav>
        <div className="sidebar-footer">
          <span className="workspace-dot" />
          <div>
            韩语课程研究空间<small>课程资料 · 竞品 · 销售</small>
          </div>
        </div>
      </aside>
      <main className="chat-main">
        <header className="chat-topbar">
          <div>
            <button
              className="mobile-menu icon-button"
              aria-label="打开侧栏"
              onClick={() => setSidebar(true)}
            >
              <Icon name="menu" />
            </button>
            <span>韩语课程调研</span>
            <span className="topbar-chevron">⌄</span>
          </div>
          <span className={`mode-pill ${offline ? 'offline' : ''}`}>
            <i />
            {health.mode ? (offline ? '离线演示' : '在线调研') : '连接中'}
          </span>
        </header>
        <div className="data-notice">
          {offline
            ? '离线演示：使用固定合成样例，不调用大模型和真实搜索。'
            : '自家课程与销售记录为合成验证数据；竞品信息以采集时状态为准。'}
        </div>
        <section
          className={`chat-scroll ${!conversation.messages.length && !loading ? 'is-empty' : ''}`}
          aria-label="对话内容"
          onScroll={(e) => {
            const el = e.currentTarget;
            followBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
          }}
        >
          {loading && !conversation.messages.length && (
            <div className="loading-chat" role="status">
              正在读取对话…
            </div>
          )}
          {!conversation.messages.length && !loading && (
            <div className="chat-welcome">
              <div className="welcome-emblem">研</div>
              <p className="welcome-kicker">从问题出发，让依据说话</p>
              <h1>今天想了解什么？</h1>
              <p>对比韩语课程、查阅课程资料，或一起复盘销售表现。</p>
              <div className="suggestions">
                {examples.map((x, i) => (
                  <button
                    key={x.title}
                    onClick={() => {
                      setQuery(x.text);
                      textarea.current?.focus();
                    }}
                  >
                    <span>0{i + 1}</span>
                    <strong>{x.title}</strong>
                    <p>
                      {
                        [
                          '看看自家与竞品，有哪些差异',
                          '从订单、退款和渠道发现变化',
                          '从课程原文中找到答案',
                        ][i]
                      }
                    </p>
                    <b>↗</b>
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="message-list">
            {conversation.messages.map((m) => (
              <div key={m.seq}>
                {m.role === 'user' ? (
                  <>
                    <div className="user-message">
                      <div>{m.content}</div>
                    </div>
                    {m.task_id && taskMap.get(m.task_id) && (
                      <Answer
                        task={taskMap.get(m.task_id)!}
                        onExport={exportAnswer}
                        progress={progress[m.task_id] || ''}
                      />
                    )}
                  </>
                ) : (
                  <article className="assistant-message">
                    <div className="assistant-avatar">研</div>
                    <div className="answer-content">
                      <div className="answer-label">课程研究助手</div>
                      <MarkdownRenderer content={m.content} />
                    </div>
                  </article>
                )}
              </div>
            ))}
            {sending && (
              <div className="sending-indicator" role="status">
                正在发送…
              </div>
            )}
            <div ref={messagesEnd} />
          </div>
        </section>
        <div className="composer-region">
          {error && (
            <div className="chat-error" role="alert">
              {error}
              <button aria-label="关闭提示" onClick={() => setError('')}>
                ×
              </button>
            </div>
          )}
          <div className="chat-composer">
            <textarea
              ref={textarea}
              aria-label="发送消息"
              placeholder="向课程研究助手提问…"
              rows={2}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send();
                }
              }}
            />
            <div className="composer-toolbar">
              {active ? (
                <button className="send-button stop-button" aria-label="停止生成" onClick={stop}>
                  <Icon name="stop" />
                </button>
              ) : (
                <button
                  className="send-button"
                  aria-label="发送"
                  disabled={sending || !query.trim()}
                  onClick={send}
                >
                  <Icon name="arrow" />
                </button>
              )}
            </div>
          </div>
          <p className="composer-footnote">
            Enter 发送 · Shift + Enter 换行 <span>回答后也可导出文件</span>
          </p>
        </div>
      </main>
    </div>
  );
}
