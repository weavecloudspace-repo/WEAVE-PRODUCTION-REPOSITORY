import { HelpCircle, ShieldCheck } from "lucide-react";
import { useEffect } from "react";
import { Link } from "react-router-dom";

import WeaveIcon from "../../components/brand/WeaveIcon";
import Navbar from "../../components/layout/Navbar";
import PublicPricingCard from "../../components/subscriptions/PublicPricingCard";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import {
  LANDING_PRICING_PLANS,
  formatLimitValue,
} from "../../features/subscriptions/subscriptionConfig";
import { usePublicPricingCatalogue } from "../../features/subscriptions/usePublicPricingCatalogue";

const comparisonRows = [
  ["Students", (plan) => formatLimitValue(plan.limits.students)],
  ["Teachers", (plan) => formatLimitValue(plan.limits.teachers)],
  ["Parents", (plan) => formatLimitValue(plan.limits.parents)],
  ["Local CBT installation", (plan) => Number(plan.limits.cbt_servers || 0) > 0 ? "Included" : "—"],
  [
    "Bulk import",
    (plan) =>
      plan.features.some((feature) => /bulk import/i.test(feature))
        ? "Included"
        : "—",
  ],
  [
    "Advanced analytics",
    (plan) =>
      plan.features.some((feature) => /advanced analytics/i.test(feature))
        ? "Included"
        : "—",
  ],
  [
    "School branding",
    (plan) =>
      plan.features.some((feature) => /branding/i.test(feature))
        ? "Included"
        : "—",
  ],
  [
    "Support",
    (plan) => (plan.planCode === "enterprise" ? "Priority" : "Standard"),
  ],
];

const faqs = [
  [
    "Can I use Weave for free?",
    "Yes. Free is a permanent Weave plan with core school workflows and deliberately limited capacity. There is no trial countdown.",
  ],
  [
    "When do paid plans charge?",
    "A paid plan is chosen for an academic term when that term is ready to open. Weave does not charge during registration or prepay future terms.",
  ],
  [
    "Can I upgrade during a term?",
    "Yes. Upgrades charge only the difference between the target plan price and successful payments already made for that same term.",
  ],
  [
    "Can I choose a lower plan later?",
    "Yes. A lower plan is available whenever the school's active operational usage fits its limits. Historical records do not need to be deleted.",
  ],
];

function PricingPage() {
  const pricingReady = usePublicPricingCatalogue();
  const paidPlans = LANDING_PRICING_PLANS.filter(
    (plan) => plan.planCode !== "free",
  );
  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, []);

  return (
    <div className="min-h-screen overflow-x-hidden bg-background text-text">
      <Navbar />
      <main>
        <section className="relative overflow-hidden border-b border-border bg-slate-950 text-white">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(37,99,235,0.24),transparent_34%),radial-gradient(circle_at_top_right,rgba(168,85,247,0.2),transparent_32%),linear-gradient(180deg,rgba(15,23,42,1),rgba(15,23,42,0.94))]"
          />
          <div className="section-container relative py-16 sm:py-20 lg:py-24">
            <div className="grid gap-8 lg:grid-cols-[minmax(0,1.1fr)_minmax(300px,0.9fr)] lg:items-center">
              <div>
                <Badge variant="primary">Pricing</Badge>
                <h1 className="mt-5 max-w-4xl text-balance text-4xl font-semibold leading-tight tracking-tight text-white sm:text-6xl">
                  Start free. Pay for more when a term needs it.
                </h1>
                <p className="mt-5 max-w-2xl text-base leading-7 text-slate-300 sm:text-lg">
                  Every school can use Weave Free permanently. Paid plans add
                  higher capacity and premium capabilities for one academic term
                  at a time.
                </p>
                <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                  <a href="#compare" className="w-full sm:w-auto">
                    <Button size="large" className="w-full sm:w-auto">
                      Compare plans
                    </Button>
                  </a>
                  <Link to="/register" className="w-full sm:w-auto">
                    <Button
                      variant="outline"
                      size="large"
                      className="w-full border-white/15 bg-white/10 text-white hover:bg-white/15"
                    >
                      Get started
                    </Button>
                  </Link>
                </div>
              </div>

              <Card className="border-white/10 bg-white/10 p-5 text-white backdrop-blur-xl">
                <div className="flex items-center gap-4">
                  <WeaveIcon className="h-20 w-20 shrink-0" decorative />
                  <div className="min-w-0">
                    <h2 className="text-xl font-semibold text-white">
                      No payment during signup.
                    </h2>
                    <p className="mt-3 text-sm leading-6 text-slate-300">
                      Register, configure the school and use Free within its
                      limits. When an academic term is ready to open, continue
                      with Free or choose a paid term plan.
                    </p>
                  </div>
                </div>
                <div className="mt-5 grid gap-3 sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3">
                  {[
                    "Permanent Free",
                    "Per-term paid plans",
                    "No prepayment",
                  ].map((item) => (
                    <div
                      key={item}
                      className="rounded-2xl border border-white/10 bg-white/10 px-4 py-3 text-sm font-semibold"
                    >
                      {item}
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          </div>
        </section>

        <section id="compare" className="border-y border-border bg-surface">
          <div className="section-container py-16">
            <div className="mx-auto max-w-3xl text-center">
              <p className="text-sm font-bold uppercase tracking-wide text-primary">
                Compare
              </p>
              <h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-5xl">
                Choose capacity that fits your school.
              </h2>
              <p className="mt-4 text-sm leading-6 text-text-muted">
                These are plan limits and capabilities. Clicking Get started
                only creates your school account; it never begins payment.
              </p>
            </div>

            <div className="mx-auto mt-12 grid max-w-6xl items-stretch gap-6 md:grid-cols-2 xl:grid-cols-3">
              {paidPlans.map((plan) => (
                <PublicPricingCard
                  key={plan.planCode}
                  plan={plan}
                  selected={plan.highlighted}
                  pricingReady={pricingReady}
                />
              ))}
            </div>

            <div className="mt-10 overflow-hidden rounded-[1.75rem] border border-border bg-background shadow-soft-card">
              <div className="hidden min-w-[760px] grid-cols-[1.2fr_repeat(3,1fr)] border-b border-border bg-surface-muted/30 px-5 py-4 text-sm font-semibold md:grid">
                <span>Feature</span>
                {paidPlans.map((plan) => (
                  <span key={plan.planCode}>{plan.name}</span>
                ))}
              </div>
              <div className="divide-y divide-border">
                {comparisonRows.map(([label, resolver]) => (
                  <div
                    key={label}
                    className="grid gap-3 px-5 py-4 md:min-w-[760px] md:grid-cols-[1.2fr_repeat(3,1fr)] md:items-center"
                  >
                    <p className="text-sm font-semibold text-text">{label}</p>
                    {paidPlans.map((plan) => (
                      <div
                        key={`${label}-${plan.planCode}`}
                        className="flex items-center justify-between rounded-xl bg-surface-muted/30 px-3 py-2 text-sm md:block md:bg-transparent md:px-0 md:py-0"
                      >
                        <span className="text-xs font-semibold text-text-muted md:hidden">
                          {plan.name}
                        </span>
                        <span>
                          {pricingReady ? resolver(plan) : "Loading pricing..."}
                        </span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
              <p className="px-5 py-4 text-sm leading-6 text-text-muted">
                WEAVE CBT V1 is designed for one school-hosted examination server. Schools can scale capacity by upgrading that server\u0027s hardware; independent CBT installations do not share examination data.
              </p>
            </div>
          </div>
        </section>

        <section className="section-container py-16">
          <div className="grid gap-5 lg:grid-cols-[0.85fr_1.15fr] lg:items-start">
            <div>
              <HelpCircle className="h-8 w-8 text-primary" />
              <h2 className="mt-4 text-3xl font-semibold tracking-tight">
                Common questions
              </h2>
              <p className="mt-3 text-sm leading-6 text-text-muted">
                Plan decisions are tied to real school usage and the academic
                term being operated.
              </p>
            </div>
            <div className="grid gap-3">
              {faqs.map(([question, answer]) => (
                <Card key={question} className="p-5">
                  <h3 className="font-semibold">{question}</h3>
                  <p className="mt-2 text-sm leading-6 text-text-muted">
                    {answer}
                  </p>
                </Card>
              ))}
            </div>
          </div>
        </section>

        <section className="section-container pb-16">
          <div className="rounded-[2rem] border border-border bg-slate-950 px-6 py-12 text-center text-white shadow-premium sm:px-10">
            <ShieldCheck className="mx-auto h-10 w-10 text-primary-soft" />
            <h2 className="mt-5 text-3xl font-semibold tracking-tight text-white sm:text-4xl">
              Start with Free. Upgrade when your school needs more.
            </h2>
            <p className="mx-auto mt-4 max-w-2xl text-sm leading-6 text-slate-300">
              Registration never charges you. Paid checkout only appears inside
              the school workspace when an operational term needs a paid plan or
              an existing term is upgraded.
            </p>
            <Link to="/register" className="mt-8 inline-flex">
              <Button size="large">Get started</Button>
            </Link>
          </div>
        </section>
      </main>
    </div>
  );
}

export default PricingPage;
