export function canRequestAICredits(quota) {
  return (
    quota?.actor_type === "teacher" &&
    quota.total_available_credits === 0 &&
    quota.weekly?.available_credits === 0 &&
    quota.extra?.available_credits === 0 &&
    quota.weekly?.reserved_credits === 0 &&
    quota.extra?.reserved_credits === 0
  );
}

export function purchasePath(quota) {
  if (quota?.actor_type === "teacher") return "/ai/teacher/purchases";
  if (quota?.actor_type === "tenant_admin") return "/ai/admin/quota/purchases";
  throw new Error("Credit purchasing is unavailable for this account.");
}

export function paystackCheckoutUrl(value) {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.hostname !== "checkout.paystack.com") {
    throw new Error("The payment provider returned an invalid checkout link.");
  }
  return url.href;
}

export async function pendingCreditRequests(api) {
  const pending = [];
  let offset = 0;
  let page;
  do {
    page = await api.get(`/ai/quota/requests?offset=${offset}&limit=100`);
    pending.push(...page.items.filter((r) => r.status === "pending"));
    offset += page.items.length;
  } while (offset < page.total && page.items.length);
  return pending;
}
