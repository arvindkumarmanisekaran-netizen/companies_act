package site.companiesact.app;

import android.app.PendingIntent;
import android.content.Intent;
import android.webkit.CookieManager;

import androidx.annotation.NonNull;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;

import com.google.firebase.messaging.FirebaseMessaging;
import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

import java.util.Map;

import static android.Manifest.permission.POST_NOTIFICATIONS;
import static android.content.pm.PackageManager.PERMISSION_GRANTED;

public class CompaniesActMessagingService extends FirebaseMessagingService {
    public static final String UPDATE_TOPIC = "app-updates";
    public static final String ADMIN_FEEDBACK_TOPIC = "admin-feedback";
    public static final String UPDATE_CHANNEL_ID = "companies_act_app_updates";

    @Override
    public void onNewToken(@NonNull String token) {
        FirebaseMessaging.getInstance().subscribeToTopic(UPDATE_TOPIC);
        AdminPushRegistration.onNewToken(getApplicationContext(), token);
    }

    @Override
    public void onMessageReceived(@NonNull RemoteMessage message) {
        Map<String, String> data = message.getData();
        String title = data.getOrDefault("title", "Companies Act update");
        String body = data.getOrDefault("body", "A new app version is available. Tap to update.");

        Intent launchIntent = getPackageManager().getLaunchIntentForPackage(getPackageName());
        if (launchIntent == null) {
            return;
        }
        launchIntent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);

        PendingIntent pendingIntent = PendingIntent.getActivity(
            this,
            0,
            launchIntent,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );

        NotificationCompat.Builder notification = new NotificationCompat.Builder(this, UPDATE_CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_update)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(new NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent);

        if (ContextCompat.checkSelfPermission(this, POST_NOTIFICATIONS) == PERMISSION_GRANTED) {
            int notificationId = "feedback".equals(data.get("kind"))
                ? (int) (System.currentTimeMillis() & 0x0fffffff)
                : 2013;
            NotificationManagerCompat.from(this).notify(notificationId, notification.build());
        }
    }

}
