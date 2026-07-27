"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type {
  Application,
  ApplicationStatus,
  Board,
  JobMatch,
} from "@/lib/types";

/** Board columns. Terminal states are grouped at the end. */
const COLUMNS: { status: ApplicationStatus; label: string }[] = [
  { status: "draft", label: "Draft" },
  { status: "tailoring", label: "Tailoring" },
  { status: "ready_for_review", label: "Ready for review" },
  { status: "submitted", label: "Submitted" },
  { status: "interviewing", label: "Interviewing" },
  { status: "offer", label: "Offer" },
];

/** What the user can move a card to from each status. */
const NEXT_ACTIONS: Partial<Record<ApplicationStatus, ApplicationStatus[]>> = {
  draft: ["tailoring", "withdrawn"],
  tailoring: ["ready_for_review", "withdrawn"],
  prefilling: ["ready_for_review", "withdrawn"],
  ready_for_review: ["submitted", "withdrawn"],
  submitted: ["acknowledged", "interviewing", "rejected"],
  acknowledged: ["interviewing", "rejected"],
  interviewing: ["offer", "rejected"],
  offer: ["rejected"],
};

const LABELS: Record<string, string> = {
  draft: "Draft",
  tailoring: "Tailoring",
  prefilling: "Prefilling",
  ready_for_review: "Ready for review",
  submitted: "Submitted",
  acknowledged: "Acknowledged",
  interviewing: "Interviewing",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

export default function TrackerPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  const [board, setBoard] = useState<Board | null>(null);
  const [matches, setMatches] = useState<JobMatch[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pasteUrl, setPasteUrl] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  const refresh = useCallback(async () => {
    try {
      const [nextBoard, nextMatches] = await Promise.all([
        api.getBoard(),
        api.listMatches(),
      ]);
      setBoard(nextBoard);
      setMatches(nextMatches);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load the board.");
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    let active = true;
    void (async () => {
      await refresh();
      if (!active) return;
    })();
    return () => {
      active = false;
    };
  }, [user, refresh]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  if (loading || !user) {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-sm text-neutral-500">Loading…</p>
      </main>
    );
  }

  const tracked = new Set(board?.applications.map((a) => a.job_posting.id) ?? []);
  const untracked = matches.filter((m) => !tracked.has(m.job_posting.id));

  return (
    <div className="flex flex-1 flex-col">
      <header className="flex items-center justify-between border-b border-neutral-200 px-6 py-4 dark:border-neutral-800">
        <div>
          <h1 className="font-semibold tracking-tight">Applications</h1>
          <p className="text-xs text-neutral-500">
            The agent prepares. You decide what gets sent.
          </p>
        </div>
        <Link
          href="/dashboard"
          className="text-sm text-neutral-600 underline underline-offset-4 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-100"
        >
          Dashboard
        </Link>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">
        {error && (
          <p className="mb-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
            {error}
          </p>
        )}

        {notice && (
          <p className="mb-6 rounded-md bg-green-50 px-3 py-2 text-sm text-green-800 dark:bg-green-950 dark:text-green-300">
            {notice}
          </p>
        )}

        <div className="mb-4 flex flex-wrap gap-2">
          <input
            type="url"
            value={pasteUrl}
            onChange={(event) => setPasteUrl(event.target.value)}
            placeholder="Paste any job link — the agent tailors CV + Anschreiben for it"
            className="min-w-0 flex-1 rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm outline-none focus:border-neutral-900 dark:border-neutral-700 dark:bg-neutral-900 dark:focus:border-neutral-100"
          />
          <button
            onClick={() =>
              run(async () => {
                const prepared = await api.prepareFromUrl(pasteUrl.trim());
                setPasteUrl("");
                setNotice(
                  `Prepared for ${prepared.company} — PDFs saved to your AgentApplications folder. Review the card, then submit yourself.`,
                );
              })
            }
            disabled={busy || !pasteUrl.trim()}
            className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
          >
            Prepare
          </button>
        </div>

        <div className="mb-8 flex flex-wrap gap-3">
          <button
            onClick={() => run(() => api.discover())}
            disabled={busy}
            className="rounded-md border border-neutral-300 px-3 py-2 text-sm font-medium hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-900"
          >
            Find jobs
          </button>
          <button
            onClick={() => run(() => api.scoreMatches(10))}
            disabled={busy}
            className="rounded-md border border-neutral-300 px-3 py-2 text-sm font-medium hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-900"
          >
            Score matches
          </button>
          {busy && <span className="self-center text-sm text-neutral-500">Working…</span>}
        </div>

        <section className="mb-10 grid gap-4 md:grid-cols-3 xl:grid-cols-6">
          {COLUMNS.map((column) => {
            const cards = (board?.applications ?? []).filter(
              (a) => a.status === column.status,
            );
            return (
              <div key={column.status}>
                <h2 className="mb-2 flex items-baseline justify-between text-xs font-semibold uppercase tracking-wide text-neutral-500">
                  {column.label}
                  <span className="tabular-nums">{cards.length}</span>
                </h2>
                <div className="flex flex-col gap-2">
                  {cards.map((application) => (
                    <Card
                      key={application.id}
                      application={application}
                      busy={busy}
                      onTransition={(status) =>
                        run(() => api.transitionApplication(application.id, status))
                      }
                    />
                  ))}
                  {cards.length === 0 && (
                    <p className="rounded-md border border-dashed border-neutral-300 px-3 py-4 text-center text-xs text-neutral-400 dark:border-neutral-800">
                      empty
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </section>

        <section>
          <h2 className="text-lg font-semibold tracking-tight">Matched jobs</h2>
          <p className="mt-1 mb-4 text-sm text-neutral-600 dark:text-neutral-400">
            Ranked by fit. Track one to start an application.
          </p>
          <div className="flex flex-col gap-3">
            {untracked.slice(0, 20).map((match) => (
              <div
                key={match.id}
                className="rounded-md border border-neutral-200 p-3 dark:border-neutral-800"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="truncate font-medium">
                      {match.job_posting.title}
                    </p>
                    <p className="text-xs text-neutral-500">
                      {match.job_posting.company}
                      {match.job_posting.location
                        ? ` · ${match.job_posting.location}`
                        : ""}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    <Score value={match.final_score} scored={match.reasoning !== null} />
                    <button
                      onClick={() => run(() => api.trackApplication(match.id))}
                      disabled={busy}
                      className="rounded-md bg-neutral-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
                    >
                      Track
                    </button>
                  </div>
                </div>
                {match.reasoning && (
                  <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
                    {match.reasoning}
                  </p>
                )}
                {match.missing_skills.length > 0 && (
                  <p className="mt-1 text-xs text-neutral-500">
                    Gaps: {match.missing_skills.slice(0, 5).join(", ")}
                  </p>
                )}
              </div>
            ))}
            {untracked.length === 0 && (
              <p className="text-sm text-neutral-500">
                No untracked matches. Run “Find jobs” to pull new postings.
              </p>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

function Card({
  application,
  busy,
  onTransition,
}: {
  application: Application;
  busy: boolean;
  onTransition: (status: ApplicationStatus) => void;
}) {
  const actions = NEXT_ACTIONS[application.status] ?? [];
  return (
    <div className="rounded-md border border-neutral-200 p-3 text-sm dark:border-neutral-800">
      <p className="font-medium leading-snug">{application.job_posting.title}</p>
      <p className="text-xs text-neutral-500">{application.job_posting.company}</p>

      {application.status === "ready_for_review" && (
        <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">
          Review the documents before submitting.
        </p>
      )}
      {application.approved_by_user_at && (
        <p className="mt-2 text-xs text-neutral-500">
          You approved this on{" "}
          {new Date(application.approved_by_user_at).toLocaleDateString()}
        </p>
      )}

      <div className="mt-3 flex flex-wrap gap-1.5">
        {actions.map((next) => (
          <button
            key={next}
            onClick={() => onTransition(next)}
            disabled={busy}
            className="rounded border border-neutral-300 px-2 py-1 text-xs hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-900"
          >
            {LABELS[next] ?? next}
          </button>
        ))}
      </div>
    </div>
  );
}

function Score({ value, scored }: { value: number; scored: boolean }) {
  if (!scored) {
    return <span className="text-xs text-neutral-400">unscored</span>;
  }
  const tone =
    value >= 65
      ? "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300"
      : value >= 40
        ? "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
        : "bg-neutral-200 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300";
  return (
    <span className={`rounded px-2 py-1 text-xs font-medium tabular-nums ${tone}`}>
      {Math.round(value)}
    </span>
  );
}
