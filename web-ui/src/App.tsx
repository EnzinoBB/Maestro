import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RealtimeProvider } from "./hooks/useRealtime";
import { Shell } from "./shell";
import { OverviewScreen } from "./screens/overview";
import { DeployDetailScreen } from "./screens/deploy-detail";
import { StubScreen } from "./screens/stub";

const qc = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <RealtimeProvider>
        <BrowserRouter>
          <Shell>
            <Routes>
              <Route path="/" element={<OverviewScreen />} />
              <Route path="/deploys" element={<OverviewScreen />} />
              <Route path="/deploys/:id" element={<DeployDetailScreen />} />
              <Route path="/nodes" element={<StubScreen title="Nodes" milestone="M2/M5" />} />
              <Route path="/wizard" element={<StubScreen title="Wizard" milestone="M3" />} />
              <Route path="/admin" element={<StubScreen title="Admin" milestone="M5" />} />
            </Routes>
          </Shell>
        </BrowserRouter>
      </RealtimeProvider>
    </QueryClientProvider>
  );
}
