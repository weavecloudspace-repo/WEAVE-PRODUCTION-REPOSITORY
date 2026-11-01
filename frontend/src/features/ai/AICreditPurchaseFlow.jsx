import { useRef, useState } from "react";
import { ArrowRight, CreditCard, ShieldCheck, Wallet } from "lucide-react";
import Button from "../../components/ui/Button";
import Modal from "../../components/ui/Modal";
import { api } from "../../services/api";
import { paystackCheckoutUrl } from "../tma/aiCredits";

const formatMoney = (kobo, currency = "NGN") =>
  new Intl.NumberFormat("en-NG", { style: "currency", currency }).format(
    Number(kobo || 0) / 100,
  );

/**
 * CBT-style compact two-step purchase. Pricing and ownership remain server-side.
 * The second dialog is a checkout confirmation, never a card-data collector.
 */
export default function AICreditPurchaseFlow({ role, open, onClose, onVerified }) {
  const [step, setStep] = useState("quota");
  const [credits, setCredits] = useState(20);
  const [quote, setQuote] = useState(null);
  const [purchase, setPurchase] = useState(null);
  const [checkoutUrl, setCheckoutUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const locked = useRef(false);
  const path = role === "admin" ? "/ai/admin/quota/purchases" : "/ai/teacher/purchases";
  const valid = Number.isSafeInteger(Number(credits)) && Number(credits) > 0;

  const run = async (fn) => {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (failure) {
      setError(failure.userMessage || failure.message || "Could not complete this action.");
    } finally {
      locked.current = false;
      setBusy(false);
    }
  };
  const reset = () => {
    if (busy) return;
    setStep("quota");
    setQuote(null);
    setPurchase(null);
    setCheckoutUrl("");
    setError("");
    onClose();
  };
  const getQuote = () => run(async () => {
    if (!valid) return;
    const result = await api.post(`${path}/quote`, { credits: Number(credits) });
    if (Number(result.credits) !== Number(credits)) {
      throw new Error("The quoted credit amount is different. Review it before payment.");
    }
    setQuote(result);
    setStep("checkout");
  });
  const beginPayment = () => {
    // Open immediately while user gesture is active to avoid popup blockers.
    const tab = window.open("about:blank", "_blank");
    if (tab) tab.opener = null;
    run(async () => {
      try {
        const result = await api.post(`${path}/checkout`, { credits: Number(credits) });
        setPurchase(result.purchase);
        const url = paystackCheckoutUrl(result.authorization_url);
        setCheckoutUrl(url);
        if (result.quote.amount_kobo !== quote.amount_kobo ||
            result.quote.credits !== quote.credits ||
            result.quote.currency !== quote.currency) {
          tab?.close();
          setQuote(result.quote);
          setError("The price changed. Please review the updated amount before opening checkout.");
          return;
        }
        if (tab) tab.location.replace(url);
      } catch (failure) {
        tab?.close();
        throw failure;
      }
    });
  };
  const verify = () => run(async () => {
    if (!purchase?.reference) return;
    const result = await api.post(
      `${path}/${encodeURIComponent(purchase.reference)}/verify`, {},
    );
    if (result.status === "success") {
      await onVerified?.();
      reset();
      return;
    }
    setError(`Payment is ${result.status}. Credits will appear only after verification.`);
  });

  return (
    <Modal
      open={open}
      title={step === "quota" ? "Buy AI credits" : "Confirm checkout"}
      description={step === "quota"
        ? "Choose how many credits you need."
        : "Review your purchase before opening secure payment."}
      className="ai-credit-compact-modal"
      onClose={reset}
    >
      <div className="space-y-4">
        <div className="flex items-center gap-3 rounded-xl border border-border bg-surface-muted/30 p-3">
          <span className="rounded-lg bg-primary/10 p-2 text-primary">
            {step === "quota" ? <Wallet size={20} /> : <ShieldCheck size={20} />}
          </span>
          <div className="min-w-0">
            <p className="font-semibold text-text">
              {role === "admin" ? "School AI reserve" : "Your personal AI wallet"}
            </p>
            <p className="text-xs text-text-muted">
              {role === "admin"
                ? "Credits are added to the school reserve for allocation."
                : "Purchased credits are added directly to your own balance."}
            </p>
          </div>
        </div>
        {step === "quota" ? (
          <>
            <label className="grid gap-1.5 text-sm font-medium" htmlFor="ai-credit-quantity">
              Number of credits
              <input id="ai-credit-quantity" type="number" min="1" max="1000000"
                step="1" className="input-base" value={credits} disabled={busy}
                onChange={(event) => {
                  setCredits(event.target.value);
                  setQuote(null);
                  setPurchase(null);
                }} />
            </label>
            <div className="flex justify-between gap-2">
              {[20, 50, 100].map((amount) => (
                <Button key={amount} size="sm" variant={Number(credits) === amount ? "primary" : "outline"}
                  onClick={() => setCredits(amount)} disabled={busy}>{amount} credits</Button>
              ))}
            </div>
            <Button className="w-full" disabled={!valid || busy} onClick={getQuote}>
              {busy ? "Checking price…" : "Review price"} <ArrowRight size={16} />
            </Button>
          </>
        ) : (
          <>
            <div className="rounded-xl border border-border p-4">
              <p className="text-sm text-text-muted">{quote?.credits} AI credits</p>
              <strong className="text-2xl font-bold text-text">
                {formatMoney(quote?.amount_kobo, quote?.currency)}
              </strong>
              <p className="mt-1 text-xs text-text-muted">
                Exact amount confirmed by WEAVE before Paystack checkout.
              </p>
            </div>
            {purchase ? (
              <div className="space-y-2 rounded-xl bg-surface-muted/30 p-3 text-xs">
                <p className="break-all text-text-muted">Reference: {purchase.reference}</p>
                <p className="text-text-muted">
                  Finish payment in the secure tab, then check payment status here.
                </p>
                {checkoutUrl && <a className="font-semibold text-primary underline"
                  href={checkoutUrl} target="_blank" rel="noopener noreferrer">Reopen Paystack checkout</a>}
              </div>
            ) : null}
            <div className="flex flex-wrap gap-2">
              {!purchase && <Button variant="outline" disabled={busy}
                onClick={() => setStep("quota")}>Back</Button>}
              {!purchase ? (
                <Button disabled={busy} className="flex-1" onClick={beginPayment}>
                  <CreditCard size={16} /> {busy ? "Opening…" : "Pay securely"}
                </Button>
              ) : (
                <Button className="flex-1" disabled={busy} onClick={verify}>
                  {busy ? "Verifying…" : "Check payment"}
                </Button>
              )}
            </div>
          </>
        )}
        {error && <p role="alert" className="rounded-xl border border-error/30 bg-error-soft p-3 text-sm text-error">{error}</p>}
        <p className="text-xs leading-5 text-text-muted">
          Payments are handled by Paystack. WEAVE never collects card details here.
        </p>
      </div>
    </Modal>
  );
}
