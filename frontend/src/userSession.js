const USER_COOKIE = "companies_act_user_name";

export const getRememberedUser = () => {
  const prefix = `${USER_COOKIE}=`;
  const value = document.cookie.split(";").map((item) => item.trim()).find((item) => item.startsWith(prefix));
  if (!value) return "";
  try {
    return decodeURIComponent(value.slice(prefix.length));
  } catch {
    return "";
  }
};

export const rememberUser = (name) => {
  const normalized = String(name || "").trim();
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${USER_COOKIE}=${encodeURIComponent(normalized)}; Max-Age=31536000; Path=/; SameSite=Lax${secure}`;
  return normalized;
};

export const forgetUser = () => {
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${USER_COOKIE}=; Max-Age=0; Path=/; SameSite=Lax${secure}`;
};
