package es.doblecheck.app

import android.content.Context
import org.json.JSONObject
import java.util.Calendar

enum class Kind(val channel: String) {
    BREAKING("breaking"),
    CONFIRMED("confirmed"),
    TOPIC("topics"),
    FOLLOW("follow"),
}

/**
 * Decide qué avisar a partir del feed y de los ajustes. Todo ocurre en el móvil.
 *
 *  - Noticia nueva: última hora, confirmada por N medios o que menciona tus temas
 *    (cada noticia se avisa una sola vez).
 *  - Noticia que sigues: novedades, confirmación ✓✓, nuevos medios, prensa extranjera.
 */
class Engine(private val ctx: Context) {

    fun run(feed: Feed, now: Long = System.currentTimeMillis() / 1000) {
        val prefs = Prefs(ctx)
        val store = Store(ctx)
        val notifier = Notifier(ctx)
        val follows = store.follows()
        val seen = store.seen()
        val firstRun = !store.initialized   // la primera vez no se avisa de lo que ya había

        // noticias que se fusionaron con otra: el seguimiento pasa a la que la absorbió
        for ((old, new) in feed.merged) {
            val o = old.toString()
            if (!follows.has(o)) continue
            if (!follows.has(new.toString())) follows.put(new.toString(), follows.getJSONObject(o))
            follows.remove(o)
        }

        val quietNow = prefs.quiet && inQuietHours(prefs.quietFrom, prefs.quietTo)
        val sent = store.sentTimes().filter { now - it < 3600 }.toMutableList()
        val keywords = prefs.keywords
        val mute = prefs.mute

        for (s in feed.stories) {
            val key = s.id.toString()
            val muted = Text.firstMatch(s.searchable, mute) != null

            // ---------- noticias nuevas
            if (!seen.has(key)) seen.put(key, JSONObject().put("x", if (firstRun) 1 else 0).put("t", now))
            val entry = seen.getJSONObject(key)
            if (!firstRun && prefs.enabled && entry.optInt("x") == 0 && !muted && now - s.lastPublished < 6 * 3600) {
                val topic = if (prefs.topics) Text.firstMatch(s.searchable, keywords) else null
                val kind = when {
                    s.breaking && prefs.breaking -> Kind.BREAKING
                    prefs.confirmed && s.written && s.sources >= prefs.minSources -> Kind.CONFIRMED
                    topic != null && s.sources >= 2 -> Kind.TOPIC
                    else -> null
                }
                if (kind != null) {
                    entry.put("x", 1)
                    val autoFollow = (kind == Kind.BREAKING && prefs.autoFollowBreaking) ||
                        (topic != null && prefs.autoFollowTopics)
                    if (autoFollow && !follows.has(key)) follows.put(key, Store.snapshot(s, now))
                    val quietOk = !quietNow || (kind == Kind.BREAKING && prefs.quietBreaking)
                    val limitOk = prefs.maxPerHour == 0 || sent.size < prefs.maxPerHour
                    if (quietOk && limitOk) {
                        notifier.newStory(s, kind, topic, following = follows.has(key))
                        sent.add(now)
                    }
                }
            }

            // ---------- noticias que sigues
            if (!follows.has(key)) continue
            val f = follows.getJSONObject(key)
            if (!f.optBoolean("init", true)) {   // se siguió sin datos: se toma el estado sin avisar
                val at = f.optLong("at", now)
                follows.put(key, Store.snapshot(s, now).put("at", at))
                continue
            }
            val events = mutableListOf<String>()
            if (prefs.followConfirm && f.optInt("ai") == 0 && s.written && s.sources >= 2)
                events.add("✓✓ Confirmada por ${s.sources} medios")
            if (prefs.followNotes && s.note != null && s.noteAt > f.optLong("u"))
                events.add("🔄 ${s.note}")
            if (prefs.followSources && s.sources - f.optInt("ns", s.sources) >= prefs.followStep) {
                events.add("📰 Ya la publican ${s.sources} medios")
                f.put("ns", s.sources)
            }
            val oldIntl = f.optInt("i")
            if (prefs.followIntl && s.intl.size > oldIntl)
                events.add("🌍 Se hace eco la prensa de " + s.intl.drop(oldIntl).joinToString(" "))

            val changed = s.sources != f.optInt("n") || s.noteAt > f.optLong("u") ||
                s.intl.size != oldIntl || (s.written && f.optInt("ai") == 0)
            if (changed) f.put("lc", now)
            f.put("h", s.headline).put("n", s.sources).put("ai", if (s.written) 1 else 0)
                .put("u", maxOf(f.optLong("u"), s.noteAt)).put("i", s.intl.size)

            if (events.isNotEmpty() && prefs.enabled && (!quietNow || prefs.quietFollow))
                notifier.followUpdate(s, events)
        }

        // dejar de seguir lo que lleva días sin novedades
        val limit = prefs.followDays * 86_400L
        for (k in follows.keys().asSequence().toList()) {
            val f = follows.getJSONObject(k)
            if (now - maxOf(f.optLong("lc"), f.optLong("at")) > limit) follows.remove(k)
        }
        // olvidar noticias vistas hace más de 3 días
        for (k in seen.keys().asSequence().toList()) {
            if (now - seen.getJSONObject(k).optLong("t") > 3 * 86_400L) seen.remove(k)
        }

        store.saveFollows(follows)
        store.saveSeen(seen)
        store.saveSentTimes(sent)
        store.initialized = true
    }

    private fun inQuietHours(from: Int, to: Int): Boolean {
        val h = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)
        return when {
            from == to -> false
            from < to -> h in from until to
            else -> h >= from || h < to   // p. ej. de 23:00 a 08:00
        }
    }
}
