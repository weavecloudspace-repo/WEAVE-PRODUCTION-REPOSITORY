import { api } from "./api";

const path = (id, suffix = "") => `/tma/assignments/${id}${suffix}`;
export const tmaService = {
  configuration: () => api.get("/tma/configuration"),
  list: (offset = 0) => api.get(`/tma/assignments?offset=${offset}&limit=24`),
  create: (body) => api.post("/tma/assignments", body),
  get: (id) => api.get(path(id)),
  update: (id, body) => api.patch(path(id), body),
  questions: (id) => api.get(path(id, "/questions")),
  addQuestion: (id, body) => api.post(path(id, "/questions"), body),
  updateQuestion: (id, question, body) =>
    api.patch(path(id, `/questions/${question}`), body),
  deleteQuestion: (id, question) =>
    api.delete(path(id, `/questions/${question}`)),
  readiness: (id) => api.get(path(id, "/readiness")),
  activate: (id) => api.post(path(id, "/activate"), {}),
  close: (id) => api.post(path(id, "/close"), {}),
  cancel: (id, reason) => api.post(path(id, "/cancel"), { reason }),
  cancellation: (id) => api.get(path(id, "/cancellation")),
  retryCancellation: (id) => api.post(path(id, "/cancellation/retry"), {}),
  revise: (id) => api.post(path(id, "/revisions"), {}),
  revisions: (id) => api.get(path(id, "/revisions")),
  submissions: (id, params) =>
    api.get(path(id, `/submissions?${new URLSearchParams(params)}`)),
  images: (id) => api.get(path(id, "/images")),
  uploadImage: (id, file) => {
    const body = new FormData();
    body.append("file", file);
    return api.postForm(path(id, "/images"), body);
  },
  imageUrl: (id, asset) => api.get(path(id, `/images/${asset}/url`)),
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
