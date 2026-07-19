// API client for Aegis Desk backend.

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const AUTH_ERROR_EVENT = "aegis-unauthorized";

function emitUnauthorized() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(AUTH_ERROR_EVENT));
  }
}

export interface User {
  username: string;
  role: string;
  display_name: string;
}

export interface PendingItem {
  thread_id: string;
  query: string;
  intencion: string;
  tool_name?: string;
  risk_level?: string;
  requested_by?: string;
  created_at?: string;
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

export interface IntentionStats {
  count: number;
  avg_confidence: number;
  avg_elapsed?: number;
  latency_p50?: number;
  latency_p95?: number;
}

export interface HourlyRequest {
  hour: string;
  count: number;
}

export interface Stats {
  total: number;
  avg_confidence: number;
  avg_elapsed: number;
  latency_p50: number;
  latency_p95: number;
  blocked: number;
  total_retries: number;
  by_intencion: Record<string, IntentionStats>;
  security_blocks_by_type?: Record<string, number>;
  hitl_queue?: Record<string, number>;
  requests_per_hour?: HourlyRequest[];
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function authHeaders(): HeadersInit {
  return { "Content-Type": "application/json" };
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const res = await fetch(`${API_URL}/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
    credentials: "include",
  });
  if (!res.ok) throw new Error("Usuario o contraseña incorrectos");
  return res.json();
}

export async function logout(): Promise<void> {
  await fetch(`${API_URL}/logout`, {
    method: "POST",
    credentials: "include",
  });
}

export async function getMe(): Promise<User> {
  const res = await fetch(`${API_URL}/me`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) {
    emitUnauthorized();
    throw new Error("No autenticado");
  }
  if (!res.ok) throw new Error("No autenticado");
  return res.json();
}

export type SSEEventType = "node" | "token" | "interrupt" | "done" | "error";

export interface SSEEvent {
  type: SSEEventType;
  payload: unknown;
}

export interface StreamCallbacks {
  onNode?: (payload: { node: string; label: string }) => void;
  onToken?: (payload: { token: string }) => void;
  onInterrupt?: (payload: { thread_id: string; resumen: string }) => void;
  onDone?: (payload: ChatResponse) => void;
  onError?: (payload: { type: string; message: string }) => void;
}

/** Parser robusto de mensajes SSE: soporta múltiples eventos y líneas data multipartes. */
export function parseSSE(buffer: string): { events: SSEEvent[]; remainder: string } {
  const events: SSEEvent[] = [];
  // Los eventos SSE terminan con dos saltos de línea.
  const parts = buffer.split("\n\n");
  const remainder = parts.pop() || "";
  for (const part of parts) {
    if (!part.trim()) continue;
    let eventName = "message";
    const dataLines: string[] = [];
    for (const line of part.split("\n")) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }
    const data = dataLines.join("\n");
    try {
      const payload: unknown = data ? JSON.parse(data) : null;
      events.push({ type: eventName as SSEEventType, payload });
    } catch {
      events.push({ type: eventName as SSEEventType, payload: data });
    }
  }
  return { events, remainder };
}

export async function chatStream(
  query: string,
  callbacks: StreamCallbacks,
  signal?: AbortSignal
): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}/chat/stream`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ query }),
    credentials: "include",
    signal,
  });
  if (res.status === 401) {
    emitUnauthorized();
    throw new Error("Sesión expirada");
  }
  if (res.status === 429) {
    const retryAfter = res.headers.get("retry-after") || res.headers.get("Retry-After");
    throw new Error(`Rate limit. Intenta en ${retryAfter || "unos segundos"}s.`);
  }
  if (!res.ok) throw new Error("Error en el chat streaming");
  if (!res.body) throw new Error("El navegador no soporta streaming");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let donePayload: ChatResponse | null = null;
  let errorPayload: { type: string; message: string } | null = null;

  try {
    while (true) {
      if (signal?.aborted) {
        await reader.cancel();
        throw new Error("Cancelado");
      }
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const { events, remainder } = parseSSE(buffer);
      buffer = remainder;
      for (const event of events) {
        switch (event.type) {
          case "node":
            callbacks.onNode?.(event.payload as { node: string; label: string });
            break;
          case "token":
            callbacks.onToken?.(event.payload as { token: string });
            break;
          case "interrupt":
            callbacks.onInterrupt?.(event.payload as { thread_id: string; resumen: string });
            break;
          case "done":
            donePayload = event.payload as ChatResponse;
            callbacks.onDone?.(donePayload);
            break;
          case "error":
            errorPayload = event.payload as { type: string; message: string };
            callbacks.onError?.(errorPayload);
            break;
        }
      }
    }
  } finally {
    reader.releaseLock();
  }

  if (errorPayload) {
    throw new Error(errorPayload.message || "Error en el stream");
  }
  if (donePayload) {
    return donePayload;
  }
  throw new Error("Stream cerrado sin respuesta");
}

export async function sendChat(query: string): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ query }),
    credentials: "include",
  });
  if (res.status === 401) {
    emitUnauthorized();
    throw new Error("Sesión expirada");
  }
  if (res.status === 429) {
    const retryAfter = res.headers.get("retry-after") || res.headers.get("Retry-After");
    throw new Error(`Rate limit. Intenta en ${retryAfter || "unos segundos"}s.`);
  }
  if (!res.ok) throw new Error("Error en el chat");
  return res.json();
}

export async function getHitlPending(): Promise<PendingItem[]> {
  const res = await fetch(`${API_URL}/hitl/pending`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) {
    emitUnauthorized();
    throw new Error("Sesión expirada");
  }
  if (res.status === 403) throw new Error("No tienes permisos de admin");
  if (!res.ok) throw new Error("Error al obtener pendientes");
  return res.json();
}

export async function approveHitl(threadId: string): Promise<{ thread_id: string; decision: string; respuesta: string }> {
  const res = await fetch(`${API_URL}/hitl/${threadId}/approve`, {
    method: "POST",
    credentials: "include",
  });
  if (res.status === 401) {
    emitUnauthorized();
    throw new Error("Sesión expirada");
  }
  if (res.status === 403) throw new Error("No tienes permisos de admin");
  if (!res.ok) throw new Error("Error al aprobar");
  return res.json();
}

export async function rejectHitl(threadId: string): Promise<{ thread_id: string; decision: string; respuesta: string }> {
  const res = await fetch(`${API_URL}/hitl/${threadId}/reject`, {
    method: "POST",
    credentials: "include",
  });
  if (res.status === 401) {
    emitUnauthorized();
    throw new Error("Sesión expirada");
  }
  if (res.status === 403) throw new Error("No tienes permisos de admin");
  if (!res.ok) throw new Error("Error al rechazar");
  return res.json();
}

export async function getStats(): Promise<Stats> {
  const res = await fetch(`${API_URL}/stats`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) {
    emitUnauthorized();
    throw new ApiError(401, "Sesión expirada");
  }
  if (res.status === 403) {
    throw new ApiError(403, "No tienes permisos de admin");
  }
  if (!res.ok) throw new ApiError(res.status, "Error al obtener stats");
  return res.json();
}

export async function getHealth(): Promise<{ status: string; service: string; langsmith_tracing: boolean }> {
  const res = await fetch(`${API_URL}/health`, { credentials: "include" });
  if (!res.ok) throw new Error("API no disponible");
  return res.json();
}
