"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { api, clearToken, getToken, setToken } from "./api";
import type { User } from "./types";

interface AuthState {
  user: User | null;
  /** True until the stored token has been checked against the API. */
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (
    email: string,
    password: string,
    fullName?: string,
  ) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  // A token in localStorage only means we had one — it may be expired or
  // signed with a rotated secret. Confirm it before trusting it.
  useEffect(() => {
    let active = true;

    void (async () => {
      try {
        if (getToken()) {
          const me = await api.me();
          if (active) setUser(me);
        }
      } catch {
        clearToken();
      } finally {
        if (active) setLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const token = await api.login(email, password);
      setToken(token.access_token);
      setUser(token.user);
      router.push("/dashboard");
    },
    [router],
  );

  const register = useCallback(
    async (email: string, password: string, fullName?: string) => {
      const token = await api.register(email, password, fullName);
      setToken(token.access_token);
      setUser(token.user);
      router.push("/dashboard");
    },
    [router],
  );

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
    router.push("/login");
  }, [router]);

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
