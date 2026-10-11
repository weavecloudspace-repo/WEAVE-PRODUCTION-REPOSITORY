import {
  ArrowLeft, ArrowRight, BookOpen, Check, ChevronRight, CircleHelp, Copy,
Info, Laptop, Link2, Monitor, Network, RefreshCcw, Rocket,
  Search, ShieldCheck, Terminal, Wrench, X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";

import PlatformLogo from "../../features/cbt/PlatformLogo";
import DashboardLayout from "../../components/layout/DashboardLayout";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import { CBT_DOCS, CLI_COMMANDS, searchCbtDocs } from "../../features/cbt/cbtDocumentationContent";

const DOC_ICONS = { Rocket, Monitor, Laptop, Terminal, Link2, Network, Wrench, RefreshCcw, CircleHelp };
const CATEGORIES = ["All", "Inspection", "Service", "Logs", "Administration"];
const CLI_PLATFORM_EXAMPLES = {
  windows: {
    label: "Windows",
    instructions: "The Windows Desktop installer includes weave.exe. From PowerShell, invoke its installed path directly if the CLI is not yet on PATH.",
    command: '& "C:\\Program Files\\WeaveCBT\\weave.exe" release',
  },
  deb: {
    label: "Linux desktop (.deb)",
    instructions: "Install the channel-matched Desktop .deb package using the system package manager. It includes the CLI.",
    command: "sudo apt install ./weave-cbt-desktop-staging-linux-amd64.deb",
  },
  tar: {
    label: "Linux CLI (.tar.gz)",
    instructions: "Download the channel-matched CLI archive. Inspect its contents before extracting and follow its included installation guidance.",
    command: "tar -tzf weave-cbt-staging-linux-amd64.tar.gz | head",
  },
};

function CommandBlock({ command, label = "Terminal" }) {
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setCopyFailed(false);
    } catch {
      setCopyFailed(true);
      setCopied(false);
    }
  };

  return (
    <div className="overflow-hidden rounded-xl border border-slate-700/60 bg-slate-950 text-slate-50">
      <div className="flex items-center justify-between gap-3 border-b border-slate-700/70 bg-slate-900/70 px-4 py-2">
        <span className="flex items-center gap-2 text-[11px] font-medium text-slate-300">
          <Terminal className="h-3.5 w-3.5" />{label}
        </span>
        <button type="button" onClick={copy} className="inline-flex min-h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs font-semibold text-slate-100 hover:bg-slate-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white" aria-label={"Copy " + command}>
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copyFailed ? "Copy failed" : copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto p-4 text-xs leading-6"><code>{command}</code></pre>
    </div>
  );
}

function CommandReference() {
  const [category, setCategory] = useState("All");
  const commands = category === "All" ? CLI_COMMANDS : CLI_COMMANDS.filter((item) => item.category === category);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter CLI commands">
        {CATEGORIES.map((item) => (
          <button key={item} type="button" aria-pressed={category === item} onClick={() => setCategory(item)}
            className={category === item ? "rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground" : "rounded-lg border border-border bg-surface px-3 py-2 text-xs font-medium text-text-soft hover:border-primary/30 hover:text-text"}>
            {item}
          </button>
        ))}
      </div>
      <div className="overflow-hidden rounded-xl border border-border/80">
        {commands.map((item) => <div key={item.command} className="flex flex-col gap-2 border-b border-border/60 bg-surface p-3 last:border-0 sm:flex-row sm:items-center sm:gap-4 sm:px-4">
          <div className="min-w-0 flex-1">
            <code className="break-all rounded-md bg-surface-muted px-2 py-1 text-xs font-semibold text-text">{item.command}</code>
            <p className="mt-2 text-xs leading-5 text-text-muted">{item.description}</p>
          </div>
          <InlineCopy command={item.command} />
        </div>)}
      </div>
      <p className="text-xs text-text-muted">Tip: use <code className="rounded bg-surface-muted px-1.5 py-0.5">weave --help</code> or <code className="rounded bg-surface-muted px-1.5 py-0.5">weave install --help</code> to inspect the options supported by your installed version.</p>
    </div>
  );
}

function InlineCopy({ command }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    try { await navigator.clipboard.writeText(command); setCopied(true); }
    catch { setCopied(false); }
  };
  return <button type="button" onClick={handleCopy} aria-label={"Copy " + command}
    className="inline-flex min-h-9 items-center justify-center gap-2 self-start rounded-lg border border-border px-3 text-xs font-medium text-text-soft hover:border-primary/40 hover:text-primary sm:self-center">
    {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
    {copied ? "Copied" : "Copy"}
  </button>;
}

function DocumentationArticleSection({ section, index, showPlatform }) {
  const [platform, setPlatform] = useState("windows");
  const example = CLI_PLATFORM_EXAMPLES[platform];

  return (
    <section id={section.id} className="scroll-mt-24 border-t border-border/70 pt-7 first:border-0 first:pt-0" aria-labelledby={section.id + "-title"}>
      <div className="flex items-start gap-3">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary/10 text-xs font-bold text-primary">{index + 1}</span>
        <div className="min-w-0 flex-1 space-y-4">
          <h2 id={section.id + "-title"} className="pt-0.5 text-lg font-semibold tracking-tight text-text">{section.title}</h2>
          {section.paragraphs?.map((p) => <p key={p} className="text-sm leading-7 text-text-muted">{p}</p>)}
          {section.steps && <ol className="space-y-3">
            {section.steps.map(([label, explanation], i) => <li key={label} className="flex gap-3 rounded-xl border border-border/70 bg-surface-muted/25 p-3.5">
              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-primary/10 text-xs font-semibold text-primary">{i + 1}</span>
              <span><span className="block text-sm font-semibold text-text">{label}</span><span className="mt-1 block text-xs leading-5 text-text-muted">{explanation}</span></span>
            </li>)}
          </ol>}
          {showPlatform && <div className="rounded-xl border border-border/80 bg-surface-muted/20 p-3 sm:p-4">
            <div role="group" aria-label="Select command platform" className="mb-4 flex flex-wrap gap-2">
              {Object.entries(CLI_PLATFORM_EXAMPLES).map(([key, item]) => <button key={key} type="button" aria-pressed={platform === key} onClick={() => setPlatform(key)}
                className={platform === key ? "rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground" : "rounded-lg border border-border bg-surface px-3 py-2 text-xs font-medium text-text-soft hover:text-text"}>
                <span className="flex items-center gap-2"><PlatformLogo platform={key === "windows" ? "windows" : "linux"} className="h-4 w-4" />{item.label}</span>
              </button>)}
            </div>
            <p className="mb-3 text-xs leading-6 text-text-muted">{example.instructions}</p>
            <CommandBlock label={platform === "windows" ? "PowerShell" : "Terminal"} command={example.command} />
            <p className="mt-3 text-xs text-text-muted">Sample staging filename shown. Always use the current package from your environment's download page.</p>
          </div>}
          {section.commands?.map((item) => <CommandBlock key={item.command} command={item.command} label={item.label} />)}
          {section.commandTable && <CommandReference />}
          {section.tips?.map((tip) => <div key={tip} className="flex items-start gap-2.5 rounded-xl border border-primary/15 bg-primary/5 px-4 py-3 text-xs leading-6 text-text">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" /><p>{tip}</p>
          </div>)}
        </div>
      </div>
    </section>
  );
}

export default function CBTServerDocumentationPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const location = useLocation();
  const articleRef = useRef(null);
  const sectionNavRef = useRef(null);
  const requestedTopic = params.get("topic");
  const topic = CBT_DOCS.find((item) => item.id === requestedTopic) || CBT_DOCS[0];
  const previousTarget = useRef(topic.id + location.hash);
  const [query, setQuery] = useState("");
  const [mobileNav, setMobileNav] = useState(false);
  const searchInput = useRef(null);
  const results = useMemo(() => searchCbtDocs(query), [query]);

  useEffect(() => {
    const onKeyDown = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchInput.current?.focus();
      }
      if (event.key === "Escape") searchInput.current?.blur();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    const targetKey = topic.id + location.hash;
    const unchangedTarget = previousTarget.current === targetKey;
    previousTarget.current = targetKey;
    if (unchangedTarget && !location.hash) return;
    // Wait until the shell has reset its viewport and React has rendered the new topic.
    let secondFrame;
    const firstFrame = window.requestAnimationFrame(() => {
      secondFrame = window.requestAnimationFrame(() => {
        const section = topic.sections.find((item) => "#" + item.id === location.hash);
        const target = section ? document.getElementById(section.id) : articleRef.current;
        const viewport = document.getElementById("dashboard-scroll-viewport");
        if (!target || !viewport) return;
        const offset = section ? (sectionNavRef.current?.getBoundingClientRect().height || 0) + 16 : 16;
        const top = viewport.scrollTop + target.getBoundingClientRect().top - viewport.getBoundingClientRect().top - offset;
        const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        viewport.scrollTo({ top: Math.max(0, top), behavior: reducedMotion ? "auto" : "smooth" });
      });
    });
    return () => {
      window.cancelAnimationFrame(firstFrame);
      if (secondFrame) window.cancelAnimationFrame(secondFrame);
    };
  }, [topic, location.hash]);

  const openTopic = (topicId, sectionId) => {
    navigate({ pathname: location.pathname, search: "?topic=" + encodeURIComponent(topicId), hash: sectionId ? "#" + sectionId : "" });
    setQuery("");
    setMobileNav(false);
  };
  const navigateToSection = (sectionId) => {
    navigate({ pathname: location.pathname, search: location.search, hash: "#" + sectionId });
  };
  const TopicIcon = DOC_ICONS[topic.icon] || BookOpen;

  return (
    <DashboardLayout role="admin" title="WEAVE CBT Documentation">
      <div className="mx-auto w-full max-w-[1200px] space-y-4 pb-8">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <Button variant="ghost" size="icon" aria-label="Back to CBT setup" onClick={() => navigate("/admin/cbt/setup-server")}><ArrowLeft className="h-4 w-4" /></Button>
            <div>
              <div className="flex flex-wrap items-center gap-1.5 text-xs font-medium text-text-muted">
                <span className="text-primary">WEAVE CBT</span><ChevronRight className="h-3 w-3" /><span>Documentation</span><ChevronRight className="h-3 w-3" /><span className="text-text">{topic.title}</span>
              </div>
              <h1 className="mt-2 text-2xl font-semibold tracking-tight text-text sm:text-3xl">Documentation</h1>
              <p className="mt-1.5 max-w-2xl text-sm leading-6 text-text-muted">Straightforward instructions for installing, operating and troubleshooting your local school exam server.</p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={() => navigate("/admin/cbt/setup-server")}><Monitor className="h-4 w-4" /> Back to setup</Button>
        </div>

        <div className="relative">
          <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-text-muted" />
          <input ref={searchInput} value={query} onChange={(event) => setQuery(event.target.value)}
            type="search" aria-label="Search CBT documentation" placeholder="Search documentation, CLI commands, setup, pairing..."
            className="h-12 w-full rounded-2xl border border-border/80 bg-surface pl-12 pr-16 text-sm text-text shadow-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15" />
          <span className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 rounded-md border border-border bg-surface-muted px-2 py-1 text-[10px] font-semibold text-text-muted">Ctrl K</span>
        </div>

        {query.trim() ? (
          <Card className="space-y-3 rounded-2xl p-4 sm:p-6">
            <div className="flex items-center justify-between gap-3"><h2 className="text-sm font-semibold text-text">Search results ({results.length})</h2>
              <button type="button" onClick={() => setQuery("")} className="flex items-center gap-1 text-xs font-medium text-text-muted hover:text-text"><X className="h-3.5 w-3.5" /> Clear</button>
            </div>
            {results.length ? <div className="grid gap-2 sm:grid-cols-2">{results.map((item) => <button key={item.topicId + item.sectionId} type="button" onClick={() => openTopic(item.topicId, item.sectionId)}
              className="group rounded-xl border border-border/80 p-3 text-left hover:border-primary/40 hover:bg-primary/5">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-primary">{item.topicTitle}</span>
              <span className="mt-1 flex items-center justify-between gap-2 text-sm font-medium text-text">{item.sectionTitle}<ArrowRight className="h-4 w-4 shrink-0 text-text-muted group-hover:text-primary" /></span>
            </button>)}</div> : <p className="py-6 text-center text-sm text-text-muted">No matching articles. Try “weave logs”, “Windows”, “DNS” or “pairing”.</p>}
          </Card>
        ) : null}

        <div className="grid items-start gap-5 lg:grid-cols-[200px_minmax(0,1fr)]">
          <div className="lg:hidden">
            <Button variant="outline" size="sm" onClick={() => setMobileNav((v) => !v)} aria-expanded={mobileNav}><BookOpen className="h-4 w-4" /> Browse topics <ChevronRight className="h-4 w-4" /></Button>
          </div>
          <aside aria-label="Documentation topics" className={(mobileNav ? "block" : "hidden") + " rounded-2xl border border-border/80 bg-surface p-2 shadow-sm lg:sticky lg:top-4 lg:block lg:max-h-[calc(100dvh-120px)] lg:overflow-y-auto"}>
            <p className="px-3 pb-2 pt-3 text-[10px] font-bold uppercase tracking-[0.17em] text-text-muted">Browse documentation</p>
            <nav className="space-y-1">
              {CBT_DOCS.map((item) => {
                const Icon = DOC_ICONS[item.icon] || BookOpen;
                return <button key={item.id} type="button" aria-current={topic.id === item.id ? "page" : undefined} onClick={() => openTopic(item.id)}
                  className={topic.id === item.id ? "flex w-full items-start gap-3 rounded-xl bg-primary/10 px-3 py-3 text-left text-primary" : "flex w-full items-start gap-3 rounded-xl px-3 py-3 text-left text-text-soft hover:bg-surface-muted/60 hover:text-text"}>
                  {item.id === "windows" || item.id === "linux" ? <PlatformLogo platform={item.id} className="mt-0.5 h-5 w-5 shrink-0" /> : <Icon className="mt-0.5 h-4 w-4 shrink-0" />}
                  <span className="min-w-0"><span className="block text-xs font-semibold">{item.title}</span></span>
                </button>;
              })}
            </nav>
          </aside>

          <main ref={articleRef} className="min-w-0">
            <Card className="rounded-2xl border-border/80 p-0 shadow-sm">
              <div className="border-b border-border/70 px-5 py-5 sm:px-8 sm:py-6">
                <div className="mb-2 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.14em] text-primary">{topic.id === "windows" || topic.id === "linux" ? <PlatformLogo platform={topic.id} className="h-5 w-5" /> : <TopicIcon className="h-4 w-4" />} WEAVE CBT Guide</div>
                <h2 className="text-xl font-semibold tracking-tight text-text sm:text-2xl">{topic.title}</h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-text-muted">{topic.summary}</p>
              </div>
              <nav ref={sectionNavRef} aria-label="On this page" className="sticky top-0 z-10 flex flex-wrap gap-x-4 gap-y-1 border-b border-border/70 bg-surface/95 px-5 py-3 backdrop-blur sm:px-8">
                {topic.sections.map((section) => <button key={section.id} type="button" onClick={() => navigateToSection(section.id)} aria-current={location.hash === "#" + section.id ? "location" : undefined}
                  className="min-h-8 text-xs font-medium text-text-muted hover:text-primary hover:underline aria-[current=location]:text-primary">{section.title}</button>)}
              </nav>
              <div className="space-y-7 px-5 py-7 sm:px-8 sm:py-9">
                {topic.sections.map((section, index) => <DocumentationArticleSection key={section.id} section={section} index={index} showPlatform={topic.id === "cli" && section.id === "cli-intro"} />)}
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/70 bg-surface-muted/20 px-5 py-4 sm:px-8">
                <p className="flex items-center gap-2 text-xs text-text-muted"><ShieldCheck className="h-4 w-4 text-primary" /> Verify commands against the installed version.</p>
                <Button variant="outline" size="sm" onClick={() => navigate("/admin/cbt/setup-server")}>Return to setup <ArrowRight className="h-4 w-4" /></Button>
              </div>
            </Card>
          </main>
        </div>
      </div>
    </DashboardLayout>
  );
}
