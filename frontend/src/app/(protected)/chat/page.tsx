"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Loader2, Bot, User as UserIcon, Info } from "lucide-react";
import { chatStream, sendChat, type ChatResponse } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";

interface Message {
  role: "user" | "assistant";
  content: string;
  metadata?: ChatResponse;
}

export default function ChatPage() {
  const { user } = useAuth();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [activeNode, setActiveNode] = useState<string | null>(null);
  const [showMetadata, setShowMetadata] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, activeNode]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const query = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: query }]);
    setLoading(true);
    setActiveNode(null);

    const assistantIndex = messages.length + 1;
    setMessages((prev) => [
      ...prev,
      { role: "assistant", content: "", metadata: undefined },
    ]);

    const controller = new AbortController();
    abortRef.current = controller;
    let receivedToken = false;

    try {
      const res = await chatStream(
        query,
        {
          onNode: (payload) => {
            setActiveNode(payload.label);
          },
          onToken: (payload) => {
            receivedToken = true;
            setMessages((prev) => {
              const next = [...prev];
              if (next[assistantIndex]?.role === "assistant") {
                next[assistantIndex] = {
                  ...next[assistantIndex],
                  content: next[assistantIndex].content + payload.token,
                };
              }
              return next;
            });
          },
          onInterrupt: (payload) => {
            toast.warning(`Aprobación requerida (thread ${payload.thread_id}). Ve a Aprobaciones.`);
          },
          onDone: (payload) => {
            setMessages((prev) => {
              const next = [...prev];
              if (next[assistantIndex]?.role === "assistant") {
                next[assistantIndex] = {
                  ...next[assistantIndex],
                  content: payload.respuesta,
                  metadata: payload,
                };
              }
              return next;
            });
            if (payload.requires_hitl) {
              toast.warning("Esta acción requiere aprobación humana. Ve a Aprobaciones.");
            }
          },
        },
        controller.signal
      );
      setMessages((prev) => {
        const next = [...prev];
        if (next[assistantIndex]?.role === "assistant") {
          next[assistantIndex] = { ...next[assistantIndex], metadata: res };
        }
        return next;
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Error desconocido";
      // Fallback a /chat si el streaming falla antes del primer token o hay error
      try {
        const res = await sendChat(query);
        setMessages((prev) => {
          const next = [...prev];
          if (next[assistantIndex]?.role === "assistant") {
            next[assistantIndex] = {
              ...next[assistantIndex],
              content: res.respuesta,
              metadata: res,
            };
          }
          return next;
        });
        if (res.requires_hitl) {
          toast.warning("Esta acción requiere aprobación humana. Ve a Aprobaciones.");
        }
      } catch {
        if (msg === "Sesión expirada") {
          toast.error("Sesión expirada. Cierra sesión y vuelve a iniciar.");
        } else if (receivedToken) {
          toast.error("El stream se interrumpió. Inténtalo de nuevo.");
        } else {
          toast.error(msg);
        }
        setMessages((prev) => {
          const next = [...prev];
          if (next[assistantIndex]?.role === "assistant") {
            next[assistantIndex] = { ...next[assistantIndex], content: `❌ Error: ${msg}` };
          }
          return next;
        });
      }
    } finally {
      setLoading(false);
      setActiveNode(null);
      abortRef.current = null;
    }
  };

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <div className="border-b px-8 py-4">
        <h1 className="text-xl font-bold tracking-tight">Chat con Aegis</h1>
        <p className="text-sm text-muted-foreground">
          Conectado como <strong>{user?.display_name}</strong> ({user?.role})
        </p>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-8 py-6 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center space-y-3">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10">
              <Bot className="h-8 w-8 text-primary" />
            </div>
            <div>
              <p className="text-lg font-medium">Bienvenido a Aegis Desk</p>
              <p className="text-sm text-muted-foreground max-w-md">
                Puedes preguntar sobre políticas de RRHH, crear tickets, consultar datos (si eres admin), y más.
              </p>
            </div>
            <div className="flex flex-wrap gap-2 justify-center max-w-lg">
              {["¿Cuántos días de vacaciones tengo?", "Crea un ticket de alta prioridad", "¿Qué dice el manual sobre seguridad?"].map((s) => (
                <button
                  key={s}
                  onClick={() => setInput(s)}
                  className="rounded-full border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none transition-[color,background-color,border-color,transform] active:scale-[0.96]"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            {msg.role === "assistant" && (
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                <Bot className="h-5 w-5 text-primary" />
              </div>
            )}
            <div className={`max-w-[70%] space-y-2 ${msg.role === "user" ? "items-end" : "items-start"}`}>
              <Card className={`p-3.5 ${msg.role === "user" ? "bg-primary text-primary-foreground" : "bg-card"}`}>
                <p className="text-sm whitespace-pre-wrap leading-relaxed">{msg.content}</p>
              </Card>
              {msg.metadata && (
                <div className="flex items-center gap-2 text-xs">
                  <button
                    onClick={() => setShowMetadata(showMetadata === msg.content ? null : msg.content)}
                    className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <Info className="h-3 w-3" />
                    Detalles
                  </button>
                  <Badge variant="secondary" className="text-xs">
                    {msg.metadata.intencion}
                  </Badge>
                  <span className="text-muted-foreground tabular-nums">
                    {msg.metadata.confidence.toFixed(2)} · {msg.metadata.elapsed_seconds}s
                  </span>
                </div>
              )}
              {showMetadata === msg.content && msg.metadata && (
                <div className="rounded-lg border bg-muted/50 p-3 text-xs space-y-1">
                  <div><strong>thread_id:</strong> <code className="text-muted-foreground">{msg.metadata.thread_id}</code></div>
                  <div><strong>confidence:</strong> {msg.metadata.confidence}</div>
                  <div><strong>elapsed:</strong> {msg.metadata.elapsed_seconds}s</div>
                  <div><strong>fuentes:</strong> {msg.metadata.fuentes.length}</div>
                  {msg.metadata.fuentes.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {msg.metadata.fuentes.map((f, j) => (
                        <div key={j} className="text-muted-foreground">
                          <strong>{f.source}:</strong> {f.content.slice(0, 80)}...
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
            {msg.role === "user" && (
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted">
                <UserIcon className="h-5 w-5 text-muted-foreground" />
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="flex gap-3 justify-start">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10">
              <Bot className="h-5 w-5 text-primary" />
            </div>
            <Card className="p-3.5 flex items-center gap-3">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              {activeNode ? (
                <span className="text-sm text-muted-foreground">{activeNode}</span>
              ) : null}
            </Card>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t px-8 py-4">
        <form onSubmit={handleSend} className="flex gap-2 max-w-3xl mx-auto">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Escribe tu consulta..."
            disabled={loading}
            className="flex-1"
          />
          <Button type="submit" disabled={loading || !input.trim()}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Enviar
          </Button>
        </form>
      </div>
    </div>
  );
}
