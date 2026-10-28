import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import "./index.css";
import { ApiError } from "./lib/api";
import { AuthProvider, useAuth } from "./lib/auth";
import { LiveProvider } from "./lib/live";
import type { Role } from "./lib/types";
import { Agents } from "./pages/Agents";
import { Approvals } from "./pages/Approvals";
import { Arena } from "./pages/Arena";
import { Audit } from "./pages/Audit";
import { Directory } from "./pages/Directory";
import { Login } from "./pages/Login";
import { Model } from "./pages/Model";
import { Overview } from "./pages/Overview";
import { Payments, PaymentDetail } from "./pages/Payments";
import { Playground } from "./pages/Playground";
import { Policies } from "./pages/Policies";
import { Team } from "./pages/Team";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: true,
      // Retry network blips, never auth/validation errors.
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
    },
  },
});

function RequireAuth({ children, role }: { children: ReactNode; role?: Role }) {
  const { operator, loading, can } = useAuth();
  const location = useLocation();
  if (loading) return <Spinner label="Signing in" />;
  if (!operator) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  if (role && !can(role)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

function App() {
  const { operator } = useAuth();
  return (
    <LiveProvider enabled={!!operator}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<RequireAuth><Layout /></RequireAuth>}>
          <Route index element={<Overview />} />
          <Route path="payments" element={<Payments />} />
          <Route path="payments/:requestId" element={<PaymentDetail />} />
          <Route path="approvals" element={<Approvals />} />
          <Route path="playground" element={<Playground />} />
          <Route path="arena" element={<Arena />} />
          <Route path="model" element={<Model />} />
          <Route path="policies" element={<Policies />} />
          <Route path="agents" element={<Agents />} />
          <Route path="directory" element={<Directory />} />
          <Route path="team" element={<RequireAuth role="admin"><Team /></RequireAuth>} />
          <Route path="audit" element={<Audit />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </LiveProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
