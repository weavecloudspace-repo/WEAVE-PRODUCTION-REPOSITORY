import { useEffect, useRef, useState } from "react";
import Button from "../../components/ui/Button";
import Modal from "../../components/ui/Modal";
import { api } from "../../services/api";
import {
  canRequestAICredits,
  paystackCheckoutUrl,
  pendingCreditRequests,
  purchasePath,
} from "./aiCredits";

export default function TmaAICredits({ quota, onRefresh }) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState("buy");
  const [count, setCount] = useState(20);
  const [quote, setQuote] = useState(null);
  const [summary, setSummary] = useState(null);
  const [requests, setRequests] = useState([]);
  const [purchase, setPurchase] = useState(null);
  const [checkoutUrl, setCheckoutUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const pending = useRef(false);
  const isAdmin = quota?.actor_type === "tenant_admin";
  const valid = Number.isSafeInteger(count) && count > 0;
  const exhausted = canRequestAICredits(quota);
  const refresh = async () => {
    const current = await onRefresh();
    if (current.actor_type === "teacher")
      setRequests(await pendingCreditRequests(api));
    else if (current.actor_type === "tenant_admin")
      setSummary(await api.get("/ai/admin/quota/summary"));
    return current;
  };
  const run = async (fn) => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await fn();
    } catch (e) {
      setError(
        e.message ||
          "Could not confirm this operation. Refresh before trying again.",
      );
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };
  useEffect(() => {
    if (!open) return;
    let active = true;
    onRefresh()
      .then(async (current) => {
        const [context, purchases] = await Promise.all([
          current.actor_type === "teacher"
            ? pendingCreditRequests(api)
            : api.get("/ai/admin/quota/summary"),
          api.get(`${purchasePath(current)}?status=pending&offset=0&limit=50`),
        ]);
        if (!active) return;
        if (current.actor_type === "teacher") setRequests(context);
        else setSummary(context);
        setPurchase(
          purchases.items.find(
            (p) =>
              current.actor_type === "teacher" ||
              p.initiated_by_admin_id === current.actor_id,
          ) || null,
        );
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [open, onRefresh]);
  const show = (next) => {
    setMode(next);
    setOpen(true);
    setError("");
    setMessage("");
  };
  const checkout = () => {
    if (pending.current) return;
    // Open synchronously on the user's click so payment preserves the question editor.
    const paymentTab = window.open("about:blank", "_blank");
    if (paymentTab) paymentTab.opener = null;
    run(async () => {
      try {
        const current = await onRefresh();
        const result = await api.post(`${purchasePath(current)}/checkout`, {
          credits: count,
        });
        const url = paystackCheckoutUrl(result.authorization_url);
        setPurchase(result.purchase);
        setCheckoutUrl(url);
        if (
          result.quote.credits !== quote.credits ||
          result.quote.amount_kobo !== quote.amount_kobo ||
          result.quote.currency !== quote.currency
        ) {
          paymentTab?.close();
          setQuote(result.quote);
          setMessage(
            "The price changed. Review the updated total, then open payment below.",
          );
          return;
        }
        if (paymentTab) paymentTab.location.replace(url);
        setMessage(
          "Complete payment on Paystack, then return here and check payment. Your question stays open in this tab.",
        );
      } catch (e) {
        paymentTab?.close();
        throw e;
      }
    });
  };
  return (
    <>
      <div className="flex flex-wrap items-center gap-2 pt-2">
        <Button
          variant="outline"
          size="xs"
          className="min-h-11"
          disabled={!quota}
          onClick={() => show("buy")}
        >
          Buy credits
        </Button>
        {exhausted && (
          <Button
            variant="outline"
            size="xs"
            className="min-h-11"
            onClick={() => show("request")}
          >
            Request more credits
          </Button>
        )}
        {isAdmin && (
          <Button
            variant="ghost"
            size="xs"
            className="min-h-11"
            onClick={() => show("allocate")}
          >
            Use school reserve
          </Button>
        )}
      </div>
      <Modal
        open={open}
        title="AI credits"
        onClose={() => !busy && setOpen(false)}
      >
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 rounded-xl border border-border bg-surface-muted p-4 text-sm">
            <div>
              <p className="text-text-muted">Available</p>
              <strong className="text-xl">
                {quota?.total_available_credits ?? "—"}
              </strong>
            </div>
            <div>
              <p className="text-text-muted">Weekly / extra</p>
              <strong>
                {quota?.weekly.available_credits ?? "—"} /{" "}
                {quota?.extra.available_credits ?? "—"}
              </strong>
            </div>
            {isAdmin && (
              <p className="col-span-2 text-text-muted">
                School reserve: {summary?.tenant_reserve_credits ?? "—"} credits
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant={mode === "buy" ? "primary" : "outline"}
              disabled={busy}
              onClick={() => setMode("buy")}
            >
              Buy credits
            </Button>
            {exhausted && (
              <Button
                variant={mode === "request" ? "primary" : "outline"}
                disabled={busy}
                onClick={() => setMode("request")}
              >
                Request from school
              </Button>
            )}
            {isAdmin && (
              <Button
                variant={mode === "allocate" ? "primary" : "outline"}
                disabled={busy}
                onClick={() => setMode("allocate")}
              >
                Use reserve
              </Button>
            )}
          </div>
          {error && (
            <p
              role="alert"
              className="rounded-xl border border-error/30 bg-error-soft p-3 text-sm text-error"
            >
              {error}
            </p>
          )}
          {message && (
            <p role="status" className="text-sm text-text-muted">
              {message}
            </p>
          )}
          <label className="grid gap-2 text-sm font-medium">
            Credits
            <input
              className="input-base"
              type="number"
              min={1}
              step={1}
              disabled={busy}
              value={count}
              onChange={(e) => {
                setCount(Number(e.target.value));
                setQuote(null);
                setCheckoutUrl("");
              }}
            />
          </label>
          {mode === "buy" && (
            <div className="space-y-4">
              <p className="text-sm text-text-muted">
                {isAdmin
                  ? "Purchases go to the school reserve. Allocate credits to your account after payment."
                  : "Purchased credits are added to your personal extra balance."}
              </p>
              {quote ? (
                <div className="rounded-xl border border-border p-4">
                  <p className="text-sm">{quote.credits} credits</p>
                  <p className="text-xl font-semibold">
                    {new Intl.NumberFormat("en-NG", {
                      style: "currency",
                      currency: quote.currency,
                    }).format(quote.amount_kobo / 100)}
                  </p>
                </div>
              ) : null}
              <Button
                disabled={busy || !valid}
                variant="outline"
                onClick={() =>
                  run(async () => {
                    const current = await onRefresh();
                    setQuote(
                      await api.post(`${purchasePath(current)}/quote`, {
                        credits: count,
                      }),
                    );
                  })
                }
              >
                Get price
              </Button>
              {quote && quote.credits === count && (
                <Button disabled={busy} onClick={checkout}>
                  Continue to Paystack
                </Button>
              )}
              {checkoutUrl && (
                <a
                  className="inline-flex min-h-11 items-center rounded-xl border border-border px-4 text-sm font-medium text-primary"
                  href={checkoutUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open payment
                </a>
              )}
            </div>
          )}
          {mode === "request" && (
            <div className="space-y-3">
              <p className="text-sm text-text-muted">
                Request extra credits from your school administrator when your
                available credits run out.
              </p>
              {requests.length > 0 ? (
                <p className="text-sm">
                  A request for{" "}
                  {requests.reduce((sum, r) => sum + r.requested_credits, 0)}{" "}
                  credits is already pending.
                </p>
              ) : (
                <Button
                  disabled={busy || !valid || !exhausted}
                  onClick={() =>
                    run(async () => {
                      const current = await onRefresh();
                      const pendingRequests = await pendingCreditRequests(api);
                      setRequests(pendingRequests);
                      if (
                        !canRequestAICredits(current) ||
                        pendingRequests.length
                      ) {
                        setMessage(
                          "Your balance or pending requests changed. Review the updated information.",
                        );
                        return;
                      }
                      try {
                        await api.post("/ai/quota/requests", {
                          credits: count,
                        });
                        setMessage(
                          "Credit request sent to your school administrator.",
                        );
                      } finally {
                        setRequests(await pendingCreditRequests(api));
                      }
                    })
                  }
                >
                  Send request
                </Button>
              )}
            </div>
          )}
          {mode === "allocate" && isAdmin && (
            <div className="space-y-3">
              <p className="text-sm text-text-muted">
                Move school reserve credits to your own AI balance.
              </p>
              <Button
                disabled={
                  busy ||
                  !valid ||
                  !summary ||
                  count > summary.tenant_reserve_credits
                }
                onClick={() =>
                  run(async () => {
                    const current = await onRefresh();
                    await api.post("/ai/admin/quota/allocations", {
                      recipient_actor_type: "tenant_admin",
                      recipient_actor_id: current.actor_id,
                      credits: count,
                    });
                    await refresh();
                    setMessage("Credits allocated to your account.");
                  })
                }
              >
                Allocate to my account
              </Button>
            </div>
          )}
          {purchase && (
            <div className="space-y-3 border-t border-border pt-4">
              <p className="text-sm text-text-muted">
                Have you completed your {purchase.credits}-credit payment?
              </p>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    const current = await onRefresh();
                    const result = await api.post(
                      `${purchasePath(current)}/${encodeURIComponent(purchase.reference)}/verify`,
                      {},
                    );
                    if (result.status !== "success") {
                      setMessage(
                        "Payment is not confirmed yet. Try again after completing checkout.",
                      );
                      return;
                    }
                    setPurchase(null);
                    setCheckoutUrl("");
                    await refresh();
                    setMessage(
                      isAdmin
                        ? "Payment confirmed. Credits are in the school reserve."
                        : "Payment confirmed. Your extra credits are available.",
                    );
                  })
                }
              >
                Check payment
              </Button>
            </div>
          )}
          <Button variant="ghost" disabled={busy} onClick={() => run(refresh)}>
            Refresh balance
          </Button>
        </div>
      </Modal>
    </>
  );
}
