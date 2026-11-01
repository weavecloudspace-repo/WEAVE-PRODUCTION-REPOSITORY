import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, BarChart3, Wallet } from "lucide-react";
import { api } from "../../services/api";
import "./ai-usage.css";

/** Small CBT-inspired AI balance summary, independent from dashboard analytics. */
export default function AIUsageDashboardCard({ role }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const result = await Promise.allSettled([
          api.get("/ai/quota"),
          ...(role === "admin" ? [api.get("/ai/admin/quota/summary")] : []),
        ]);
        if (!alive) return;
        if (result[0].status !== "fulfilled") throw result[0].reason;
        setData({
          quota: result[0].value,
          summary: result[1]?.status === "fulfilled" ? result[1].value : null,
        });
        setError("");
      } catch (failure) {
        if (alive) setError(failure.userMessage || failure.message || "AI credits are unavailable.");
      }
    };
    void load();
    window.addEventListener("focus", load);
    return () => {
      alive = false;
      window.removeEventListener("focus", load);
    };
  }, [role]);
  const value = role === "admin" ? data?.summary?.tenant_reserve_credits
    : data?.quota?.total_available_credits;
  return <section className="ai-dashboard-card" aria-label="AI credit usage">
    <div className="ai-dashboard-card-heading">
      <span className="ai-dashboard-card-icon"><BarChart3 size={20} /></span>
      <div><h2>AI Usage</h2><p>{role === "admin" ? "School credit reserve and staff usage" : "Your AI question-generation credits"}</p></div>
    </div>
    <div className="ai-dashboard-card-balance">
      <Wallet size={19} />
      <strong>{value == null ? "—" : Number(value).toLocaleString("en-NG")}</strong>
      <span>{role === "admin" ? "school credits available" : "credits available"}</span>
    </div>
    {error ? <p className="text-xs text-error" role="status">{error}</p> : null}
    <div className="ai-dashboard-card-meta">
      <span>{role === "admin" ? `${data?.summary?.pending_request_count ?? "—"} pending requests`
        : `${data?.quota?.weekly?.used_credits ?? "—"} used this week`}</span>
      <Link to={`/${role}/ai-usage`}>Open AI Usage <ArrowRight size={15} /></Link>
    </div>
  </section>;
}
