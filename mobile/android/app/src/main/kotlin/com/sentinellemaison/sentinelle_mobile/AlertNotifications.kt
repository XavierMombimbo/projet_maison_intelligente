package com.sentinellemaison.sentinelle_mobile

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build

class AlertNotifications(private val context: Context) {
    private val manager = context.getSystemService(NotificationManager::class.java)

    fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                "sentinelle_alerts", "Alertes de surveillance", NotificationManager.IMPORTANCE_HIGH,
            )
            channel.enableVibration(true)
            manager.createNotificationChannel(channel)
        }
    }

    fun show(deliveryId: String, eventId: String?, lockScreen: String?, personWeaponSuspicion: Boolean = false) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N && !manager.areNotificationsEnabled()) return
        createChannel()
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
            action = "sentinelle.alert.$deliveryId"
            putExtra("sentinelle_event_id", eventId)
            putExtra("sentinelle_delivery_id", deliveryId)
        }
        val pending = PendingIntent.getActivity(
            context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(context, "sentinelle_alerts")
        } else {
            Notification.Builder(context)
        }
        val notification = builder
            .setSmallIcon(R.drawable.ic_stat_alert)
            .setContentTitle("Sentinelle Maison")
            .setContentText(if (personWeaponSuspicion) "Personne détectée avec port d’arme probable" else "Une nouvelle alerte est disponible.")
            .setCategory(Notification.CATEGORY_ALARM)
            .setPriority(Notification.PRIORITY_HIGH)
            .setDefaults(Notification.DEFAULT_ALL)
            .setVisibility(when (lockScreen) {
                "secret" -> Notification.VISIBILITY_SECRET
                "public" -> Notification.VISIBILITY_PUBLIC
                else -> Notification.VISIBILITY_PRIVATE
            })
            .setOnlyAlertOnce(true)
            .setAutoCancel(true)
            .setContentIntent(pending)
            .build()
        manager.notify(deliveryId, 0, notification)
    }
}
