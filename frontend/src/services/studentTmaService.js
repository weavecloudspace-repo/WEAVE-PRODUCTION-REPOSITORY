import { api } from "./api";
import { tmaReadRequest } from "./tmaReadRequest";

const root = "/students/tma";
const read = (path) =>
  tmaReadRequest((signal) => api.get(root + path, { signal }));

// Writes continue across SPA navigation. An uncertain response is retried against
// the same attempt; answers are idempotent replacements and submit is idempotent.
async function write(send) {
  const controller = new AbortController();
  let timer;
  try {
    return await Promise.race([
      send(controller.signal),
      new Promise((_, reject) => {
        timer = setTimeout(() => {
          reject(
            new Error(
              "We could not confirm the save. Check your connection and retry.",
            ),
          );
          controller.abort();
        }, 25000);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

export const studentTmaService = {
  list: () => read("/assignments"),
  start: (id) =>
    write((signal) =>
      api.post(`${root}/assignments/${id}/start`, {}, { signal }),
    ),
  resume: (id) => read(`/attempts/${id}`),
  save: (id, questionId, optionId) =>
    write((signal) =>
      api.put(
        `${root}/attempts/${id}/answer`,
        {
          question_id: questionId,
          selected_option_id: optionId,
        },
        { signal, keepalive: true },
      ),
    ),
  submit: (id) =>
    write((signal) =>
      api.post(`${root}/attempts/${id}/submit`, {}, { signal }),
    ),
  result: (id) => read(`/attempts/${id}/result`),
  image: (id, asset) => read(`/attempts/${id}/images/${asset}/url`),
};
