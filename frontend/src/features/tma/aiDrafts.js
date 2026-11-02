// CBT's IndexedDB draft workflow, scoped to the tenant, membership and assignment.
export function aiDraftScope(user, role, assignmentId) {
  const tenant = user?.tenant_id || user?.tenant?.id;
  const actor = user?.membership_id || user?.id;
  if (!tenant || !actor) return null;
  return `${tenant}:${role}:${actor}:${assignmentId}`;
}

export function createAIDraftStore(
  scope,
  indexedDBImpl = globalThis.indexedDB,
) {
  async function transact(mode, action) {
    if (!indexedDBImpl)
      throw new Error(
        "Browser draft storage is unavailable. Enable site storage to continue.",
      );
    const db = await new Promise((resolve, reject) => {
      const request = indexedDBImpl.open(`weave-tma-ai:v1:${scope}`, 1);
      request.onupgradeneeded = () =>
        request.result.createObjectStore("drafts", { keyPath: "draft_id" });
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction("drafts", mode);
        let result;
        let failure;
        tx.oncomplete = () => resolve(result);
        tx.onerror = () =>
          reject(tx.error || new Error("Could not save browser draft."));
        tx.onabort = () =>
          reject(
            failure ||
              tx.error ||
              new Error("Browser draft operation was interrupted."),
          );
        action(
          tx.objectStore("drafts"),
          (value) => {
            result = value;
          },
          tx,
          (e) => {
            failure = e;
          },
        );
      });
    } finally {
      db.close();
    }
  }
  return {
    list: () =>
      transact("readonly", (store, done) => {
        const request = store.getAll();
        request.onsuccess = () => done(request.result);
      }),
    get: (id) =>
      transact("readonly", (store, done) => {
        const request = store.get(id);
        request.onsuccess = () => done(request.result);
      }),
    put: (draft) =>
      transact("readwrite", (store, done) => {
        store.put(draft);
        done(draft);
      }),
    delete: (id) =>
      transact("readwrite", (store) => {
        store.delete(id);
      }),
    change: (id, transform) =>
      transact("readwrite", (store, done, tx, fail) => {
        const request = store.get(id);
        request.onsuccess = () => {
          try {
            const next = transform(request.result);
            store.put(next);
            done(next);
          } catch (e) {
            // Abort without overwriting a draft locked by another tab.
            fail(e);
            tx.abort();
          }
        };
      }),
  };
}

export function validateAIQuestion(q) {
  if (!q.prompt?.trim() && !q.image) return "Add question text or an image.";
  if (q.options.length < 4 || q.options.length > 50)
    return "Keep between four and fifty options.";
  if (q.options.some((o) => !o.text?.trim() && !o.image))
    return "Every option needs text or an image.";
  if (q.options.filter((o) => o.is_correct).length !== 1)
    return "Select exactly one correct answer.";
  return "";
}

export function createAIDraftController({
  store,
  service,
  assignmentId,
  revisionNumber,
  uuid = () => crypto.randomUUID(),
}) {
  const editable = (draft) => {
    if (!draft || draft.status !== "review" || draft.pending_regeneration) {
      throw new Error(
        "Recover the pending operation before editing this draft.",
      );
    }
    return draft;
  };
  async function finishGeneration(draft) {
    const result = await service.generate(
      assignmentId,
      draft.input,
      draft.draft_id,
    );
    return store.put({
      ...draft,
      questions: result.questions,
      status: "review",
    });
  }
  async function finishRegeneration(draft) {
    const pending = draft.pending_regeneration;
    let result;
    try {
      result = await service.regenerate(
        assignmentId,
        pending.body,
        pending.key,
      );
    } catch (e) {
      if ([400, 422].includes(e.status || e.response?.status)) {
        await store.change(draft.draft_id, (current) => ({
          ...current,
          pending_regeneration: null,
        }));
      }
      throw e;
    }
    return store.change(draft.draft_id, (current) => {
      if (current.pending_regeneration?.key !== pending.key) return current;
      return {
        ...current,
        pending_regeneration: null,
        questions: current.questions.map((q, i) =>
          i === pending.index ? result.question : q,
        ),
      };
    });
  }
  return {
    async generate(input) {
      const draft = {
        draft_id: uuid(),
        assignment_id: assignmentId,
        revision_number: revisionNumber,
        input,
        questions: [],
        status: "generating",
        created_at: new Date().toISOString(),
      };
      await store.put(draft);
      return finishGeneration(draft);
    },
    async recover(id) {
      const draft = await store.get(id);
      if (!draft) throw new Error("This browser draft is no longer available.");
      if (draft.status === "generating") return finishGeneration(draft);
      if (draft.pending_regeneration) return finishRegeneration(draft);
      return draft;
    },
    update: (id, questions) =>
      store.change(id, (draft) => ({ ...editable(draft), questions })),
    async regenerate(id, index, instruction) {
      const draft = await store.change(id, (current) => {
        editable(current);
        return {
          ...current,
          pending_regeneration: {
            index,
            key: uuid(),
            body: {
              ...current.input,
              question_count: undefined,
              existing_question: current.questions[index],
              instruction,
            },
          },
        };
      });
      return finishRegeneration(draft);
    },
    async save(id) {
      const draft = await store.change(id, (current) => {
        if (current?.status === "saving") return current;
        editable(current);
        if (!current.questions.length)
          throw new Error("Keep at least one question before adding.");
        const invalid = current.questions.map(validateAIQuestion).find(Boolean);
        if (invalid) throw new Error(invalid);
        return { ...current, status: "saving" };
      });
      let result;
      try {
        result = await service.importQuestions(assignmentId, {
          draft_id: draft.draft_id,
          revision_number: draft.revision_number,
          questions: draft.questions,
        });
      } catch (e) {
        // A validation rejection has no writes. An uncertain response stays frozen for safe retry.
        if ([400, 422].includes(e.status || e.response?.status))
          await store.change(id, (current) => ({
            ...current,
            status: "review",
          }));
        throw e;
      }
      try {
        await store.delete(id);
      } catch {
        /* Confirmed saves remain successful. */
      }
      return result;
    },
  };
}
