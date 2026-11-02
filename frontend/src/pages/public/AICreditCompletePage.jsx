import WeaveIcon from "../../components/brand/WeaveIcon";

export default function AICreditCompletePage() {
  return (
    <main className="flex min-h-screen min-h-[100svh] items-center justify-center bg-slate-50 px-5 py-10 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <section
        aria-labelledby="ai-credit-completion-title"
        className="w-full max-w-md rounded-3xl border border-slate-200 bg-white px-6 pb-7 pt-9 text-center shadow-sm sm:px-10 sm:pb-8 sm:pt-10 dark:border-slate-800 dark:bg-slate-900"
      >
        <div className="mb-8 flex items-center justify-center gap-2">
          <WeaveIcon className="h-12 w-12 shrink-0" decorative />
          <span className="brand-wordmark text-2xl font-semibold tracking-tight">Weave</span>
        </div>
        <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
          AI credits
        </p>
        <h1 id="ai-credit-completion-title" className="text-2xl font-semibold leading-tight tracking-tight sm:text-3xl">
          Return to Weave
        </h1>
        <div className="mx-auto mt-4 max-w-xs text-base leading-7 text-slate-600 dark:text-slate-300">
          <p>Return to your Weave tab to check your AI credits.</p>
          <p className="mt-2">Your balance may take a few moments to update.</p>
        </div>
        <p className="mt-8 border-t border-slate-100 pt-5 text-xs font-medium text-blue-600 dark:border-slate-800 dark:text-blue-400">
          You can close this tab and return to Weave.
        </p>
      </section>
    </main>
  );
}
