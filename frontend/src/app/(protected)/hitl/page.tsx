"use client";

import { useState, useEffect, useCallback } from "react";
import { Check, X, Clock, ShieldCheck } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { approveHitl, rejectHitl } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";

interface PendingItem {
  thread_id: string;
  query: string;
  intencion: string;
}

export default function HitlPage() {
  const { user } = useAuth();
  const [pending, setPending] = useState<PendingItem[]>([]);
  const [processing, setProcessing] = useState<string | null>(null);

  const addPending = useCallback((item: PendingItem) => {
    setPending((prev) => {
      if (prev.some((p) => p.thread_id === item.thread_id)) return prev;
      return [...prev, item];
    });
  }, []);

  // Expose addPending globally so chat page can add items
  useEffect(() => {
    if (typeof window !== "undefined") {
      (window as unknown as { __addPending?: (item: PendingItem) => void }).__addPending = addPending;
    }
  }, [addPending]);

  const handleApprove = async (threadId: string) => {
    setProcessing(threadId);
    try {
      const res = await approveHitl(threadId);
      toast.success(`Aprobado: ${res.respuesta.slice(0, 80)}`);
      setPending((prev) => prev.filter((p) => p.thread_id !== threadId));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error al aprobar");
    } finally {
      setProcessing(null);
    }
  };

  const handleReject = async (threadId: string) => {
    setProcessing(threadId);
    try {
      const res = await rejectHitl(threadId);
      toast.info(`Rechazado: ${res.respuesta.slice(0, 80)}`);
      setPending((prev) => prev.filter((p) => p.thread_id !== threadId));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error al rechazar");
    } finally {
      setProcessing(null);
    }
  };

  if (user?.role !== "admin") {
    return (
      <div className="p-8">
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted">
            <ShieldCheck className="h-8 w-8 text-muted-foreground" />
          </div>
          <h2 className="mt-4 text-lg font-semibold">Acceso restringido</h2>
          <p className="text-sm text-muted-foreground mt-1">
            Solo los administradores pueden aprobar o rechazar acciones.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Aprobaciones Pendientes</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Revisa y aprueba acciones sensibles detectadas por el sistema
        </p>
      </div>

      {pending.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-muted">
              <Clock className="h-7 w-7 text-muted-foreground" />
            </div>
            <p className="mt-4 text-lg font-medium">No hay acciones pendientes</p>
            <p className="text-sm text-muted-foreground mt-1">
              Las acciones que requieran aprobación aparecerán aquí.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {pending.map((item) => (
            <Card key={item.thread_id}>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-base">{item.query}</CardTitle>
                    <CardDescription className="mt-1">
                      Thread: <code className="text-xs">{item.thread_id}</code>
                    </CardDescription>
                  </div>
                  <Badge variant="secondary">{item.intencion}</Badge>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex gap-2">
                  <Button
                    onClick={() => handleApprove(item.thread_id)}
                    disabled={processing === item.thread_id}
                    size="sm"
                  >
                    <Check className="h-4 w-4" />
                    Aprobar
                  </Button>
                  <Button
                    onClick={() => handleReject(item.thread_id)}
                    disabled={processing === item.thread_id}
                    size="sm"
                    variant="destructive"
                  >
                    <X className="h-4 w-4" />
                    Rechazar
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
