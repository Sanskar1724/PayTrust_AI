import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api";
import type { Operator, Role } from "./types";

interface AuthState {
  operator: Operator | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  can: (role: Role) => boolean;
}

const RANK: Record<Role, number> = { viewer: 0, reviewer: 1, admin: 2 };
const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [operator, setOperator] = useState<Operator | null>(null);
  const [loading, setLoading] = useState(Boolean(getToken()));
  const queryClient = useQueryClient();

  const logout = useCallback(() => {
    setToken(null);
    setOperator(null);
    queryClient.clear();
  }, [queryClient]);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    if (!getToken()) return;
    api<Operator>("/v1/auth/me")
      .then(setOperator)
      .catch(() => logout())
      .finally(() => setLoading(false));
  }, [logout]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api<{ access_token: string; operator: Operator }>("/v1/auth/login", {
      method: "POST",
      body: { email, password },
    });
    setToken(res.access_token);
    setOperator(res.operator);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      operator,
      loading,
      login,
      logout,
      can: (role) => (operator ? RANK[operator.role] >= RANK[role] : false),
    }),
    [operator, loading, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
