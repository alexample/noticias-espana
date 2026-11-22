package es.doblecheck.app

import android.content.Intent
import android.os.Bundle
import android.text.format.DateUtils
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.ListView
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONObject

/** Lista de noticias que sigues. Pulsar abre la noticia; mantener pulsado deja de seguirla. */
class FollowingActivity : AppCompatActivity() {

    private lateinit var list: ListView
    private lateinit var empty: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_following)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        list = findViewById(R.id.list)
        empty = findViewById(R.id.empty)
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }

    private fun refresh() {
        val follows = Store(this).follows()
        val items: List<Pair<Int, JSONObject>> = follows.keys().asSequence()
            .mapNotNull { k -> k.toIntOrNull()?.let { it to follows.getJSONObject(k) } }
            .sortedByDescending { it.second.optLong("lc") }
            .toList()
        empty.visibility = if (items.isEmpty()) View.VISIBLE else View.GONE

        list.adapter = object : ArrayAdapter<Pair<Int, JSONObject>>(
            this, android.R.layout.simple_list_item_2, android.R.id.text1, items
        ) {
            override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
                val v = super.getView(position, convertView, parent)
                val o = getItem(position)?.second ?: return v
                val n = o.optInt("n")
                val ago = DateUtils.getRelativeTimeSpanString(o.optLong("lc") * 1000)
                v.findViewById<TextView>(android.R.id.text1).text = o.optString("h")
                v.findViewById<TextView>(android.R.id.text2).text =
                    (if (n >= 2) "✓✓ $n medios" else "✓ 1 medio") + " · última novedad $ago"
                return v
            }
        }
        list.setOnItemClickListener { _, _, pos, _ ->
            startActivity(Intent(this, MainActivity::class.java)
                .putExtra("story", items[pos].first)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP))
        }
        list.setOnItemLongClickListener { _, _, pos, _ ->
            AlertDialog.Builder(this)
                .setMessage("¿Dejar de seguir «${items[pos].second.optString("h")}»?")
                .setPositiveButton("Dejar de seguir") { _, _ ->
                    Store(this).unfollow(items[pos].first)
                    refresh()
                }
                .setNegativeButton("Cancelar", null)
                .show()
            true
        }
    }
}
