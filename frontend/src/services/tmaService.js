import { api } from "./api";
import { tmaReadRequest } from "./tmaReadRequest";

const path = (id, suffix = "") => `/tma/assignments/${id}${suffix}`;
const read = (endpoint) =>
  tmaReadRequest((signal) => api.get(endpoint, { signal }));
export const tmaService = {
  configuration: () => read("/tma/configuration"),
  list: (offset = 0) => read(`/tma/assignments?offset=${offset}&limit=24`),
  create: (body) => api.post("/tma/assignments", body),
  get: (id) => read(path(id)),
  update: (id, body) => api.patch(path(id), body),
  questions: (id) => read(path(id, "/questions")),
  addQuestion: (id, body) => api.post(path(id, "/questions"), body),
  updateQuestion: (id, question, body) =>
    api.patch(path(id, `/questions/${question}`), body),
  deleteQuestion: (id, question) =>
    api.delete(path(id, `/questions/${question}`)),
  readiness: (id) => read(path(id, "/readiness")),
  activate: (id) => api.post(path(id, "/activate"), {}),
  close: (id) => api.post(path(id, "/close"), {}),
  cancel: (id, reason) => api.post(path(id, "/cancel"), { reason }),
  cancellation: (id) => read(path(id, "/cancellation")),
  retryCancellation: (id) => api.post(path(id, "/cancellation/retry"), {}),
  revise: (id) => api.post(path(id, "/revisions"), {}),
  revisions: (id) => read(path(id, "/revisions")),
  submissions: (id, params) =>
    read(path(id, `/submissions?${new URLSearchParams(params)}`)),
  images: (id) => read(path(id, "/images")),
  uploadImage: (id, file) => {
    const body = new FormData();
    body.append("file", file);
    return api.postForm(path(id, "/images"), body);
  },
  imageUrl: (id, asset) => read(path(id, `/images/${asset}/url`)),
  deleteImage: (id, asset) => api.delete(path(id, `/images/${asset}`)),
  generate: (id, body, key) =>
    api.post(path(id, "/ai/questions/generate"), body, {
      headers: { "Idempotency-Key": key },
    }),
  regenerate: (id, body, key) =>
    api.post(path(id, "/ai/questions/regenerate"), body, {
      headers: { "Idempotency-Key": key },
    }),
  importQuestion: (id, question) =>
    api.post(path(id, "/ai/questions/import"), { question }),
};
