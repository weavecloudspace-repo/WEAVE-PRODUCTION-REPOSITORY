import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BookOpen,
  ChevronRight,
  CircleHelp,
  Download,
  Info,
  Link2,
  RefreshCw,
  Terminal,
  Wrench,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import PlatformLogo from "../../features/cbt/PlatformLogo";
import DashboardLayout from "../../components/layout/DashboardLayout";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import { useToast } from "../../hooks/useToast";
import { parseApiError } from "../../services/api";
import { cbtService } from "../../services/cbtService";

const DOWNLOAD_PLATFORMS = [
  {
    id: "windows-desktop",
    platform: "windows",
    kind: "desktop",
    title: "Windows Desktop",
    subtitle: "Recommended for a Windows 64-bit exam server",
    type: "Windows installer",
    topic: "windows",
  },
  {
    id: "windows-cli",
    platform: "windows",
    kind: "cli",
    title: "Windows CLI",
    subtitle: "Command-line setup for advanced administrators",
    type: "Windows setup",
    topic: "cli",
  },
  {
    id: "linux-desktop",
    platform: "linux",
    kind: "desktop",
    title: "Linux Desktop (.deb)",
    subtitle: "Graphical manager for Ubuntu / Debian amd64",
    type: ".deb package",
    topic: "linux",
  },
  {
    id: "linux-cli",
    platform: "linux",
    kind: "cli",
    title: "Linux CLI (.tar.gz)",
    subtitle: "Standalone command line for experienced users",
    type: ".tar.gz archive",
    topic: "linux",
  },
];

const SUPPORT_LINKS = [
  {
    title: "Need the CLI?",
    topic: "cli",
    Icon: Terminal,
  },
  {
    title: "Troubleshooting",
    topic: "troubleshooting",
    Icon: Wrench,
  },
  {
    title: "System requirements",
    topic: "quick-start",
    Icon: CircleHelp,
  },
];

function SizeLabel({ bytes }) {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes <= 0) return null;
  return <span>{(bytes / (1024 * 1024)).toFixed(1)} MB</span>;
}

function DownloadCard({ definition, packageItem, version, onDownload, onOpenDocs, disabled }) {
  const [showIntegrity, setShowIntegrity] = useState(false);
  return (
    <div className="flex h-full min-w-0 flex-col rounded-2xl border border-border/80 bg-surface p-4 shadow-sm transition hover:border-primary/25 hover:shadow-md sm:p-5">
      <div className="flex items-start justify-between gap-2">
        <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
          <PlatformLogo platform={definition.platform} className="h-7 w-7" />
        </div>
        {definition.id === "windows-desktop" && (
          <span className="rounded-full border border-primary/15 bg-primary/5 px-2.5 py-1 text-[10px] font-semibold text-primary">
            Recommended
          </span>
        )}
      </div>
      <h3 className="mt-4 text-sm font-semibold text-text">{definition.title}</h3>
      <p className="mt-1 min-h-10 text-xs leading-5 text-text-muted">{definition.subtitle}</p>
      <Button type="button" className="mt-4 w-full justify-center" disabled={disabled || !packageItem?.url}
        onClick={() => onDownload(packageItem, definition.id === "windows-desktop")}>
        <Download className="h-4 w-4" />
        {definition.kind === "cli" ? "Download CLI" : "Download installer"}
      </Button>
      <div className="mt-4 space-y-2 border-t border-border/70 pt-3 text-xs">
        <div className="flex items-center justify-between gap-2 text-text-muted"><span>Version</span><span className="font-semibold text-text">{version || "Not available"}</span></div>
        <div className="flex items-center justify-between gap-2 text-text-muted"><span>Format</span><span className="font-medium text-text">{definition.type}</span></div>
        {typeof packageItem?.size_bytes === "number" && (
          <div className="flex items-center justify-between gap-2 text-text-muted"><span>Size</span><span className="font-semibold text-text"><SizeLabel bytes={packageItem.size_bytes} /></span></div>
        )}
      </div>
      {!packageItem?.url && <p className="mt-3 text-xs text-text-muted">Package currently unavailable</p>}
      <div className="mt-auto flex items-center justify-between gap-3 pt-3">
        <button type="button" onClick={() => onOpenDocs(definition.topic)} className="inline-flex min-h-8 items-center gap-1 text-xs font-semibold text-primary hover:underline">
          Setup guide <ArrowRight className="h-3.5 w-3.5" />
        </button>
        {packageItem?.sha256 && <button type="button" aria-expanded={showIntegrity} onClick={() => setShowIntegrity((value) => !value)} className="min-h-8 text-xs font-medium text-text-muted hover:text-text">
          {showIntegrity ? "Hide checksum" : "Verify download"}
        </button>}
      </div>
      {showIntegrity && packageItem?.sha256 && <div className="mt-3 rounded-lg border border-border bg-surface-muted/30 p-3">
        <p className="text-xs leading-5 text-text-muted">Compare this SHA-256 checksum with your downloaded file to verify its integrity.</p>
        <code className="mt-2 block break-all text-xs text-text">{packageItem.sha256}</code>
      </div>}
    </div>
  );
}

export default function CBTServerSetupPage() {
  const navigate = useNavigate();
  const { showError, showSuccess } = useToast();
  const [release, setRelease] = useState(null);
  const [downloadMode, setDownloadMode] = useState("desktop");
  const [loadingRelease, setLoadingRelease] = useState(true);
  const [releaseError, setReleaseError] = useState("");
  const [creatingPairingCode, setCreatingPairingCode] = useState(false);

  const loadRelease = useCallback(async () => {
    setLoadingRelease(true);
    setReleaseError("");
    try {
      const response = await cbtService.getLatestRelease();
      setRelease(response);
    } catch (error) {
      const parsed = parseApiError(error, "The WEAVE CBT installer is temporarily unavailable.");
      setRelease(null);
      setReleaseError(parsed.message);
    } finally {
      setLoadingRelease(false);
    }
  }, []);

  useEffect(() => {
    loadRelease();
  }, [loadRelease]);

  const packageName = useMemo(
    () => release?.installer_asset || "WEAVE CBT Windows installer",
    [release?.installer_asset],
  );

  const packages = DOWNLOAD_PLATFORMS.map((definition) => {
    const packageItem = release?.packages?.find(
      (packageItem) =>
        packageItem.platform === "windows" && definition.platform === "windows"
          ? packageItem.kind === definition.kind
          : packageItem.platform === "linux" && definition.platform === "linux"
            ? packageItem.kind === definition.kind
            : false,
    );
    // Keep the existing Windows Desktop API fields compatible with older releases.
    if (!packageItem && definition.id === "windows-desktop" && release?.installer_url) {
      return { definition, packageItem: {
        asset: packageName,
        url: release.installer_url,
        sha256: release.installer_sha256,
      } };
    }
    return { definition, packageItem };
  });

  const startDownload = (packageItem = null, desktop = false) => {
    if (!release?.installer_url || (!packageItem && !desktop)) return;
    const downloadLink = document.createElement("a");
    if (desktop || !packageItem) {
      downloadLink.href = release.installer_url;
      downloadLink.download = packageName;
    } else {
      downloadLink.href = packageItem.url;
      downloadLink.download = packageItem.asset;
    }
    downloadLink.rel = "noopener noreferrer";
    downloadLink.style.display = "none";
    document.body.appendChild(downloadLink);
    downloadLink.click();
    downloadLink.remove();
  };

  const continueToPairing = async () => {
    setCreatingPairingCode(true);
    try {
      const response = await cbtService.createPairingCode();
      showSuccess("Pairing code generated. Enter it in WEAVE CBT Manager.");
      navigate("/admin/cbt/pairing-code", {
        state: { pairingCode: response },
      });
    } catch (error) {
      showError(parseApiError(error, "Could not create a pairing code.").message);
    } finally {
      setCreatingPairingCode(false);
    }
  };

  const openDocs = (topic) => {
    navigate(topic ? "/admin/cbt/documentation?topic=" + encodeURIComponent(topic) : "/admin/cbt/documentation");
  };

  return (
    <DashboardLayout role="admin" title="Set up CBT Server">
      <div className="mx-auto w-full max-w-[1360px] space-y-6 pb-12">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3">
            <Button type="button" variant="ghost" size="icon" aria-label="Back to CBT servers" onClick={() => navigate("/admin/cbt")}>
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div className="min-w-0">
              <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-primary">WEAVE CBT</p>
              <h1 className="mt-1 text-2xl font-semibold tracking-tight text-text sm:text-3xl">Set up a local exam server</h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-text-muted">Download the correct CBT package for your school server, finish local installation and return to connect it to this WEAVE workspace.</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => openDocs()}>
              <BookOpen className="h-4 w-4" /> Documentation
            </Button>
          </div>
        </div>

        <section aria-labelledby="cbt-download-heading">
          <Card className="rounded-2xl border-border/80 p-4 shadow-sm sm:p-6">
            <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 id="cbt-download-heading" className="text-lg font-semibold text-text">Download WEAVE CBT</h2>
                <p className="mt-1 text-sm text-text-muted">Choose a desktop installer or a standalone command-line package for the server computer.</p>
              </div>
            </div>

            {loadingRelease ? (
              <div className="flex min-h-36 items-center justify-center rounded-2xl border border-dashed border-border bg-surface-muted/30 p-6 text-center">
                <div><RefreshCw className="mx-auto h-5 w-5 animate-spin text-primary" /><p className="mt-3 text-sm text-text-muted">Checking available packages...</p></div>
              </div>
            ) : releaseError ? (
              <div role="alert" className="flex flex-col gap-4 rounded-xl border border-amber-300/60 bg-amber-50/70 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-start gap-3"><AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" />
                  <div><p className="text-sm font-semibold text-amber-900">Installer metadata could not be loaded</p><p className="mt-1 text-sm leading-6 text-amber-900">{releaseError}</p></div>
                </div>
                <Button type="button" variant="outline" size="sm" onClick={loadRelease}><RefreshCw className="h-4 w-4" /> Try again</Button>
              </div>
            ) : (
              <>
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <div role="group" aria-label="Installation type" className="inline-flex rounded-xl border border-border bg-surface-muted/40 p-1">
                    {[{ id: "desktop", label: "GUI", description: "Desktop manager" }, { id: "cli", label: "CLI", description: "Command line" }].map((mode) => (
                      <button key={mode.id} type="button" aria-pressed={downloadMode === mode.id} onClick={() => setDownloadMode(mode.id)}
                        className={"min-h-10 rounded-lg px-5 text-sm font-semibold transition-colors " + (downloadMode === mode.id ? "bg-primary text-primary-foreground shadow-sm" : "text-text-muted hover:text-text")}>
                        {mode.label}<span className="ml-2 hidden text-xs font-normal sm:inline">{mode.description}</span>
                      </button>
                    ))}
                  </div>
                  <p className="text-xs text-text-muted">{downloadMode === "desktop" ? "Recommended for most schools" : "For experienced administrators"}</p>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  {packages.filter(({ definition }) => definition.kind === downloadMode).map(({definition, packageItem}) => (
                    <DownloadCard key={definition.id} definition={definition} packageItem={packageItem}
                      version={release?.manager_version} disabled={loadingRelease}
                      onDownload={startDownload} onOpenDocs={openDocs} />
                  ))}
                </div>
              </>
            )}
          </Card>
        </section>

        <div className="flex flex-col gap-4 border-y border-border/70 py-5 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-base font-semibold text-text">First time setting up?</h2>
            <p className="mt-1 text-sm text-text-muted">Follow the guide from installation to your first school LAN connection.</p>
          </div>
          <Button variant="outline" onClick={() => openDocs("quick-start")} className="shrink-0">
            <BookOpen className="h-4 w-4" /> Quick start guide <ArrowRight className="h-4 w-4" />
          </Button>
        </div>

        <nav aria-label="Setup help" className="flex flex-wrap gap-x-6 gap-y-2">
          {SUPPORT_LINKS.map(({ title, topic, Icon }) => (
            <button key={topic} type="button" onClick={() => openDocs(topic)}
              className="inline-flex min-h-10 items-center gap-2 text-sm font-medium text-text-muted hover:text-primary">
              <Icon className="h-4 w-4" /> {title} <ChevronRight className="h-3.5 w-3.5" />
            </button>
          ))}
        </nav>

        <div className="flex flex-col gap-4 rounded-2xl border border-primary/20 bg-primary/5 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-surface text-primary"><Link2 className="h-5 w-5" /></span>
            <div>
              <h2 className="text-base font-semibold text-text">Ready to connect your CBT server?</h2>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-text-muted">Complete installation and verify the local Manager first. Pairing codes expire, so generate one only when you're ready to enter it in WEAVE CBT.</p>
              <button type="button" onClick={() => openDocs("pairing")} className="mt-2 inline-flex min-h-8 items-center gap-1 text-xs font-semibold text-primary hover:underline">
                <Info className="h-3.5 w-3.5" /> How pairing works <ArrowRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          <Button type="button" className="shrink-0 justify-center" disabled={creatingPairingCode} onClick={continueToPairing}>
            {creatingPairingCode ? <RefreshCw className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
            {creatingPairingCode ? "Generating code..." : "Continue to pairing"}
          </Button>
        </div>
      </div>
    </DashboardLayout>
  );
}
