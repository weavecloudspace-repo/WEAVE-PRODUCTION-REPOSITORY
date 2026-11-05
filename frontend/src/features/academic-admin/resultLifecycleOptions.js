const actionSets = {
  draft: [
    { key: "edit", label: "Edit scores" },
    { key: "submitted", label: "Submit for review" },
  ],
  submitted: [
    { key: "approved", label: "Approve result" },
    { key: "return_to_draft", label: "Return to draft" },
  ],
  approved: [
    { key: "locked", label: "Lock result" },
    { key: "return_to_draft", label: "Return to draft" },
  ],
  locked: [{ key: "return_to_draft", label: "Reopen to draft" }],
};

export const resultLifecycleOptions = (status) => actionSets[status] || [];
