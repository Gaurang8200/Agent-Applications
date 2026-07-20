// Mirrors app/schemas/profile.py and app/schemas/auth.py on the API side.
// Keep these in sync when the Pydantic models change.

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  created_at: string;
}

export interface Token {
  access_token: string;
  token_type: string;
  user: User;
}

export interface WorkExperience {
  id?: string;
  company: string;
  title: string;
  location: string | null;
  start_date: string | null;
  end_date: string | null;
  is_current: boolean;
  highlights: string[];
  display_order: number;
}

export interface Education {
  id?: string;
  institution: string;
  degree: string | null;
  field_of_study: string | null;
  start_date: string | null;
  end_date: string | null;
  grade: string | null;
  display_order: number;
}

export interface Skill {
  id?: string;
  name: string;
  category: string | null;
  years: number | null;
}

export interface Profile {
  id: string;
  user_id: string;
  headline: string | null;
  summary: string | null;
  location: string | null;
  phone: string | null;
  links: Record<string, string>;
  years_experience: number | null;
  desired_roles: string[];
  desired_locations: string[];
  remote_ok: boolean;
  min_salary: number | null;
  requires_sponsorship: boolean | null;
  work_experience: WorkExperience[];
  education: Education[];
  skills: Skill[];
  created_at: string;
  updated_at: string;
}

export interface ParsedResume {
  full_name: string | null;
  email: string | null;
  phone: string | null;
  location: string | null;
  headline: string | null;
  summary: string | null;
  links: Record<string, string>;
  work_experience: WorkExperience[];
  education: Education[];
  skills: Skill[];
  extraction_method: "llm" | "heuristic";
  confidence: number | null;
}

export interface Resume {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  parse_status: "pending" | "parsed" | "failed";
  parse_error: string | null;
  is_primary: boolean;
  created_at: string;
}

export interface ResumeUploadResponse {
  resume: Resume;
  parsed: ParsedResume | null;
}
