import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { ChatView } from "./components/chat/ChatView";
import { GalaxyView } from "./components/galaxy/GalaxyView";
import { LibraryView } from "./components/library/LibraryView";
import { ResearchView } from "./components/research/ResearchView";
import { SystemView } from "./components/system/SystemView";

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<ChatView />} />
        <Route path="/chat/:sessionId" element={<ChatView />} />
        <Route path="/library" element={<LibraryView />} />
        <Route path="/galaxy" element={<GalaxyView />} />
        <Route path="/research" element={<ResearchView />} />
        <Route path="/system" element={<SystemView />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
