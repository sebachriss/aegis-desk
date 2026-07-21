"use client";

import { useState } from "react";
import { Shield, Loader2 } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";

export default function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(username, password);
      toast.success("Bienvenido a Aegis Desk");
    } catch {
      toast.error("Usuario o contraseña incorrectos");
    } finally {
      setLoading(false);
    }
  };

  const fillDemo = (user: string, pass: string) => {
    setUsername(user);
    setPassword(pass);
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-background via-background to-muted/50">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-3 text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-xl bg-primary/10">
            <Shield className="h-7 w-7 text-primary" />
          </div>
          <div>
            <CardTitle className="text-2xl">Aegis Desk</CardTitle>
            <CardDescription className="mt-1">
              Plataforma de soporte interno inteligente
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="username">Usuario</Label>
              <Input
                id="username"
                type="text"
                placeholder="ana.garcia"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Contraseña</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Iniciando sesión...
                </>
              ) : (
                "Iniciar sesión"
              )}
            </Button>
          </form>

          <div className="mt-6 rounded-lg border bg-muted/50 p-4">
            <p className="mb-2 text-xs font-medium text-muted-foreground">
              Usuarios de prueba (click para autocompletar):
            </p>
            <div className="space-y-1.5">
              <button
                onClick={() => fillDemo("ana.garcia", "ana123")}
                className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-xs hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none transition-colors"
              >
                <span className="font-mono">ana.garcia</span>
                <span className="text-muted-foreground">empleado</span>
              </button>
              <button
                onClick={() => fillDemo("carlos.lopez", "carlos123")}
                className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-xs hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none transition-colors"
              >
                <span className="font-mono">carlos.lopez</span>
                <span className="text-muted-foreground">empleado</span>
              </button>
              <button
                onClick={() => fillDemo("admin.aegis", "admin123")}
                className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-xs hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none transition-colors"
              >
                <span className="font-mono">admin.aegis</span>
                <span className="text-muted-foreground">admin</span>
              </button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
