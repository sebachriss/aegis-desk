// API client for Aegis Desk backend.

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface User {
  username: string;
  role: string;
  display_name: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  role: string;
  display_name: string;
}

export interface ChatResponse {
  thread_id: string;
  intencion: string;
  respuesta: string;
  confidence: number;
  fuentes: Source[];
  elapsed_seconds: number;
  requires_hitl: boolean;
}

export interface Source {
  source: string;
  content: string;
}

export interface Stats {
  total: number;
  avg_confidence: number;
  avg_elapsed: number;
  blocked: number;
  total_retries: number;
  by_intencion: Record<string, { count: number; avg_confidence: number }>;
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("aegis_token");
}

function authHeaders(): HeadersInit {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const res = await fetch(`${API_URL}/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error("Usuario o contraseña incorrectos");
  return res.json();
}

export async function getMe(): Promise<User> {
  const res = await fetch(`${API_URL}/me`, { headers: authHeaders() });
  if (!res.ok) throw new Error("No autenticado");
  return res.json();
}

export async function sendChat(query: string): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ query }),
  });
  if (res.status === 401) throw new Error("Sesión expirada");
  if (!res.ok) throw new Error("Error en el chat");
  return res.json();
}

export async function approveHitl(threadId: string): Promise<{ thread_id: string; decision: string; respuesta: string }> {
  const res = await fetch(`${API_URL}/hitl/${threadId}/approve`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (res.status === 403) throw new Error("No tienes permisos de admin");
  if (!res.ok) throw new Error("Error al aprobar");
  return res.json();
}

export async function rejectHitl(threadId: string): Promise<{ thread_id: string; decision: string; respuesta: string }> {
  const res = await fetch(`${API_URL}/hitl/${threadId}/reject`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (res.status === 403) throw new Error("No tienes permisos de admin");
  if (!res.ok) throw new Error("Error al rechazar");
  return res.json();
}

export async function getStats(): Promise<Stats> {
  const res = await fetch(`${API_URL}/stats`, { headers: authHeaders() });
  if (!res.ok) throw new Error("Error al obtener stats");
  return res.json();
}

export async function getHealth(): Promise<{ status: string; service: string; langsmith_tracing: boolean }> {
  const res = await fetch(`${API_URL}/health`);
  if (!res.ok) throw new Error("API no disponible");
  return res.json();
}
