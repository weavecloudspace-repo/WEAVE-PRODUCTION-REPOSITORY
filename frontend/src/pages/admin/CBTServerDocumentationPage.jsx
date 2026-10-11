import {
  ArrowLeft, ArrowRight, BookOpen, Check, ChevronRight, CircleHelp, Copy,
Info, Laptop, Link2, Monitor, Network, RefreshCcw, Rocket,
  Search, ShieldCheck, Terminal, Wrench, X,
} from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";

import PlatformLogo from "../../features/cbt/PlatformLogo";
import DashboardLayout from "../../components/layout/DashboardLayout";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import { CBT_DOCS, CLI_COMMANDS, CLI_GROUPS, searchCbtDocs } from "../../features/cbt/cbtDocumentationContent";

const DOC_ICONS = { Rocket, Monitor, Laptop, Terminal, Link2, Network, Wrench, RefreshCcw, CircleHelp };
const CLI_PLATFORM_EXAMPLES = {
  windows: {
    label: "Windows",
    instructions: "Open PowerShell. If weave is not on PATH, use the installed executable path below and append the command and its options.",
    command: '& "C:\\Program Files\\WeaveCBT\\weave.exe" status --json',
  },
  linux: {
    label: "Linux",
    instructions: "Open a terminal. The desktop package normally adds weave to PATH. Use sudo for administration commands; inspection requires access to the installed runtime.",
    command: "weave status --json",
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

function CommandReference({ groupId, onSelectGroup }) {
  const commands = CLI_COMMANDS.filter((item) => item.groupId === groupId);
  return (
    <div className="space-y-4">
      <div className="lg:hidden">
        <label htmlFor="cli-command-group" className="mb-2 block text-xs font-semibold text-text">Command group</label>
        <select id="cli-command-group" value={groupId} onChange={(event) => onSelectGroup(event.target.value)}
          className="min-h-11 w-full rounded-lg border border-border bg-surface px-3 text-sm text-text">
          {CLI_GROUPS.map((group) => <option key={group.id} value={group.id}>{group.title}</option>)}
        </select>
      </div>
      <p className="text-xs leading-5 text-text-muted">Select a command to see when to use it, supported options, and copyable examples. Examples use <code>weave</code>; substitute the installed executable path if needed.</p>
      <div className="divide-y divide-border/70 overflow-hidden rounded-xl border border-border/80">
        {commands.map((item) => <details key={item.command} className="group bg-surface">
          <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-3 px-4 py-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary [&::-webkit-details-marker]:hidden">
            <span className="min-w-0"><code className="text-sm font-semibold text-text">{item.command}</code><span className="mt-1 block text-xs leading-5 text-text-muted">{item.description}</span></span>
            <ChevronRight aria-hidden="true" className="h-4 w-4 shrink-0 text-text-muted transition-transform group-open:rotate-90 motion-reduce:transition-none" />
          </summary>
          <div className="space-y-4 border-t border-border/60 px-4 py-5 sm:px-5">
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-muted"><span>{item.platforms}</span><span>{item.access}</span></div>
            <p className="text-sm leading-6 text-text-muted">{item.explanation}</p>
            <div><h3 className="mb-2 text-xs font-semibold text-text">Usage</h3><code className="block break-words rounded-lg bg-surface-muted/50 p-3 text-xs leading-6 text-text">{item.usage}</code></div>
            <div>
              <h3 className="mb-2 text-xs font-semibold text-text">Options & arguments</h3>
              {item.options.length ? <dl className="space-y-3">{item.options.map((option) => <div key={option.flag} className="sm:grid sm:grid-cols-[minmax(0,160px)_minmax(0,1fr)] sm:gap-3">
                <dt><code className="break-words text-xs font-semibold text-text">{option.flag}</code></dt>
                <dd className="mt-1 text-xs leading-6 text-text-muted sm:mt-0">{option.description}</dd>
              </div>)}</dl> : <p className="text-xs text-text-muted">No command-specific options or arguments. Add --help to view help.</p>}
            </div>
            <div className="space-y-3"><h3 className="text-xs font-semibold text-text">Example usage</h3>
              {item.examples.map((example) => <CommandBlock key={example.command} command={example.command} label={example.label + (example.platform ? " (" + example.platform + ")" : "")} />)}
            </div>
            <div><h3 className="mb-1 text-xs font-semibold text-text">What to check afterward</h3><p className="text-xs leading-6 text-text-muted">{item.outcome}</p></div>
            {item.note && <p className="rounded-lg border border-primary/15 bg-primary/5 p-3 text-xs leading-6 text-text">{item.note}</p>}
          </div>
        </details>)}
      </div>
    </div>
  );
}

function DocumentationArticleSection({ section, index, showPlatform, onSelectGroup }) {
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
          </div>}
          {section.commands?.map((item) => <CommandBlock key={item.command} command={item.command} label={item.label} />)}
          {section.commandTable && <CommandReference groupId={section.commandGroupId} onSelectGroup={onSelectGroup} />}
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
  const requestedGroup = params.get("group") || topic.sections.find((section) => "#" + section.id === location.hash)?.commandGroupId;
  const selectedGroup = CLI_GROUPS.find((group) => group.id === requestedGroup) || CLI_GROUPS[0];
  const visibleSections = topic.id === "cli"
    ? topic.sections.filter((section) => section.commandGroupId === selectedGroup.id || (selectedGroup.id === "diagnostics" && section.id === "cli-intro"))
    : topic.sections;
  const previousTarget = useRef({ contentKey: topic.id + selectedGroup.id, hash: location.hash });
  const [query, setQuery] = useState("");
  const [mobileNav, setMobileNav] = useState(false);
  const [cliNavExpanded, setCliNavExpanded] = useState(true);
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

  useLayoutEffect(() => {
    const contentKey = topic.id + selectedGroup.id;
    const contentChanged = previousTarget.current.contentKey !== contentKey;
    const hashChanged = previousTarget.current.hash !== location.hash;
    previousTarget.current = { contentKey, hash: location.hash };
    if (!contentChanged && !hashChanged && !location.hash) return;

    const article = articleRef.current;
    const viewport = document.getElementById("dashboard-scroll-viewport");
    if (!article || !viewport) return;
    const section = topic.sections.find((item) => "#" + item.id === location.hash);
    const target = (section && document.getElementById(section.id)) || article;
    const offset = section ? (sectionNavRef.current?.getBoundingClientRect().height || 0) + 16 : 16;
    const top = Math.max(0, viewport.scrollTop + target.getBoundingClientRect().top - viewport.getBoundingClientRect().top - offset);
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Keep the current reading position unless a section was requested or the
    // new, shorter article would otherwise leave its heading above the viewport.
    if (section || viewport.scrollTop > top) {
      viewport.scrollTo({ top, behavior: section && !contentChanged && !reducedMotion ? "smooth" : "auto" });
    }
    if (contentChanged && !reducedMotion) {
      const animation = article.animate?.(
        [{ opacity: 0.65, transform: "translateY(4px)" }, { opacity: 1, transform: "translateY(0)" }],
        { duration: 150, easing: "ease-out" },
      );
      return () => animation?.cancel();
    }
  }, [topic, selectedGroup.id, location.hash]);

  const openTopic = (topicId, sectionId, groupId) => {
    navigate({ pathname: location.pathname, search: "?topic=" + encodeURIComponent(topicId) + (groupId ? "&group=" + encodeURIComponent(groupId) : ""), hash: sectionId ? "#" + sectionId : "" });
    setQuery("");
    setMobileNav(false);
  };
  const navigateToSection = (sectionId) => {
    navigate({ pathname: location.pathname, search: location.search, hash: "#" + sectionId });
  };
  const selectTopic = (topicId) => {
    if (topicId === "cli" && topic.id === "cli") {
      setCliNavExpanded((expanded) => !expanded);
      return;
    }
    if (topicId === "cli") setCliNavExpanded(true);
    openTopic(topicId);
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
          <div className="overflow-hidden rounded-xl border border-border/80 bg-surface" aria-label="Documentation search results">
            <div className="flex items-center justify-between gap-3 border-b border-border/70 px-4 py-3">
              <h2 className="text-xs font-semibold text-text">Search results ({results.length})</h2>
              <button type="button" onClick={() => setQuery("")} className="inline-flex min-h-8 items-center gap-1 text-xs font-medium text-text-muted hover:text-text"><X className="h-3.5 w-3.5" /> Clear</button>
            </div>
            {results.length ? <ul className="divide-y divide-border/60">{results.map((item) => <li key={item.topicId + item.sectionId}>
              <button type="button" onClick={() => openTopic(item.topicId, item.sectionId, item.groupId)}
                className="group flex min-h-14 w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-primary/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-primary sm:px-5">
                <span className="flex min-w-0 flex-col gap-1 sm:flex-row sm:items-center sm:gap-4">
                  <span className="shrink-0 text-xs font-medium text-text-muted sm:w-36">{item.topicTitle}</span>
                  <span className="text-sm font-medium text-text">{item.sectionTitle}</span>
                </span>
                <ArrowRight aria-hidden="true" className="h-4 w-4 shrink-0 text-text-muted group-hover:text-primary" />
              </button>
            </li>)}</ul> : <p className="px-4 py-6 text-sm text-text-muted">No matching articles. Try “weave logs”, “Windows”, “DNS” or “pairing”.</p>}
          </div>
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
                return <div key={item.id}><button type="button" aria-current={topic.id === item.id ? "page" : undefined}
                  aria-expanded={item.id === "cli" ? topic.id === "cli" && cliNavExpanded : undefined}
                  aria-controls={item.id === "cli" ? "cli-command-groups" : undefined} onClick={() => selectTopic(item.id)}
                  className={topic.id === item.id ? "flex w-full items-start gap-3 rounded-xl bg-primary/10 px-3 py-3 text-left text-primary" : "flex w-full items-start gap-3 rounded-xl px-3 py-3 text-left text-text-soft hover:bg-surface-muted/60 hover:text-text"}>
                  {item.id === "windows" || item.id === "linux" ? <PlatformLogo platform={item.id} className="mt-0.5 h-5 w-5 shrink-0" /> : <Icon className="mt-0.5 h-4 w-4 shrink-0" />}
                  <span className="min-w-0"><span className="block text-xs font-semibold">{item.title}</span></span>
                </button>
                  {item.id === "cli" && topic.id === "cli" && cliNavExpanded && <nav id="cli-command-groups" aria-label="CLI command groups" className="mb-2 ml-5 border-l border-border pl-2">
                    {CLI_GROUPS.map((group) => <button key={group.id} type="button" aria-current={selectedGroup.id === group.id ? "page" : undefined}
                      onClick={() => openTopic("cli", "cli-" + group.id, group.id)}
                      className={"block min-h-9 w-full rounded-lg px-2 py-2 text-left text-xs " + (selectedGroup.id === group.id ? "bg-primary/10 font-semibold text-primary" : "text-text-muted hover:bg-surface-muted hover:text-text")}>
                      {group.title}
                    </button>)}
                  </nav>}
                </div>;
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
                {visibleSections.map((section) => <button key={section.id} type="button" onClick={() => navigateToSection(section.id)} aria-current={location.hash === "#" + section.id ? "location" : undefined}
                  className="min-h-8 text-xs font-medium text-text-muted hover:text-primary hover:underline aria-[current=location]:text-primary">{section.title}</button>)}
              </nav>
              <div className="space-y-7 px-5 py-7 sm:px-8 sm:py-9">
                {visibleSections.map((section, index) => <DocumentationArticleSection key={section.id} section={section} index={index} onSelectGroup={(groupId) => openTopic("cli", "cli-" + groupId, groupId)} showPlatform={topic.id === "cli" && section.id === "cli-intro"} />)}
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
