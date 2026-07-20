"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ChangeEvent } from "react";

import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { ParsedResume, Profile, Resume } from "@/lib/types";

export default function DashboardPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();

  const [profile, setProfile] = useState<Profile | null>(null);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [parsed, setParsed] = useState<ParsedResume | null>(null);
  const [parsedResumeId, setParsedResumeId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  const refresh = useCallback(async () => {
    try {
      const [nextProfile, nextResumes] = await Promise.all([
        api.getProfile(),
        api.listResumes(),
      ]);
      setProfile(nextProfile);
      setResumes(nextResumes);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load data.");
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    let active = true;

    void (async () => {
      await refresh();
      // Nothing to commit here; refresh() owns its own state writes. The guard
      // exists so a late failure after unmount stays silent.
      if (!active) return;
    })();

    return () => {
      active = false;
    };
  }, [user, refresh]);

  async function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    // Reset immediately so re-selecting the same file still fires onChange.
    event.target.value = "";
    if (!file) return;

    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.uploadResume(file);
      if (result.resume.parse_status === "failed") {
        setError(result.resume.parse_error ?? "Could not parse that file.");
        setParsed(null);
        setParsedResumeId(null);
      } else {
        setParsed(result.parsed);
        setParsedResumeId(result.resume.id);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleApply() {
    if (!parsedResumeId) return;
    setBusy(true);
    setError(null);
    try {
      const next = await api.applyParsed(parsedResumeId);
      setProfile(next);
      setParsed(null);
      setParsedResumeId(null);
      setNotice("Profile updated from your resume.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not apply.");
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

  return (
    <div className="flex flex-1 flex-col">
      <header className="flex items-center justify-between border-b border-neutral-200 px-6 py-4 dark:border-neutral-800">
        <div>
          <h1 className="font-semibold tracking-tight">Agent Applications</h1>
          <p className="text-xs text-neutral-500">{user.email}</p>
        </div>
        <button
          onClick={logout}
          className="text-sm text-neutral-600 underline underline-offset-4 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-100"
        >
          Sign out
        </button>
      </header>

      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-10">
        {error && <Banner tone="error">{error}</Banner>}
        {notice && <Banner tone="success">{notice}</Banner>}

        <Section
          title="Resume"
          description="Upload a PDF, DOCX, or TXT. Nothing is applied to your profile until you approve it."
        >
          <label className="inline-flex cursor-pointer items-center rounded-md bg-neutral-900 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300">
            {busy ? "Working…" : "Choose file"}
            <input
              type="file"
              accept=".pdf,.docx,.txt,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              onChange={handleUpload}
              disabled={busy}
              className="sr-only"
            />
          </label>

          {resumes.length > 0 && (
            <ul className="mt-4 flex flex-col gap-1 text-sm">
              {resumes.map((resume) => (
                <li
                  key={resume.id}
                  className="flex items-center gap-2 text-neutral-600 dark:text-neutral-400"
                >
                  <span className="truncate">{resume.filename}</span>
                  <StatusChip status={resume.parse_status} />
                  {resume.is_primary && (
                    <span className="text-xs text-neutral-500">primary</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Section>

        {parsed && (
          <Section
            title="Review extracted details"
            description="Check this against your resume before applying it. Applying replaces your existing work history, education, and skills."
          >
            {parsed.extraction_method === "heuristic" && (
              <Banner tone="warning">
                Parsed without AI — no <code>ANTHROPIC_API_KEY</code> is
                configured. Contact details and skills only; work history was
                not extracted. Add a key to <code>.env</code> and restart the
                API for full extraction.
              </Banner>
            )}

            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
              <Row label="Name" value={parsed.full_name} />
              <Row label="Email" value={parsed.email} />
              <Row label="Phone" value={parsed.phone} />
              <Row label="Location" value={parsed.location} />
              <Row label="Headline" value={parsed.headline} />
              <Row
                label="Links"
                value={Object.values(parsed.links).join(", ") || null}
              />
              <Row
                label="Skills"
                value={parsed.skills.map((s) => s.name).join(", ") || null}
              />
              <Row
                label="Roles"
                value={
                  parsed.work_experience.length
                    ? `${parsed.work_experience.length} found`
                    : null
                }
              />
            </dl>

            {parsed.work_experience.length > 0 && (
              <ul className="mt-4 flex flex-col gap-3 text-sm">
                {parsed.work_experience.map((role, index) => (
                  <li
                    key={`${role.company}-${index}`}
                    className="rounded-md border border-neutral-200 p-3 dark:border-neutral-800"
                  >
                    <p className="font-medium">
                      {role.title} · {role.company}
                    </p>
                    <p className="text-xs text-neutral-500">
                      {role.start_date ?? "?"} –{" "}
                      {role.is_current ? "Present" : (role.end_date ?? "?")}
                    </p>
                    {role.highlights.length > 0 && (
                      <ul className="mt-2 list-disc pl-5 text-neutral-600 dark:text-neutral-400">
                        {role.highlights.map((highlight, i) => (
                          <li key={i}>{highlight}</li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            )}

            <div className="mt-5 flex gap-3">
              <button
                onClick={handleApply}
                disabled={busy}
                className="rounded-md bg-neutral-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
              >
                Apply to profile
              </button>
              <button
                onClick={() => {
                  setParsed(null);
                  setParsedResumeId(null);
                }}
                disabled={busy}
                className="rounded-md border border-neutral-300 px-4 py-2.5 text-sm font-medium hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-900"
              >
                Discard
              </button>
            </div>
          </Section>
        )}

        <Section title="Profile" description="What the agent will use to match and tailor.">
          {profile ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
              <Row label="Headline" value={profile.headline} />
              <Row label="Location" value={profile.location} />
              <Row label="Phone" value={profile.phone} />
              <Row
                label="Skills"
                value={profile.skills.map((s) => s.name).join(", ") || null}
              />
              <Row
                label="Experience"
                value={
                  profile.work_experience.length
                    ? `${profile.work_experience.length} roles`
                    : null
                }
              />
            </dl>
          ) : (
            <p className="text-sm text-neutral-500">Loading…</p>
          )}
        </Section>
      </main>
    </div>
  );
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-10">
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      {description && (
        <p className="mt-1 mb-4 text-sm text-neutral-600 dark:text-neutral-400">
          {description}
        </p>
      )}
      {children}
    </section>
  );
}

function Row({ label, value }: { label: string; value: string | null }) {
  return (
    <>
      <dt className="text-neutral-500">{label}</dt>
      <dd className={value ? "" : "text-neutral-400 italic"}>
        {value ?? "not found"}
      </dd>
    </>
  );
}

function StatusChip({ status }: { status: Resume["parse_status"] }) {
  const tone =
    status === "parsed"
      ? "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300"
      : status === "failed"
        ? "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300"
        : "bg-neutral-200 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300";
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs ${tone}`}>{status}</span>
  );
}

function Banner({
  tone,
  children,
}: {
  tone: "error" | "success" | "warning";
  children: React.ReactNode;
}) {
  const styles = {
    error: "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300",
    success: "bg-green-50 text-green-800 dark:bg-green-950 dark:text-green-300",
    warning: "bg-amber-50 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  }[tone];
  return (
    <p className={`mb-6 rounded-md px-3 py-2 text-sm ${styles}`}>{children}</p>
  );
}
