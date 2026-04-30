import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { RealtimeProvider } from "./hooks/useRealtime";
import { AuthProvider, useAuth } from "./hooks/useAuth";
import { Shell } from "./shell";
import { OverviewScreen } from "./screens/overview";
import { DeployDetailScreen } from "./screens/deploy-detail";
import { DeployMetricsScreen } from "./screens/deploy-metrics";
import { ComponentLogsScreen } from "./screens/component-logs";
import { WizardScreen } from "./screens/wizard";
import { NodesScreen } from "./screens/nodes";
import { AdminScreen } from "./screens/admin";
import { SettingsScreen } from "./screens/settings";
import { LoginScreen } from "./screens/login";

const qc = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

function RequireAuth({ children }: { children: ReactNode }) {
  const { state } = useAuth();
  const loc = useLocation();
  if (state.status === "loading") {
    return <div className="cp-page"><div className="cp-skel" style={{ height: 120 }} /></div>;
  }
  if (state.status === "anonymous" || state.status === "needs-setup") {
    return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <AuthProvider>
          <RealtimeProvider>
            <Routes>
              <Route path="/login" element={<LoginScreen />} />
              <Route
                path="/*"
                element={
                  <RequireAuth>
                    <Shell>
                      <Routes>
                        <Route path="/" element={<OverviewScreen />} />
                        <Route path="/deploys" element={<OverviewScreen />} />
                        <Route path="/deploys/:id" element={<DeployDetailScreen />} />
                        <Route path="/deploys/:id/metrics" element={<DeployMetricsScreen />} />
                        <Route path="/components/:id/logs" element={<ComponentLogsScreen />} />
                        <Route path="/nodes" element={<NodesScreen />} />
                        <Route path="/wizard" element={<WizardScreen />} />
                        <Route path="/admin" element={<AdminScreen />} />
                        <Route path="/settings" element={<SettingsScreen />} />
                      </Routes>
                    </Shell>
                  </RequireAuth>
                }
              />
            </Routes>
          </RealtimeProvider>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
