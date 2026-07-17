"use client";

import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { useRouter } from "next/navigation";
import { login as apiLogin, logout as apiLogout, getMe, type User } from "@/lib/api";

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();

  // Validar sesion al cargar la aplicacion (token en cookie HttpOnly)
  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((u) => {
        if (!cancelled) setUser(u);
      })
      .catch(() => {
        if (!cancelled) {
          setUser(null);
          router.push("/login");
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => { cancelled = true; };
  }, [router]);

  // Cerrar sesión automáticamente si alguna API devuelve 401
  useEffect(() => {
    if (typeof window === "undefined") return;
    const handleUnauthorized = () => {
      setUser(null);
      router.push("/login");
    };
    window.addEventListener("aegis-unauthorized", handleUnauthorized);
    return () => window.removeEventListener("aegis-unauthorized", handleUnauthorized);
  }, [router]);

  const login = async (username: string, password: string) => {
    const res = await apiLogin(username, password);
    const userData: User = {
      username,
      role: res.role,
      display_name: res.display_name,
    };
    setUser(userData);
    router.push("/dashboard");
  };

  const logout = async () => {
    await apiLogout();
    setUser(null);
    router.push("/login");
  };

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
