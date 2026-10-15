package com.sentinellemaison.sentinelle_mobile

import android.app.NotificationManager
import android.content.Intent
import android.os.Build
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private var notificationChannel: MethodChannel? = null
    private var tapListenerReady = false

    private fun takeOpenedAlert(): Map<String, String>? {
        val eventId = intent?.getStringExtra("sentinelle_event_id") ?: return null
        val deliveryId = intent?.getStringExtra("sentinelle_delivery_id") ?: return null
        intent.removeExtra("sentinelle_event_id")
        intent.removeExtra("sentinelle_delivery_id")
        return mapOf("type" to "alert.created", "event_id" to eventId, "delivery_id" to deliveryId)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (tapListenerReady) {
            takeOpenedAlert()?.let { notificationChannel?.invokeMethod("alertOpened", it) }
        }
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val alerts = AlertNotifications(this)
        alerts.createChannel()
        notificationChannel = MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "sentinelle_maison/notifications",
        )
        notificationChannel!!.setMethodCallHandler { call, result ->
            if (call.method == "takeOpenedAlert") {
                tapListenerReady = true
                result.success(takeOpenedAlert())
                return@setMethodCallHandler
            }
            if (call.method == "showAlert") {
                val deliveryId = call.argument<String>("delivery_id")
                if (deliveryId.isNullOrBlank()) {
                    result.error("invalid_delivery", "Identifiant manquant", null)
                } else {
                    try {
                        alerts.show(deliveryId, call.argument<String>("event_id"), call.argument<String>("lock_screen"))
                        result.success(null)
                    } catch (_: SecurityException) {
                        result.error("permission_denied", "Notifications non autorisees", null)
                    }
                }
                return@setMethodCallHandler
            }
            if (call.method != "areNotificationsEnabled") {
                result.notImplemented()
                return@setMethodCallHandler
            }
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
                result.success(true)
                return@setMethodCallHandler
            }
            val manager = getSystemService(NotificationManager::class.java)
            result.success(manager.areNotificationsEnabled())
        }
    }
}
