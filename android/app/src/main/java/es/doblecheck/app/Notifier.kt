package es.doblecheck.app

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat

/**
 * Crea y muestra los avisos. Cada tipo tiene su canal de Android, así que el usuario
 * puede elegir sonido, vibración o silencio por separado desde los ajustes del sistema.
 */
class Notifier(private val ctx: Context) {

    companion object {
        private const val BLUE = 0xFF1D9BD8.toInt()
        private const val RED = 0xFFB3261E.toInt()

        fun createChannels(ctx: Context) {
            if (Build.VERSION.SDK_INT < 26) return
            val nm = ctx.getSystemService(NotificationManager::class.java) ?: return
            listOf(
                NotificationChannel("breaking", "🔴 Última hora", NotificationManager.IMPORTANCE_HIGH).apply {
                    description = "Noticias de última hora, aunque aún las tenga un solo medio"
                },
                NotificationChannel("confirmed", "✓✓ Noticias confirmadas", NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = "Noticias publicadas por varios medios"
                },
                NotificationChannel("topics", "🏷 Mis temas", NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = "Noticias que mencionan los temas que has elegido"
                },
                NotificationChannel("follow", "🔔 Noticias que sigo", NotificationManager.IMPORTANCE_HIGH).apply {
                    description = "Novedades de las noticias que sigues"
                },
            ).forEach { nm.createNotificationChannel(it) }
        }
    }

    fun newStory(s: Story, kind: Kind, topic: String?, following: Boolean) {
        val title = when (kind) {
            Kind.BREAKING -> if (s.sources <= 1) "🔴 Última hora ✓" else "🔴 Última hora ✓✓"
            Kind.CONFIRMED -> "✓✓ Confirmada por ${s.sources} medios"
            Kind.TOPIC -> "🏷 ${topic ?: s.tag}"
            Kind.FOLLOW -> "🔔 ${s.tag}"
        }
        val detail = if (s.sources <= 1)
            "Según ${s.sourceNames.firstOrNull() ?: "un medio"} · pendiente de confirmar por otros medios"
        else sourcesLine(s)
        val b = base(kind.channel, s.id)
            .setContentTitle(title)
            .setContentText(s.headline)
            .setStyle(NotificationCompat.BigTextStyle().bigText("${s.headline}\n\n$detail"))
            .setColor(if (kind == Kind.BREAKING) RED else BLUE)
        if (following) b.addAction(0, "Dejar de seguir", actionIntent(s, follow = false))
        else b.addAction(0, "🔔 Seguir", actionIntent(s, follow = true))
        post(s.id, b)
    }

    fun followUpdate(s: Story, events: List<String>) {
        val b = base(Kind.FOLLOW.channel, s.id)
            .setContentTitle(s.headline)
            .setContentText(events.first())
            .setStyle(NotificationCompat.BigTextStyle().bigText(events.joinToString("\n") + "\n\n" + sourcesLine(s)))
            .setSubText("Siguiendo")
            .addAction(0, "Dejar de seguir", actionIntent(s, follow = false))
        post(s.id, b)
    }

    fun test() {
        val b = base(Kind.CONFIRMED.channel, 0)
            .setContentTitle("✓✓ Los avisos funcionan")
            .setContentText("Así te llegarán las noticias de DobleCheck")
        post(999_999_999, b)
    }

    private fun sourcesLine(s: Story): String {
        val names = s.sourceNames.take(3).joinToString(", ")
        val more = s.sources - s.sourceNames.take(3).size
        return "✓✓ $names" + (if (more > 0) " y $more más" else "") +
            (if (s.intl.isNotEmpty()) "  ·  🌍 " + s.intl.joinToString(" ") else "")
    }

    private fun base(channel: String, storyId: Int): NotificationCompat.Builder =
        NotificationCompat.Builder(ctx, channel)
            .setSmallIcon(R.drawable.ic_stat_check)
            .setColor(BLUE)
            .setAutoCancel(true)
            .setOnlyAlertOnce(false)
            .setContentIntent(openIntent(storyId))
            .setGroup(channel)

    private fun openIntent(storyId: Int): PendingIntent {
        val i = Intent(ctx, MainActivity::class.java)
            .putExtra("story", storyId)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        return PendingIntent.getActivity(ctx, storyId, i,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    private fun actionIntent(s: Story, follow: Boolean): PendingIntent {
        val i = Intent(ctx, ActionReceiver::class.java)
            .setAction(if (follow) ActionReceiver.FOLLOW else ActionReceiver.UNFOLLOW)
            .putExtra("id", s.id)
            .putExtra("h", s.headline)
        return PendingIntent.getBroadcast(ctx, s.id * 2 + (if (follow) 1 else 0), i,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    private fun post(id: Int, b: NotificationCompat.Builder) {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) return
        try {
            NotificationManagerCompat.from(ctx).notify(id, b.build())
        } catch (e: SecurityException) {
            // permiso retirado entre la comprobación y el aviso
        }
    }
}
