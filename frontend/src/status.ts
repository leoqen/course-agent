export const terminal = new Set(['SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED', 'INTERRUPTED']);
export const status: Record<string, string> = {
  QUEUED: '正在排队',
  RUNNING: '正在调研',
  SUCCEEDED: '已完成',
  PARTIAL: '部分完成',
  FAILED: '执行失败',
  CANCELLED: '已停止',
  INTERRUPTED: '已中断',
};
