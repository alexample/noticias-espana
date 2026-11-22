package es.doblecheck.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/**
 * Estado local: noticias que sigues, noticias ya vistas (para no avisar dos veces)
 * y avisos enviados en la última hora (para el límite por hora).
 */
class Store(ctx: Context) {
    private val sp = ctx.applicationContext.getSharedPreferences("state", Context.MODE_PRIVATE)
    private val feedSp = ctx.applicationContext.getSharedPreferences("feed", Context.MODE_PRIVATE)

    @Synchronized fun follows(): JSONObject = JSONObject(sp.getString("follows", "{}") ?: "{}")
    @Synchronized fun saveFollows(o: JSONObject) { sp.edit().putString("follows", o.toString()).commit() }

    @Synchronized fun seen(): JSONObject = JSONObject(sp.getString("seen", "{}") ?: "{}")
    @Synchronized fun saveSeen(o: JSONObject) { sp.edit().putString("seen", o.toString()).commit() }

    fun sentTimes(): List<Long> {
        val a = JSONArray(sp.getString("sent", "[]") ?: "[]")
        return (0 until a.length()).map { a.getLong(it) }
    }
    fun saveSentTimes(t: List<Long>) { sp.edit().putString("sent", JSONArray(t).toString()).commit() }

    var initialized: Boolean
        get() = sp.getBoolean("initialized", false)
        set(v) { sp.edit().putBoolean("initialized", v).commit() }

    fun isFollowing(id: Int) = follows().has(id.toString())

    /** Seguir una noticia. Toma su estado actual del último feed descargado. */
    @Synchronized fun follow(id: Int, headline: String) {
        val f = follows()
        val story = cachedFeed()?.find(id)
        val now = System.currentTimeMillis() / 1000
        f.put(id.toString(), if (story != null) snapshot(story, now) else
            JSONObject().put("h", headline).put("at", now).put("lc", now).put("init", false))
        saveFollows(f)
    }

    @Synchronized fun unfollow(id: Int) {
        val f = follows()
        f.remove(id.toString())
        saveFollows(f)
    }

    fun saveFeedCache(body: String) { feedSp.edit().putString("cache", body).apply() }

    fun cachedFeed(): Feed? = try {
        feedSp.getString("cache", null)?.let { Feed.parse(it) }
    } catch (e: Exception) { null }

    companion object {
        /** Estado de una noticia en el momento de empezar a seguirla. */
        fun snapshot(s: Story, now: Long): JSONObject = JSONObject()
            .put("h", s.headline)
            .put("n", s.sources)
            .put("ns", s.sources)
            .put("ai", if (s.written) 1 else 0)
            .put("u", s.noteAt)
            .put("i", s.intl.size)
            .put("at", now)
            .put("lc", now)
            .put("init", true)
    }
}
