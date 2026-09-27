package site.companiesact.app;

import android.content.Context;
import android.content.SharedPreferences;

import com.google.firebase.messaging.FirebaseMessaging;

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public final class AdminPushRegistration {
    private static final String PREFS = "companies_act_push";
    private static final String ADMIN_NAME = "admin_name";
    private static final String ENDPOINT = "https://companiesact.site/api/admin/push-token";
    private static final String UNREGISTER_ENDPOINT = "https://companiesact.site/api/admin/push-token/unregister";

    private AdminPushRegistration() {}

    public static void setAdminName(Context context, String suppliedName) {
        String name = suppliedName == null ? "" : suppliedName.trim().toLowerCase();
        boolean isAdmin = "arv@momo".equals(name) || "nak@momo".equals(name);
        SharedPreferences preferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        if (!isAdmin) {
            String previousAdmin = preferences.getString(ADMIN_NAME, "");
            preferences.edit().remove(ADMIN_NAME).apply();
            FirebaseMessaging.getInstance().unsubscribeFromTopic(CompaniesActMessagingService.ADMIN_FEEDBACK_TOPIC);
            if (!previousAdmin.isEmpty()) {
                FirebaseMessaging.getInstance().getToken().addOnSuccessListener(
                    token -> unregister(previousAdmin, token)
                );
            }
            return;
        }

        preferences.edit().putString(ADMIN_NAME, name).apply();
        FirebaseMessaging.getInstance().subscribeToTopic(CompaniesActMessagingService.ADMIN_FEEDBACK_TOPIC);
        FirebaseMessaging.getInstance().getToken().addOnSuccessListener(token -> register(name, token));
    }

    public static void onNewToken(Context context, String token) {
        String name = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(ADMIN_NAME, "");
        if ("arv@momo".equals(name) || "nak@momo".equals(name)) {
            FirebaseMessaging.getInstance().subscribeToTopic(CompaniesActMessagingService.ADMIN_FEEDBACK_TOPIC);
            register(name, token);
        }
    }

    private static void register(String name, String token) {
        sendTokenRequest(ENDPOINT, name, token);
    }

    private static void unregister(String name, String token) {
        sendTokenRequest(UNREGISTER_ENDPOINT, name, token);
    }

    private static void sendTokenRequest(String endpoint, String name, String token) {
        if (token == null || token.isEmpty()) return;
        new Thread(() -> {
            HttpURLConnection connection = null;
            try {
                connection = (HttpURLConnection) new URL(endpoint).openConnection();
                connection.setRequestMethod("POST");
                connection.setConnectTimeout(7000);
                connection.setReadTimeout(7000);
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json");
                connection.setRequestProperty("X-Admin-Name", name);
                byte[] body = new JSONObject()
                    .put("token", token)
                    .put("platform", "android")
                    .toString()
                    .getBytes(StandardCharsets.UTF_8);
                connection.setFixedLengthStreamingMode(body.length);
                try (OutputStream output = connection.getOutputStream()) {
                    output.write(body);
                }
                connection.getResponseCode();
            } catch (Exception ignored) {
                // Registration is retried whenever the app resumes or Firebase rotates the token.
            } finally {
                if (connection != null) connection.disconnect();
            }
        }, "admin-push-registration").start();
    }
}
