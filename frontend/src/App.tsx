import { useEffect } from "react";

import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { Toasts } from "./components/Toasts";
import { Lightbox } from "./components/Lightbox";
import { SettingsPanel } from "./components/SettingsPanel";
import { DocumentView } from "./views/DocumentView";
import { Library } from "./views/Library";
import { useHashRoute } from "./hooks/useHashRoute";
import { useApp } from "./store";

export function App() {
  const route = useHashRoute();
  const bootstrap = useApp((s) => s.bootstrap);
  const openDocument = useApp((s) => s.openDocument);
  const closeDocument = useApp((s) => s.closeDocument);
  const doc = useApp((s) => s.doc);
  const settingsOpen = route.name === "settings";

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    if (route.name === "doc" && route.id) {
      if (doc?.id !== route.id) void openDocument(route.id);
    } else if (doc) {
      closeDocument();
    }
  }, [route, doc, openDocument, closeDocument]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-paper text-ink">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="min-h-0 min-w-0 flex-1 overflow-hidden">
          {route.name === "doc" && doc ? (
            <DocumentView />
          ) : doc ? (
            <div className="flex h-full items-center justify-center text-sm text-ink-2">
              正在加载文献…
            </div>
          ) : (
            <Library />
          )}
        </main>
      </div>
      {settingsOpen && <SettingsPanel />}
      <Lightbox />
      <Toasts />
    </div>
  );
}
