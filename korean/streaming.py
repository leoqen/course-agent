"""Persist only main-agent answer text as resumable stream drafts."""
import time


class AnswerStream:
    """Batch main-model text only; never publish specialist/tool/reasoning output."""
    def __init__(self, store, tid, transform=None):
        self.store, self.tid = store, tid
        self.message_id = None
        self.pending = ''
        self.last_flush = 0.0
        self.transform = transform

    def push(self, message, metadata):
        if 'answer_main' not in metadata.get('tags', []):
            return
        if getattr(message, 'type', '') not in {'AIMessageChunk', 'ai'}:
            return
        if message.id != self.message_id:
            self.pending = ''
            self.message_id = message.id
            self.store.answer_chunk(self.tid, '', reset=True)
            if self.transform:
                self.transform.reset()
        content = message.content
        text = content if isinstance(content, str) else ''.join(
            b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text')
        self.pending += self.transform.feed(text) if self.transform else text
        if time.monotonic() - self.last_flush >= .08:
            self.flush()

    def flush(self):
        if self.pending:
            self.store.answer_chunk(self.tid, self.pending)
            self.pending = ''
            self.last_flush = time.monotonic()

    def clear(self):
        self.pending = ''
        self.message_id = None
        self.store.answer_chunk(self.tid, '', reset=True)
        if self.transform:
            self.transform.reset()
