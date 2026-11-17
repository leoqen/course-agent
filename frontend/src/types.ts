export type Task = {
  id: string;
  thread_id: string;
  status: string;
  request: {
    query: string;
    course_id: string;
    competitors: string[];
    start_date: string;
    end_date: string;
  };
  report: string;
  draft?: string;
  error: string;
  metrics: Record<string, unknown>;
  files: { id: string; name: string }[];
};
export type Message = { seq: number; role: string; content: string; task_id: string | null };
export type Conversation = { messages: Message[]; tasks: Task[] };
export type Session = { thread_id: string; title: string; updated: number };
export type Event = {
  seq: number;
  message: string;
  event: string;
  task_id: string;
  data: { text?: string };
};
export type Source = { evidence_id: string; kind: string; title?: string; document_name?: string };
