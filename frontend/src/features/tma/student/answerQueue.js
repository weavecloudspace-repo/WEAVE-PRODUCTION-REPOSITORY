// Serialize replacements so a slow save can never overwrite a newer selection.
// Failed entries stay pending. No answer or attempt is stored in browser caches.
export function createAnswerQueue(save, notify = () => {}) {
  const entries = new Map();
  let running = null;
  let error = null;
  let listener = notify;
  const snapshot = () => ({
    pending: [...entries.keys()],
    saving: Boolean(running),
    error,
  });
  const emit = () => listener?.(snapshot());
  function drain() {
    if (running) return running;
    error = null;
    running = (async () => {
      while (entries.size) {
        const [questionId, entry] = entries.entries().next().value;
        try {
          await save(questionId, entry.optionId);
        } catch (cause) {
          error = cause;
          throw cause;
        }
        if (entries.get(questionId) === entry) entries.delete(questionId);
        emit();
      }
    })().finally(() => {
      running = null;
      emit();
    });
    emit();
    return running;
  }
  return {
    select(questionId, optionId) {
      entries.set(questionId, { optionId });
      emit();
      drain().catch(() => {});
    },
    async flush() {
      if (running) await running;
      if (entries.size) await drain();
    },
    snapshot,
    detach() {
      listener = null;
    },
  };
}
