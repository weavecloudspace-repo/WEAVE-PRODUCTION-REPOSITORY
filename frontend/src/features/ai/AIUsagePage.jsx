import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, BarChart3, Check, CreditCard, History, RefreshCw, Search, Users, Wallet, X } from "lucide-react";
import { Link } from "react-router-dom";
import Button from "../../components/ui/Button";
import Modal from "../../components/ui/Modal";
import { api, getErrorMessage } from "../../services/api";
import { useToast } from "../../hooks/useToast";
import AICreditPurchaseFlow from "./AICreditPurchaseFlow";
import { canRequestAICredits } from "../tma/aiCredits";
import "./ai-usage.css";

const PAGE_SIZE = 20;
const matchesTeacher = (query, ...values) => {
  const term = query.trim().toLocaleLowerCase();
  return !term || values.some((value) => String(value ?? "").toLocaleLowerCase().includes(term));
};
const number = (value) => Number(value || 0).toLocaleString("en-NG");
const money = (value) => new Intl.NumberFormat("en-NG", {
  style: "currency", currency: "NGN",
}).format(Number(value || 0) / 100);
const date = (value) => value ? new Date(value).toLocaleString() : "—";
const errorText = (error) => getErrorMessage(error, "Something went wrong. Please retry.");
const progress = (used, available) => {
  const total = Number(used || 0) + Number(available || 0);
  return total ? Math.min(100, Math.round(Number(used || 0) / total * 100)) : 0;
};

function Metric({ label, value, detail, icon: Icon }) {
  return <article className="ai-usage-metric">
    <span className="ai-usage-metric-icon"><Icon size={20} /></span>
    <span className="text-sm text-text-muted">{label}</span>
    <strong>{value}</strong>
    <span className="text-xs text-text-muted">{detail}</span>
  </article>;
}
function Status({ value }) {
  return <span className={`ai-usage-status ai-usage-status--${value || "unknown"}`}>
    {String(value || "unknown").replaceAll("_", " ")}
  </span>;
}
function Pager({ page, total, onChange }) {
  const pages = Math.ceil(total / PAGE_SIZE);
  if (pages <= 1) return null;
  return <div className="ai-usage-pager">
    <span>Page {page + 1} of {pages}</span>
    <div className="flex gap-2">
      <Button size="sm" variant="outline" disabled={page === 0} onClick={() => onChange(page - 1)}>Previous</Button>
      <Button size="sm" variant="outline" disabled={page + 1 >= pages} onClick={() => onChange(page + 1)}>Next</Button>
    </div>
  </div>;
}

export default function AIUsagePage({ role }) {
  const { showError, showSuccess } = useToast();
  const admin = role === "admin";
  const [tab, setTab] = useState("overview");
  const [staffSearch, setStaffSearch] = useState("");
  const [requestSearch, setRequestSearch] = useState("");
  const [staffQuery, setStaffQuery] = useState("");
  const [requestQuery, setRequestQuery] = useState("");
  const [staffPage, setStaffPage] = useState(0);
  const [requestPage, setRequestPage] = useState(0);
  const [staffLoading, setStaffLoading] = useState(false);
  const [requestLoading, setRequestLoading] = useState(false);
  const actorVersion = useRef(0);
  const requestVersion = useRef(0);
  const [page, setPage] = useState(0);
  useEffect(() => {
    const timer = window.setTimeout(() => setStaffQuery(staffSearch.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [staffSearch]);
  useEffect(() => {
    const timer = window.setTimeout(() => setRequestQuery(requestSearch.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [requestSearch]);
  const [data, setData] = useState({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [purchaseOpen, setPurchaseOpen] = useState(false);
  const [action, setAction] = useState(null);
  const [credits, setCredits] = useState(20);
  const [note, setNote] = useState("");
  const version = useRef(0);
  const activeRequest = useRef(false);
  const lastLoadError = useRef("");
  const loadStaff = useCallback(async () => {
    if (!admin) return;
    const current = ++actorVersion.current;
    setStaffLoading(true);
    try {
      const params = new URLSearchParams({ offset: String(staffPage * PAGE_SIZE), limit: String(PAGE_SIZE) });
      if (staffQuery) params.set("search", staffQuery);
      const result = await api.get(`/ai/admin/quota/actors?${params}`);
      if (actorVersion.current === current) setData((previous) => ({ ...previous, actors: result }));
    } catch (error) {
      if (actorVersion.current === current) showError(`Staff usage: ${errorText(error)}`);
    } finally {
      if (actorVersion.current === current) setStaffLoading(false);
    }
  }, [admin, staffPage, staffQuery, showError]);

  const loadCreditRequests = useCallback(async () => {
    if (!admin) return;
    const current = ++requestVersion.current;
    setRequestLoading(true);
    try {
      const params = new URLSearchParams({ offset: String(requestPage * PAGE_SIZE), limit: String(PAGE_SIZE) });
      if (requestQuery) params.set("search", requestQuery);
      const result = await api.get(`/ai/admin/quota/requests?${params}`);
      if (requestVersion.current === current) setData((previous) => ({ ...previous, requests: result }));
    } catch (error) {
      if (requestVersion.current === current) showError(`Credit requests: ${errorText(error)}`);
    } finally {
      if (requestVersion.current === current) setRequestLoading(false);
    }
  }, [admin, requestPage, requestQuery, showError]);

  useEffect(() => {
    void loadStaff();
    return () => { actorVersion.current += 1; };
  }, [loadStaff]);
  useEffect(() => {
    void loadCreditRequests();
    return () => { requestVersion.current += 1; };
  }, [loadCreditRequests]);

  const reload = useCallback(async ({ silent = false } = {}) => {
    const current = ++version.current;
    if (!silent) setLoading(true);
    const requests = {
      quota: "/ai/quota",
      purchases: admin ? `/ai/admin/quota/purchases?offset=${page * PAGE_SIZE}&limit=${PAGE_SIZE}`
        : `/ai/teacher/purchases?offset=${page * PAGE_SIZE}&limit=${PAGE_SIZE}`,
      ...(admin ? {
        summary: "/ai/admin/quota/summary",
        allocations: "/ai/admin/quota/allocations?offset=0&limit=50",
      } : { requests: "/ai/quota/requests?offset=0&limit=100" }),
    };
    const results = await Promise.allSettled(Object.values(requests).map((path) => api.get(path)));
    if (current !== version.current) return;
    const next = {};
    const failed = [];
    Object.keys(requests).forEach((key, i) => {
      if (results[i].status === "fulfilled") next[key] = results[i].value;
      else {
        const message = errorText(results[i].reason);
        const label = { quota: "AI balance", purchases: "Purchases", summary: "School reserve", actors: "Staff usage", requests: "Credit requests", allocations: "Allocations" }[key];
        if (message) failed.push(`${label}: ${message}`);
      }
    });
    setData((previous) => ({ ...previous, ...next }));
    const failure = failed.join(" · ");
    if (failure && (!silent || failure !== lastLoadError.current)) showError(failure);
    lastLoadError.current = failure;
    setLoading(false);
  }, [admin, page, showError]);
  useEffect(() => {
    void reload();
    const refresh = () => void reload({ silent: true });
    window.addEventListener("focus", refresh);
    return () => {
      version.current += 1;
      window.removeEventListener("focus", refresh);
    };
  }, [reload]);
  const refreshAll = () => Promise.allSettled([
    reload({ silent: true }),
    ...(admin ? [loadStaff(), loadCreditRequests()] : []),
  ]);
  const act = async (fn, success) => {
    if (activeRequest.current) return;
    activeRequest.current = true;
    setBusy(true);
    try {
      await fn();
      setAction(null);
      showSuccess(success);
      await refreshAll();
    } catch (failure) {
      showError(errorText(failure));
      await refreshAll();
    } finally {
      setBusy(false);
      activeRequest.current = false;
    }
  };
  const openAction = (kind, item = null) => {
    setAction({ kind, item });
    setNote("");
    setCredits(kind === "approve" ? item?.requested_credits || 20 : 20);
  };
  const submitAction = () => {
    if (!action) return;
    if (action.kind === "request") return act(
      () => api.post("/ai/quota/requests", { credits: Number(credits) }),
      "Credit request sent to your administrator.",
    );
    if (action.kind === "approve") return act(
      () => api.post(`/ai/admin/quota/requests/${action.item.id}/approve`,
        { approved_credits: Number(credits), note: note.trim() || null }),
      "Credits allocated to the teacher.",
    );
    if (action.kind === "reject") return act(
      () => api.post(`/ai/admin/quota/requests/${action.item.id}/reject`,
        { note: note.trim() || null }),
      "Request rejected.",
    );
    if (action.kind === "allocate") return act(
      () => api.post("/ai/admin/quota/allocations", {
        recipient_actor_type: action.item.actor_type,
        recipient_actor_id: action.item.actor_id,
        credits: Number(credits),
      }),
      "Credits allocated successfully.",
    );
  };
  const quota = data.quota;
  const summary = data.summary;
  const actors = data.actors?.items || [];
  const requests = data.requests?.items || [];
  const pending = requests.filter((item) => item.status === "pending");
  const filteredActors = actors;
  const filteredRequests = requests;
  const weekly = quota?.weekly;
  const staffUsage = data.actors?.weekly_used_credits_total ?? null;
  const tabs = admin
    ? [{ id: "overview", label: "School usage" }, { id: "requests", label: `Requests${pending.length ? ` (${pending.length})` : ""}` }, { id: "transactions", label: "Transactions" }]
    : [{ id: "overview", label: "My credits" }, { id: "transactions", label: "Transactions" }];
  return <main className="ai-usage-page">
    <header className="ai-usage-top">
      <div>
        <Link to={`/${role}/dashboard`} className="ai-usage-back"><ArrowLeft size={16} /> Dashboard</Link>
        <div className="ai-usage-title"><BarChart3 size={23} /><h1>AI Usage</h1></div>
        <p className="text-sm text-text-muted">
          {admin ? "Monitor school AI credits, review teachers, and manage purchases."
            : "Your AI balance, weekly usage, credit requests, and purchases."}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={loading || busy} onClick={() => { void refreshAll(); }}><RefreshCw size={16} /> Refresh</Button>
        <Button onClick={() => setPurchaseOpen(true)}><CreditCard size={16} /> Buy credits</Button>
      </div>
    </header>
    <section className="ai-usage-metrics" aria-label="AI credit summary">
      <Metric icon={Wallet} label={admin ? "School reserve" : "Available credits"}
        value={data.summary ? number(summary.tenant_reserve_credits) : admin ? "—" : quota ? number(quota.total_available_credits) : "—"}
        detail={admin ? "Credits ready to allocate" : "Weekly and personal credits combined"} />
      <Metric icon={BarChart3} label={admin ? "Staff usage this week" : "Used this week"}
        value={admin ? (staffUsage !== null ? number(staffUsage) : "—") : weekly ? number(weekly.used_credits) : "—"}
        detail={admin ? "Weekly credits spent across all staff" : "Weekly free allocation spent"} />
      <Metric icon={Users} label={admin ? "Pending requests" : "Personal top-ups"}
        value={admin ? (summary ? number(summary.pending_request_count) : "—") : quota ? number(quota.extra?.available_credits) : "—"}
        detail={admin ? "Awaiting administrator review" : "Purchased or allocated extra credits"} />
      <Metric icon={History} label={admin ? "AI staff accounts" : "Weekly credits available"}
        value={admin ? (summary ? number(summary.quota_actor_count) : "—") : quota ? number(weekly?.available_credits) : "—"}
        detail={admin ? "School members with AI accounts" : "Your own weekly balance"} />
    </section>
    <nav className="ai-usage-tabs" aria-label="AI Usage sections">
      {tabs.map((item) => <button key={item.id} type="button" aria-current={tab === item.id ? "page" : undefined}
        onClick={() => { setTab(item.id); setPage(0); }}>{item.label}</button>)}
    </nav>
    {loading ? <div role="status" className="ai-usage-panel">Loading AI usage…</div> : null}
    {!loading && tab === "overview" && <div className="ai-usage-columns">
      <section className="ai-usage-panel">
        <div className="ai-usage-panel-heading">
          <div><h2>{admin ? "Teacher credit usage" : "Your weekly allocation"}</h2>
            <p>{admin ? "Personal usage and balances across the school." : "The same credits are available in WEAVE CBT and TMA."}</p></div>
          {!admin && canRequestAICredits(quota) &&
            <Button variant="outline" size="sm" onClick={() => openAction("request")}>Request credits</Button>}
        </div>
        {admin ? <>
          <label className="ai-usage-search"><Search size={16} aria-hidden="true" />
            <input type="search" aria-label="Search staff AI credits" placeholder="Search staff by name or email"
              value={staffSearch} onChange={(event) => { setStaffPage(0); setStaffSearch(event.target.value); }} />
          </label>
          <div className="ai-usage-table-wrap"><table className="ai-usage-table"><thead><tr>
            <th>Staff member</th><th>Used this week</th><th>Available</th><th>Action</th>
          </tr></thead><tbody>{filteredActors.map((item) => <tr key={item.quota_account_id}>
            <td><strong>{item.display_name}</strong><small>{item.email || item.actor_type}</small></td>
            <td>{number(item.weekly_used_credits)}</td><td>{number(item.total_available_credits)}</td>
            <td><Button variant="outline" size="sm" disabled={busy || summary?.tenant_reserve_credits === 0}
              onClick={() => openAction("allocate", item)}>Allocate</Button></td>
          </tr>)}</tbody></table></div>
          {staffLoading && <p className="ai-usage-empty">Searching staff…</p>}
          {!staffLoading && !actors.length && <p className="ai-usage-empty">{staffQuery ? "No staff match this search." : "No AI accounts found yet."}</p>}
          <Pager page={staffPage} total={data.actors?.total || 0} onChange={setStaffPage} />
        </> : <>
          <div className="ai-usage-weekly">
            <div className="flex justify-between"><span>Weekly usage</span><strong>{number(weekly?.used_credits)} used</strong></div>
            <progress value={progress(weekly?.used_credits, weekly?.available_credits)} max="100" aria-label="Weekly AI usage" />
            <div className="flex flex-wrap justify-between gap-3 text-xs text-text-muted">
              <span>{number(weekly?.available_credits)} free credits remaining</span>
              <span>{number(quota?.extra?.available_credits)} extra credits</span>
            </div>
          </div>
          <div className="ai-usage-personal-actions">
            <Button variant="outline" onClick={() => setTab("transactions")}>View purchases <ArrowRight size={16} /></Button>
            {pending.length ? <span className="text-sm text-text-muted">{pending.length} pending request(s)</span> : null}
          </div>
        </>}
      </section>
      <section className="ai-usage-panel">
        <div className="ai-usage-panel-heading"><div><h2>{admin ? "Recent allocations" : "Recent credit requests"}</h2>
          <p>{admin ? "Credits assigned from the school reserve." : "Requests sent to your school administrator."}</p></div></div>
        {admin ? (data.allocations?.items || []).slice(0, 8).map((item) => (
          <div className="ai-usage-feed" key={item.id}>
            <div><strong>{item.recipient_name || item.recipient_email || "Staff member"}</strong>
              <p>{date(item.created_at)}</p></div><b>+{number(item.credits)}</b>
          </div>
        )) : (data.requests?.items || []).slice(0, 8).map((item) => (
          <div className="ai-usage-feed" key={item.id}>
            <div><strong>{number(item.requested_credits)} requested</strong>
              <p>{date(item.created_at)}</p></div><Status value={item.status} />
          </div>
        ))}
        {!(admin ? data.allocations?.items : data.requests?.items)?.length &&
          <p className="ai-usage-empty">No activity yet.</p>}
      </section>
    </div>}
    {!loading && tab === "requests" && admin && <section className="ai-usage-panel">
      <div className="ai-usage-panel-heading"><div><h2>Teacher credit requests</h2>
        <p>Review requests before transferring credits from your reserve.</p></div></div>
      <label className="ai-usage-search"><Search size={16} aria-hidden="true" />
        <input type="search" aria-label="Search teacher credit requests" placeholder="Search requests by teacher or email"
          value={requestSearch} onChange={(event) => { setRequestPage(0); setRequestSearch(event.target.value); }} />
      </label>
      <div className="ai-usage-table-wrap"><table className="ai-usage-table"><thead>
        <tr><th>Teacher</th><th>Requested</th><th>Created</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>{filteredRequests.map((item) => <tr key={item.id}>
          <td>{item.requester_name || item.requester_email || "Teacher"}</td>
          <td>{number(item.requested_credits)}</td><td>{date(item.created_at)}</td>
          <td><Status value={item.status} /></td><td>{item.status === "pending" &&
            <div className="flex gap-2"><Button size="sm" disabled={busy} onClick={() => openAction("approve", item)}>
              <Check size={14} /> Approve</Button>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => openAction("reject", item)}>
                <X size={14} /> Reject</Button></div>}</td>
        </tr>)}</tbody></table></div>
      {requestLoading && <p className="ai-usage-empty">Searching requests…</p>}
      {!requestLoading && !requests.length && <p className="ai-usage-empty">{requestQuery ? "No requests match this search." : "No teacher requests found."}</p>}
      <Pager page={requestPage} total={data.requests?.total || 0} onChange={setRequestPage} />
    </section>}
    {!loading && tab === "transactions" && <section className="ai-usage-panel">
      <div className="ai-usage-panel-heading"><div><h2>Payment history</h2>
        <p>Verified Paystack purchases credit {admin ? "the school reserve" : "your personal balance"}.</p></div></div>
      <div className="ai-usage-table-wrap"><table className="ai-usage-table"><thead>
        <tr><th>Date</th><th>Credits</th><th>Amount</th><th>Reference</th><th>Status</th><th>Action</th></tr></thead>
        <tbody>{(data.purchases?.items || []).map((item) => <tr key={item.id}>
          <td>{date(item.created_at)}</td><td>{number(item.credits)}</td>
          <td>{money(item.amount_kobo)}</td><td className="ai-usage-reference">{item.reference}</td>
          <td><Status value={item.status} /></td><td>{item.status === "pending" &&
            <Button variant="outline" size="sm" disabled={busy}
              onClick={() => act(async () => {
                const path = admin ? "/ai/admin/quota/purchases" : "/ai/teacher/purchases";
                await api.post(`${path}/${encodeURIComponent(item.reference)}/verify`, {});
              }, "Purchase status refreshed.")}>Verify</Button>}</td>
        </tr>)}</tbody></table></div>
      {!data.purchases?.items?.length && <p className="ai-usage-empty">No purchases yet.</p>}
      <Pager page={page} total={data.purchases?.total || 0} onChange={setPage} />
    </section>}
    <AICreditPurchaseFlow role={role} open={purchaseOpen}
      onClose={() => setPurchaseOpen(false)} onVerified={() => { void refreshAll(); }} />
    <Modal open={Boolean(action)} title={action?.kind === "request" ? "Request AI credits" :
      action?.kind === "reject" ? "Reject request" : action?.kind === "approve" ? "Approve request" : "Allocate credits"}
      onClose={() => !busy && setAction(null)} className="ai-credit-compact-modal">
      <div className="space-y-4">
        {action?.item && <p className="text-sm text-text-muted">
          {action.item.requester_name || action.item.display_name || action.item.requester_email || "Staff member"}
        </p>}
        {action?.kind !== "reject" && <label className="grid gap-2 text-sm font-medium">Credits
          <input type="number" className="input-base" min="1" step="1" value={credits} disabled={busy}
            onChange={(event) => setCredits(event.target.value)} /></label>}
        {(action?.kind === "approve" || action?.kind === "reject") && <label className="grid gap-2 text-sm font-medium">
          Note (optional)<textarea className="input-base" rows={2} maxLength={2000} value={note} disabled={busy}
            onChange={(event) => setNote(event.target.value)} /></label>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" disabled={busy} onClick={() => setAction(null)}>Cancel</Button>
          <Button disabled={busy || (action?.kind !== "reject" &&
            (!Number.isSafeInteger(Number(credits)) || Number(credits) <= 0))}
            onClick={submitAction}>{busy ? "Saving…" : "Confirm"}</Button>
        </div>
      </div>
    </Modal>
  </main>;
}
