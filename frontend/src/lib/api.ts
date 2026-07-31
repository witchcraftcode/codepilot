const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || "Request failed");
  }
  return res.json();
}

export const api = {
  health: () => request<{ status: string }>("/../health".replace("/api/v1/../", "/")),

  listRepositories: () => request<{ repositories: Repository[]; total: number }>("/repository"),

  createRepository: (github_url: string, branch?: string) =>
    request<Repository>("/repository", {
      method: "POST",
      body: JSON.stringify({ github_url, branch }),
    }),

  getRepository: (id: string) => request<Repository>(`/repository/${id}`),

  createReview: (repository_id: string, review_type = "full") =>
    request<Review>("/review", {
      method: "POST",
      body: JSON.stringify({ repository_id, review_type }),
    }),

  getReview: (id: string) => request<ReviewDetail>(`/review/${id}`),

  getHistory: (repository_id?: string) =>
    request<{ reviews: Review[]; total: number }>(
      `/history${repository_id ? `?repository_id=${repository_id}` : ""}`
    ),

  chat: (repository_id: string, message: string, conversation_id?: string) =>
    request<ChatResponse>("/chat", {
      method: "POST",
      body: JSON.stringify({ repository_id, message, conversation_id }),
    }),

  getScores: (repository_id: string) =>
    request<ScoresResponse>(`/scores/${repository_id}`),

  securityAudit: (repository_id: string) =>
    request<Review>("/security", {
      method: "POST",
      body: JSON.stringify({ repository_id }),
    }),
};

export interface Repository {
  id: string;
  github_url: string;
  name: string;
  full_name: string;
  status: string;
  languages: Record<string, number> | null;
  frameworks: string[] | null;
  file_count: number;
  chunk_count: number;
  health_score: number | null;
  overview: string | null;
  created_at: string;
  indexed_at: string | null;
}

export interface Review {
  id: string;
  repository_id: string;
  review_type: string;
  status: string;
  overall_score: number | null;
  summary: string | null;
  top_issues: Array<{ title: string; severity: string; agent: string }> | null;
  tokens_used: number;
  duration_ms: number | null;
  created_at: string;
  completed_at: string | null;
}

export interface ReviewDetail extends Review {
  agent_results: Array<{
    agent_name: string;
    score: number | null;
    findings: Array<{
      id: string;
      severity: string;
      category: string;
      title: string;
      description: string;
      file_path: string | null;
      suggestion: string | null;
    }>;
    summary: string | null;
  }>;
  report: Record<string, unknown> | null;
}

export interface ChatResponse {
  conversation_id: string;
  message: string;
  sources: Array<{
    file_path: string;
    chunk_type: string;
    symbol_name: string | null;
    relevance_score: number;
  }>;
}

export interface ScoresResponse {
  repository_id: string;
  health_score: {
    security: number;
    performance: number;
    architecture: number;
    documentation: number;
    testing: number;
    maintainability: number;
    overall: number;
  };
  last_review_at: string | null;
}
