import { useEffect, useState } from "react";

export type Route = { name: "library" } | { name: "settings" } | { name: "doc"; id: string };

function parse(hash: string): Route {
  const clean = hash.replace(/^#\/?/, "");
  if (clean.startsWith("doc/")) {
    const id = clean.slice(4).split("/")[0];
    if (id) return { name: "doc", id };
  }
  if (clean.startsWith("settings")) return { name: "settings" };
  return { name: "library" };
}

/** Minimal hash router: no dependency, works when served from any sub-path. */
export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));

  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  return route;
}

export function navigate(to: string) {
  window.location.hash = to;
}
