package es.doblecheck.app

import android.content.Context
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** Descarga data/feed.json. Usa ETag: si nada ha cambiado, el servidor responde 304 y no se descarga nada. */
object FeedClient {
    fun fetch(ctx: Context, force: Boolean = false): Feed? {
        val sp = ctx.getSharedPreferences("feed", Context.MODE_PRIVATE)
        val conn = URL(BuildConfig.SITE_URL + "data/feed.json").openConnection() as HttpURLConnection
        conn.connectTimeout = 15_000
        conn.readTimeout = 20_000
        conn.setRequestProperty("User-Agent", "DobleCheckApp/" + BuildConfig.VERSION_NAME)
        val etag = sp.getString("etag", null)
        if (!force && etag != null) conn.setRequestProperty("If-None-Match", etag)
        try {
            val code = conn.responseCode
            if (code == HttpURLConnection.HTTP_NOT_MODIFIED) return null
            if (code != HttpURLConnection.HTTP_OK) throw IOException("HTTP $code")
            val body = conn.inputStream.bufferedReader().use { it.readText() }
            val feed = Feed.parse(body)
            sp.edit().putString("etag", conn.getHeaderField("ETag")).apply()
            Store(ctx).saveFeedCache(body)
            return feed
        } finally {
            conn.disconnect()
        }
    }
}
