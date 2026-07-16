"use client";

import { createContext, useContext, useState, ReactNode } from "react";
import { useRouter } from "next/navigation";
import { login as apiLogin, type User } from "@/lib/api";

interface AuthContextType {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("aegis_token");
    }
    return null;
  });
  const [user, setUser] = useState<User | null>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("aegis_user");
      return saved ? JSON.parse(saved) : null;
    }
    return null;
  });
  const [isLoading] = useState(false);
  const router = useRouter();

  const login = async (username: string, password: string) => {
    const res = await apiLogin(username, password);
    const userData: User = {
      username,
      role: res.role,
      display_name: res.display_name,
    };
    localStorage.setItem("aegis_token", res.access_token);
    localStorage.setItem("aegis_user", JSON.stringify(userData));
    setToken(res.access_token);
    setUser(userData);
    router.push("/dashboard");
  };

  const logout = () => {
    localStorage.removeItem("aegis_token");
    localStorage.removeItem("aegis_user");
    setToken(null);
    setUser(null);
    router.push("/login");
  };

  return (
    <AuthContext.Provider value={{ user, token, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
