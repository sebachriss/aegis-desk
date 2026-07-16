"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Loader2, Bot, User as UserIcon, Info } from "lucide-react";
import { sendChat, type ChatResponse } from "@/lib/api";
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
  const [showMetadata, setShowMetadata] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const query = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: query }]);
    setLoading(true);

    try {
      const res = await sendChat(query);
      setMessages((prev) => [...prev, { role: "assistant", content: res.respuesta, metadata: res }]);

      if (res.requires_hitl) {
        toast.warning("Esta acción requiere aprobación humana. Ve a Aprobaciones.");
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Error desconocido";
      if (msg === "Sesión expirada") {
        toast.error("Sesión expirada. Cierra sesión y vuelve a iniciar.");
      } else {
        toast.error(msg);
      }
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `❌ Error: ${msg}` },
      ]);
    } finally {
      setLoading(false);
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
                  className="rounded-full border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted transition-colors"
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
            <Card className="p-3.5">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
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
