package es.doblecheck.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.widget.Toast
import androidx.core.app.NotificationManagerCompat

/** Botones «Seguir» y «Dejar de seguir» de los avisos. */
class ActionReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        val id = intent.getIntExtra("id", -1)
        if (id < 0) return
        val store = Store(ctx)
        when (intent.action) {
            FOLLOW -> {
                store.follow(id, intent.getStringExtra("h") ?: "")
                Toast.makeText(ctx, "🔔 Siguiendo esta noticia", Toast.LENGTH_SHORT).show()
            }
            UNFOLLOW -> {
                store.unfollow(id)
                Toast.makeText(ctx, "Has dejado de seguir esta noticia", Toast.LENGTH_SHORT).show()
            }
        }
        NotificationManagerCompat.from(ctx).cancel(id)
    }

    companion object {
        const val FOLLOW = "es.doblecheck.app.FOLLOW"
        const val UNFOLLOW = "es.doblecheck.app.UNFOLLOW"
    }
}
