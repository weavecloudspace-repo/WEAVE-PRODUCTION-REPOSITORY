import {
  BarChart3,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  GraduationCap,
  Palette,
  ShieldCheck,
  Users,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import previewImage from "../../assets/images/academic-workspace-preview.png";
import Navbar from "../../components/layout/Navbar";
import PublicPricingCard from "../../components/subscriptions/PublicPricingCard";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import { LANDING_PRICING_PLANS } from "../../features/subscriptions/subscriptionConfig";
import { usePublicPricingCatalogue } from "../../features/subscriptions/usePublicPricingCatalogue";

const features = [
  {
    title: "Student Management",
    description:
      "Keep admissions, student records, class placement, guardian links, and academic status organised in one reliable workspace.",
    icon: GraduationCap,
  },
  {
    title: "Teacher Management",
    description:
      "Manage teacher profiles, subject responsibilities, class assignments, and account verification with clear administrative control.",
    icon: Users,
  },
  {
    title: "Results and Report Cards",
    description:
      "Record scores, manage result workflows, and prepare polished report cards without disconnected spreadsheets.",
    icon: BookOpen,
  },
  {
    title: "Academic Lifecycle",
    description:
      "Structure sessions, terms, calendars, classes, subjects, and student progression through guided school-wide workflows.",
    icon: ShieldCheck,
  },
  {
    title: "Operational Insights",
    description:
      "See enrollment, academic, usage, and plan information from focused dashboards built for everyday decisions.",
    icon: BarChart3,
  },
  {
    title: "School Branding",
    description:
      "Carry your school identity across the workspace with coordinated colours and logo support on eligible plans.",
    icon: Palette,
  },
];

const benefits = [
  "Give administrators, teachers, students, and parents focused workspaces built around their actual responsibilities.",
  "Move from student setup and class assignment to results, report cards, parent access, and school announcements in one connected system.",
  "Keep school operations accessible across phones, tablets, and desktops without sacrificing structure or role boundaries.",
];

const operationalNotes = [
  {
    title: "Administrators stay in control",
    description:
      "Set up academic structures, manage learners and staff, publish announcements, manage term plans, and review school activity from one central workspace.",
  },
  {
    title: "Teachers stay focused",
    description:
      "Access assigned classes, manage scores, prepare academic records, and follow school updates without navigating admin-only tools.",
  },
  {
    title: "Families stay connected",
    description:
      "Give parents and students a clear, private view of linked profiles, academic records, report cards, and school announcements.",
  },
];

function formatLandingPrice(plan) {
  if (plan.planCode === "free") return "₦0 · permanent";
  if (plan.pricePerTerm === null || plan.pricePerTerm === undefined) {
    return plan.priceLabel || "Pricing unavailable";
  }
  return `₦${Number(plan.pricePerTerm).toLocaleString()} / term`;
}

function LandingPage() {
  const location = useLocation();
  const pageRef = useRef(null);
  const [activePricingPlan, setActivePricingPlan] = useState("professional");
  const pricingReady = usePublicPricingCatalogue();
  const paidPlans = LANDING_PRICING_PLANS.filter(
    (plan) => plan.planCode !== "free",
  );

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("public-panel-reveal");
          observer.unobserve(entry.target);
        });
      },
      { threshold: 0.08 },
    );
    const sections =
      pageRef.current?.querySelectorAll("main > section:not(#home)") ?? [];
    sections.forEach((section) => observer.observe(section));
    return () => {
      observer.disconnect();
      sections.forEach((section) =>
        section.classList.remove("public-panel-reveal"),
      );
    };
  }, []);

  useEffect(() => {
    if (!location.hash) return;
    const target = document.getElementById(location.hash.slice(1));
    if (!target) return;
    window.requestAnimationFrame(() => {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, [location.hash]);

  return (
    <div
      ref={pageRef}
      className="public-page-shell min-h-[100dvh] overflow-x-hidden bg-background text-text"
    >
      <Navbar />
      <main>
        <section
          id="home"
          className="relative min-h-[calc(100dvh-4.4rem)] scroll-mt-24 overflow-hidden border-b border-border bg-slate-950 text-white"
        >
          <img
            src={previewImage}
            alt="Weave dashboard preview"
            loading="eager"
            decoding="async"
            fetchPriority="high"
            className="absolute inset-0 h-full w-full object-cover opacity-35"
          />
          <div className="absolute inset-0 bg-slate-950/70" />
          <div className="section-container relative flex min-h-[calc(100dvh-4.4rem)] items-center py-8 pb-[max(2rem,env(safe-area-inset-bottom))] sm:py-18 lg:py-24">
            <div className="grid gap-10 lg:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)] lg:items-center">
              <div className="max-w-3xl">
                <h1
                  className="text-balance text-4xl font-semibold leading-tight tracking-tight text-white sm:text-6xl lg:text-7xl"
                  aria-label="Run your school with clarity, control, and every role connected."
                >
                  {"Run your school with clarity, control, and every role connected."
                    .split(" ")
                    .map((word, index) => (
                      <span key={`${word}-${index}`} aria-hidden="true">
                        <span
                          className="landing-headline-word"
                          style={{ animationDelay: `${80 + index * 85}ms` }}
                        >
                          {word}
                        </span>
                        {index < 9 ? " " : null}
                      </span>
                    ))}
                </h1>
                <p
                  className="public-panel-reveal mt-5 max-w-2xl text-base leading-7 text-slate-200 sm:text-lg sm:leading-8"
                  style={{ animationDelay: "350ms" }}
                >
                  Weave brings student records, staff management, academic
                  setup, results, report cards, family access, announcements,
                  and school operations into one structured workspace.
                </p>
                <div
                  className="public-panel-reveal mt-8 flex flex-col gap-3 sm:flex-row"
                  style={{ animationDelay: "500ms" }}
                >
                  <Link to="/register">
                    <Button size="large" className="w-full sm:w-auto">
                      Get started free
                    </Button>
                  </Link>
                  <Link to="/pricing" className="w-full sm:w-auto">
                    <Button
                      variant="outline"
                      size="large"
                      className="w-full border-white/20 bg-white/10 text-white hover:bg-white/15"
                    >
                      View pricing
                    </Button>
                  </Link>
                </div>
                <p className="mt-4 text-sm text-slate-300">
                  Free is permanent. Registration never starts a payment.
                </p>
              </div>

              <div
                className="public-panel-reveal rounded-[1.75rem] border border-white/10 bg-white/10 p-4 backdrop-blur-xl sm:p-5"
                style={{ animationDelay: "250ms" }}
              >
                <div className="rounded-[1.45rem] border border-white/10 bg-slate-950/35 p-4">
                  <p className="text-sm font-semibold text-white">
                    Start free, then choose per term
                  </p>
                  <p className="mt-2 text-sm leading-6 text-slate-300">
                    Configure and use Weave Free within its limits. When an
                    academic term is ready to open, continue with Free or choose
                    a paid plan for that term.
                  </p>
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  {paidPlans.map((plan) => (
                    <Link
                      key={plan.planCode}
                      to="/pricing"
                      className={`rounded-[1.25rem] border px-4 py-4 text-left transition ${
                        plan.highlighted
                          ? "border-primary/40 bg-primary/10"
                          : "border-white/10 bg-white/5 hover:bg-white/10"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-sm font-semibold text-white">
                          {plan.name}
                        </p>
                        {plan.highlighted ? (
                          <span className="rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-semibold text-white">
                            Popular
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-1 text-xs uppercase tracking-wide text-slate-300">
                        {pricingReady
                          ? formatLandingPrice(plan)
                          : "Loading pricing..."}
                      </p>
                    </Link>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="features" className="section-container scroll-mt-24 py-20">
          <div className="max-w-3xl">
            <p className="text-sm font-bold uppercase tracking-wide text-primary">
              Features
            </p>
            <h2 className="mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">
              The essential school workflows, thoughtfully connected.
            </h2>
            <p className="mt-4 text-base leading-7 text-text-muted">
              Weave gives every role a focused experience while keeping the
              school working from one dependable source of truth.
            </p>
          </div>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {features.map((feature) => {
              const Icon = feature.icon;
              return (
                <article
                  key={feature.title}
                  className="rounded-2xl border border-border bg-surface p-6 shadow-soft-card"
                >
                  <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary-soft text-primary">
                    <Icon className="h-5 w-5" />
                  </span>
                  <h3 className="mt-5 text-lg font-semibold">
                    {feature.title}
                  </h3>
                  <p className="mt-2 text-sm leading-6 text-text-muted">
                    {feature.description}
                  </p>
                </article>
              );
            })}
          </div>
        </section>

        <section
          id="benefits"
          className="scroll-mt-24 border-y border-border bg-surface"
        >
          <div className="section-container grid gap-10 py-20 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
            <div>
              <p className="text-sm font-bold uppercase tracking-wide text-primary">
                Benefits
              </p>
              <h2 className="mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">
                One school. One trusted operational workspace.
              </h2>
              <p className="mt-4 text-base leading-7 text-text-muted">
                Weave keeps records, academic workflows, staff responsibilities,
                family access, and school updates connected without blurring
                permissions between roles.
              </p>
            </div>
            <div className="grid gap-3">
              {benefits.map((benefit) => (
                <div
                  key={benefit}
                  className="flex gap-3 rounded-2xl border border-border bg-background px-5 py-4"
                >
                  <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-success" />
                  <p className="text-sm font-medium leading-6 text-text-soft">
                    {benefit}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="section-container py-20">
          <div className="grid gap-6 lg:grid-cols-3">
            {operationalNotes.map((note) => (
              <article
                key={note.title}
                className="rounded-2xl border border-border bg-surface p-6 shadow-soft-card"
              >
                <span className="flex h-10 w-10 items-center justify-center rounded-full bg-primary-soft text-primary">
                  <CheckCircle2 className="h-5 w-5" />
                </span>
                <h3 className="mt-5 text-lg font-semibold">{note.title}</h3>
                <p className="mt-2 text-sm leading-6 text-text-muted">
                  {note.description}
                </p>
              </article>
            ))}
          </div>
        </section>

        <section
          id="pricing"
          className="relative scroll-mt-24 overflow-hidden border-y border-border bg-background"
        >
          <div className="section-container relative py-16 sm:py-20">
            <div className="mx-auto max-w-3xl text-center">
              <Badge variant="primary">Pricing</Badge>
              <h2 className="mt-5 text-4xl font-semibold tracking-tight text-text sm:text-5xl">
                Free forever, with paid capacity when you need it.
              </h2>
              <p className="mt-4 text-base leading-7 text-text-muted">
                Paid plans are selected inside Weave for the academic term being
                operated. There is no future-term prepayment.
              </p>
            </div>

            <div className="mx-auto mt-8 flex max-w-full justify-center overflow-x-auto px-1 pb-1">
              <div className="inline-grid min-w-[30rem] grid-cols-3 gap-1 rounded-full border border-border/70 bg-surface-muted/60 p-1 shadow-soft-card sm:min-w-[36rem]">
                {paidPlans.map((plan) => (
                  <a
                    key={`landing-plan-tab-${plan.planCode}`}
                    href={`#landing-plan-${plan.planCode}`}
                    onClick={() => setActivePricingPlan(plan.planCode)}
                    aria-current={
                      activePricingPlan === plan.planCode ? "true" : undefined
                    }
                    className={`rounded-full px-3 py-2.5 text-center text-sm font-semibold transition ${
                      activePricingPlan === plan.planCode
                        ? "bg-surface text-primary shadow-[0_10px_30px_rgba(15,23,42,0.12)] ring-1 ring-border/60"
                        : "text-text-muted hover:text-text"
                    }`}
                  >
                    {plan.name}
                  </a>
                ))}
              </div>
            </div>

            <div className="mx-auto mt-12 grid max-w-6xl items-stretch gap-6 md:grid-cols-2 xl:grid-cols-3">
              {paidPlans.map((plan) => (
                <PublicPricingCard
                  key={plan.planCode}
                  plan={plan}
                  id={`landing-plan-${plan.planCode}`}
                  selected={activePricingPlan === plan.planCode}
                />
              ))}
            </div>

            <div className="mt-8 flex flex-col items-center justify-between gap-4 rounded-[1.5rem] border border-border/70 bg-surface px-5 py-5 text-center shadow-soft-card sm:flex-row sm:text-left">
              <div>
                <div className="flex items-center justify-center gap-2 sm:justify-start">
                  <ShieldCheck className="h-4 w-4 text-primary" />
                  <p className="text-sm font-semibold text-text">
                    Need the full comparison?
                  </p>
                </div>
                <p className="mt-1 text-sm leading-6 text-text-muted">
                  See exact limits, term billing rules, upgrades, and
                  downgrades.
                </p>
              </div>
              <Link to="/pricing" className="w-full sm:w-auto">
                <Button className="w-full sm:w-auto">
                  View full pricing
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </Link>
            </div>
          </div>
        </section>

        <section className="section-container py-20">
          <div className="rounded-2xl border border-border bg-slate-950 px-6 py-12 text-center text-white shadow-premium sm:px-10">
            <ShieldCheck className="mx-auto h-10 w-10 text-primary-soft" />
            <h2 className="mt-5 text-4xl font-semibold tracking-tight text-white">
              Give your school a more organised way to operate.
            </h2>
            <p className="mx-auto mt-4 max-w-2xl text-base leading-7 text-slate-300">
              Create your school workspace on Free. Move to a paid plan only
              when an academic term needs greater capacity or premium features.
            </p>
            <Link to="/register" className="mt-8 inline-flex">
              <Button size="large">Create workspace</Button>
            </Link>
          </div>
        </section>
      </main>

      <footer className="border-t border-border bg-surface">
        <div className="section-container flex flex-col gap-4 py-8 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-bold">Weave</p>
            <p className="mt-1 text-sm text-text-muted">
              Connected school operations, built around every role.
            </p>
          </div>
          <div className="flex flex-wrap gap-4 text-sm font-semibold text-text-muted">
            <a href="#features" className="hover:text-primary">
              Features
            </a>
            <a href="#benefits" className="hover:text-primary">
              Benefits
            </a>
            <Link to="/pricing" className="hover:text-primary">
              Pricing
            </Link>
            <Link to="/login" className="hover:text-primary">
              Log in
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}

export default LandingPage;
