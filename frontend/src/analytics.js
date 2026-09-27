import posthog from "posthog-js";

// The project token is a public browser ingestion key, not a personal API key.
const projectToken = import.meta.env.VITE_POSTHOG_PROJECT_TOKEN || "phc_r8rwNrrHXFEnBTXJm5XbgXbFrt4oicJsCo6wF8btwMUa";
const apiHost = import.meta.env.VITE_POSTHOG_HOST || "https://us.i.posthog.com";
const enabled = import.meta.env.PROD && Boolean(projectToken && apiHost);

export function initAnalytics() {
  if (!enabled) return;
  posthog.init(projectToken, {
    api_host: apiHost,
    autocapture: false,
    capture_pageview: false,
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
