import posthog from "posthog-js";

// The project token is a public browser ingestion key, not a personal API key.
const projectToken = import.meta.env.VITE_POSTHOG_PROJECT_TOKEN || "phc_r8rwNrrHXFEnBTXJm5XbgXbFrt4oicJsCo6wF8btwMUa";
const apiHost = import.meta.env.VITE_POSTHOG_HOST || "https://us.i.posthog.com";
const enabled = import.meta.env.PROD && Boolean(projectToken && apiHost);

export function initAnalytics() {
  if (!enabled) return;
  posthog.init(projectToken, {
    api_host: apiHost,
    autocapture: true,
    capture_pageview: true,
    person_profiles: "identified_only",
    disable_session_recording: true,
  });
  posthog.register({ platform: import.meta.env.VITE_MOBILE_APP === "true" ? "android" : "web" });
}

export function setReaderName(name) {
  if (!enabled) return;
  const normalized = String(name || "").trim();
  if (normalized) posthog.register({ reader_name: normalized });
  else posthog.unregister("reader_name");
}

export function resetAnalytics() {
  if (!enabled) return;
  posthog.reset();
  posthog.register({ platform: import.meta.env.VITE_MOBILE_APP === "true" ? "android" : "web" });
}

export function captureEvent(name, properties = {}) {
  if (enabled) posthog.capture(name, properties);
}

export function startActiveTimeTracking() {
  if (!enabled || typeof document === "undefined") return () => {};

  let visible = document.visibilityState === "visible";
  let activeSeconds = 0;
  let lastActivity = Date.now();

  const markActivity = () => {
    lastActivity = Date.now();
  };

  const flush = () => {
    if (!visible || Date.now() - lastActivity > 30_000) return;
    activeSeconds += 10;
    posthog.capture("reader_active", { active_seconds: 10, total_active_seconds: activeSeconds });
  };

  const handleVisibility = () => {
    if (document.visibilityState === "hidden") {
      if (visible) posthog.capture("$pageleave", { active_seconds: activeSeconds });
      visible = false;
      return;
    }
    visible = true;
    markActivity();
  };

  const interval = window.setInterval(flush, 10_000);
  const activityEvents = ["pointerdown", "keydown", "scroll", "touchstart"];
  activityEvents.forEach((eventName) => window.addEventListener(eventName, markActivity, { passive: true }));
  document.addEventListener("visibilitychange", handleVisibility);

  return () => {
    window.clearInterval(interval);
    activityEvents.forEach((eventName) => window.removeEventListener(eventName, markActivity));
    document.removeEventListener("visibilitychange", handleVisibility);
    if (visible) posthog.capture("$pageleave", { active_seconds: activeSeconds });
  };
}
