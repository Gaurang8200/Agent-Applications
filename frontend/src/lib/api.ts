import type {
  Application,
  ApplicationDetail,
  ApplicationStatus,
  Board,
  JobMatch,
  Profile,
  Resume,
  ResumeUploadResponse,
  Token,
  User,
} from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "agentapp.token";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  // Let the browser set the multipart boundary itself for FormData bodies.
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(
      `Cannot reach the API at ${BASE_URL}. Is the backend running?`,
      0,
    );
  }

  if (!response.ok) {
    throw new ApiError(await readErrorDetail(response), response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    // FastAPI validation errors arrive as a list of {loc, msg} objects.
    if (Array.isArray(detail)) {
      return detail.map((d) => d?.msg ?? JSON.stringify(d)).join("; ");
    }
  } catch {
    // Fall through to the generic message below.
  }
  return `Request failed (${response.status})`;
}

export const api = {
  register: (email: string, password: string, fullName?: string) =>
    request<Token>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email,
        password,
        full_name: fullName || null,
      }),
    }),

  login: (email: string, password: string) =>
    request<Token>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  me: () => request<User>("/api/v1/auth/me"),

  changePassword: (currentPassword: string, newPassword: string) =>
    request<void>("/api/v1/auth/password", {
      method: "POST",
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    }),

  getProfile: () => request<Profile>("/api/v1/profile"),

  updateProfile: (patch: Partial<Profile>) =>
    request<Profile>("/api/v1/profile", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  applyParsed: (resumeId: string) =>
    request<Profile>(`/api/v1/profile/apply-parsed/${resumeId}`, {
      method: "POST",
    }),

  listResumes: () => request<Resume[]>("/api/v1/resumes"),

  uploadResume: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ResumeUploadResponse>("/api/v1/resumes", {
      method: "POST",
      body: form,
    });
  },

  listMatches: () => request<JobMatch[]>("/api/v1/jobs/matches"),

  discover: () => request<unknown>("/api/v1/discover", { method: "POST", body: "{}" }),

  scoreMatches: (limit = 10) =>
    request<unknown>("/api/v1/jobs/score", {
      method: "POST",
      body: JSON.stringify({ limit }),
    }),

  getBoard: () => request<Board>("/api/v1/tracker/board"),

  trackApplication: (matchId: string) =>
    request<Application>("/api/v1/tracker/applications", {
      method: "POST",
      body: JSON.stringify({ match_id: matchId }),
    }),

  getApplication: (id: string) =>
    request<ApplicationDetail>(`/api/v1/tracker/applications/${id}`),

  prepareFromUrl: (url: string, company?: string) =>
    request<{ company: string; cv_pdf: string; anschreiben_pdf: string; compliant: boolean }>(
      "/api/v1/applications/prepare-from-url",
      {
        method: "POST",
        body: JSON.stringify({ url, company: company || null }),
      },
    ),

  transitionApplication: (id: string, status: ApplicationStatus, message?: string) =>
    request<ApplicationDetail>(`/api/v1/tracker/applications/${id}/transition`, {
      method: "POST",
      body: JSON.stringify({ status, message: message ?? null }),
    }),
};
