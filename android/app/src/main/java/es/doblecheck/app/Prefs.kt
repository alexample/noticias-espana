package es.doblecheck.app

import android.content.Context
import androidx.preference.PreferenceManager

/** Ajustes del usuario (pantalla de Ajustes de avisos). Todo se guarda solo en el móvil. */
class Prefs(ctx: Context) {
    private val p = PreferenceManager.getDefaultSharedPreferences(ctx)

    private fun bool(k: String, d: Boolean) = p.getBoolean(k, d)
    private fun int(k: String, d: Int) = p.getString(k, null)?.toIntOrNull() ?: d
    private fun words(k: String): List<String> =
        (p.getString(k, "") ?: "").split(",").map { Text.fold(it.trim()) }.filter { it.length >= 2 }

    val enabled get() = bool("enabled", true)
    val breaking get() = bool("breaking", true)
    val confirmed get() = bool("confirmed", true)
    val minSources get() = int("min_sources", 4)
    val topics get() = bool("topics", true)
    val keywords get() = words("keywords")
    val mute get() = words("mute")

    val followNotes get() = bool("follow_notes", true)
    val followConfirm get() = bool("follow_confirm", true)
    val followSources get() = bool("follow_sources", false)
    val followStep get() = int("follow_step", 3)
    val followIntl get() = bool("follow_intl", true)
    val autoFollowBreaking get() = bool("autofollow_breaking", false)
    val autoFollowTopics get() = bool("autofollow_topics", false)
    val followDays get() = int("follow_days", 3)

    val interval get() = int("interval", 15)
    val maxPerHour get() = int("max_per_hour", 4)

    val quiet get() = bool("quiet", false)
    val quietFrom get() = int("quiet_from", 23)
    val quietTo get() = int("quiet_to", 8)
    val quietBreaking get() = bool("quiet_breaking", true)
    val quietFollow get() = bool("quiet_follow", false)
}
