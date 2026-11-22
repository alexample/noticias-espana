package es.doblecheck.app

import org.json.JSONArray
import org.json.JSONObject
import java.text.Normalizer

/** Una noticia tal como viene en data/feed.json (generado por la web cada 15 minutos). */
data class Story(
    val id: Int,
    val headline: String,
    val tag: String,
    val sources: Int,
    val breaking: Boolean,
    val written: Boolean,
    val firstPublished: Long,
    val lastPublished: Long,
    val sourceNames: List<String>,
    val noteAt: Long,
    val note: String?,
    val intl: List<String>,
) {
    /** Texto donde se buscan los temas y las palabras silenciadas. */
    val searchable: String get() = "$headline $tag"

    companion object {
        fun parse(o: JSONObject): Story {
            val u = o.optJSONObject("u")
            return Story(
                id = o.getInt("id"),
                headline = o.optString("h"),
                tag = o.optString("t"),
                sources = o.optInt("n"),
                breaking = o.optInt("b") == 1,
                written = o.optInt("ai") == 1,
                firstPublished = o.optLong("fp"),
                lastPublished = o.optLong("lp"),
                sourceNames = o.optJSONArray("src").strings(),
                noteAt = u?.optLong("at") ?: 0L,
                note = u?.optString("note")?.takeIf { it.isNotBlank() },
                intl = o.optJSONArray("i").strings(),
            )
        }
    }
}

data class Feed(val generated: Long, val stories: List<Story>, val merged: Map<Int, Int>) {
    fun find(id: Int): Story? = stories.firstOrNull { it.id == id }

    companion object {
        fun parse(body: String): Feed {
            val o = JSONObject(body)
            val arr = o.getJSONArray("s")
            val stories = (0 until arr.length()).map { Story.parse(arr.getJSONObject(it)) }
            val merged = mutableMapOf<Int, Int>()
            o.optJSONObject("m")?.let { m ->
                for (k in m.keys()) k.toIntOrNull()?.let { merged[it] = m.getInt(k) }
            }
            return Feed(o.optLong("g"), stories, merged)
        }
    }
}

fun JSONArray?.strings(): List<String> =
    if (this == null) emptyList() else (0 until length()).map { optString(it) }

object Text {
    private val marks = "\\p{Mn}+".toRegex()

    /** minúsculas y sin tildes, como hace el worker en Python */
    fun fold(s: String): String =
        Normalizer.normalize(s.lowercase(), Normalizer.Form.NFD).replace(marks, "")

    /** Devuelve la primera palabra de la lista que aparece en el texto (palabra completa). */
    fun firstMatch(text: String, words: List<String>): String? {
        if (words.isEmpty()) return null
        val t = fold(text)
        return words.firstOrNull { w ->
            Regex("(^|[^a-z0-9ñ])" + Regex.escape(w) + "([^a-z0-9ñ]|$)").containsMatchIn(t)
        }
    }
}
