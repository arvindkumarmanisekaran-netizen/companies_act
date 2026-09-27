package site.companiesact.app;

import android.Manifest;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;

import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import com.getcapacitor.BridgeActivity;
import com.google.firebase.FirebaseApp;
import com.google.firebase.appdistribution.FirebaseAppDistribution;
import com.google.firebase.messaging.FirebaseMessaging;

import static android.content.pm.PackageManager.PERMISSION_GRANTED;

public class MainActivity extends BridgeActivity {
    private static final int NOTIFICATION_PERMISSION_REQUEST = 2013;
    private static final long ADMIN_TOPIC_CHECK_INTERVAL_MS = 2000L;
    private final Handler adminTopicHandler = new Handler(Looper.getMainLooper());
    private Boolean lastAdminTopicState = null;
    private final Runnable adminTopicSync = new Runnable() {
        @Override
        public void run() {
            syncAdminFeedbackTopic();
            adminTopicHandler.postDelayed(this, ADMIN_TOPIC_CHECK_INTERVAL_MS);
        }
    };

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getBridge().getWebView().addJavascriptInterface(new Object() {
            @JavascriptInterface
            public void setAdminName(String name) {
                AdminPushRegistration.setAdminName(getApplicationContext(), name);
            }
        }, "CompaniesActNative");
        createNotificationChannel();

        if (!FirebaseApp.getApps(this).isEmpty()) {
            FirebaseMessaging.getInstance().subscribeToTopic(CompaniesActMessagingService.UPDATE_TOPIC);
            requestNotificationPermission();
        }
    }

    @Override
    public void onResume() {
        super.onResume();
        if (!FirebaseApp.getApps(this).isEmpty()) {
            FirebaseAppDistribution.getInstance().updateIfNewReleaseAvailable();
            adminTopicHandler.removeCallbacks(adminTopicSync);
            adminTopicHandler.post(adminTopicSync);
        }
    }

    @Override
    public void onPause() {
        adminTopicHandler.removeCallbacks(adminTopicSync);
        super.onPause();
    }

    private void syncAdminFeedbackTopic() {
        if (FirebaseApp.getApps(this).isEmpty()) return;
        boolean isAdmin = hasAdminCookie();
        if (lastAdminTopicState != null && lastAdminTopicState == isAdmin) return;
        lastAdminTopicState = isAdmin;
        if (isAdmin) {
            String cookies = CookieManager.getInstance().getCookie("https://localhost");
            String normalized = cookies == null ? "" : cookies.toLowerCase();
            AdminPushRegistration.setAdminName(
                getApplicationContext(),
                normalized.contains("companies_act_user_name=nak%40momo") || normalized.contains("companies_act_user_name=nak@momo")
                    ? "nak@momo" : "arv@momo"
            );
        } else {
            AdminPushRegistration.setAdminName(getApplicationContext(), "");
        }
    }

    private boolean hasAdminCookie() {
        CookieManager cookieManager = CookieManager.getInstance();
        String cookies = cookieManager.getCookie("https://localhost");
        if (cookies == null || cookies.isEmpty()) {
            cookies = cookieManager.getCookie("https://companiesact.site");
        }
        if (cookies == null) return false;
        String normalized = cookies.toLowerCase();
        return normalized.contains("companies_act_user_name=arv%40momo")
            || normalized.contains("companies_act_user_name=nak%40momo")
            || normalized.contains("companies_act_user_name=arv@momo")
            || normalized.contains("companies_act_user_name=nak@momo");
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }

        NotificationChannel channel = new NotificationChannel(
            CompaniesActMessagingService.UPDATE_CHANNEL_ID,
            getString(R.string.update_channel_name),
            NotificationManager.IMPORTANCE_HIGH
        );
        channel.setDescription(getString(R.string.update_channel_description));
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(channel);
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
            && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(
                this,
                new String[]{Manifest.permission.POST_NOTIFICATIONS},
                NOTIFICATION_PERMISSION_REQUEST
            );
        }
    }
}
