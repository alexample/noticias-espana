package es.doblecheck.app

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout

/** La web de DobleCheck dentro de la app, con botón «Seguir» en cada noticia. */
class MainActivity : AppCompatActivity() {

    private lateinit var web: WebView
    private lateinit var swipe: SwipeRefreshLayout
    private val siteHost: String? = Uri.parse(BuildConfig.SITE_URL).host

    private val askPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (!granted) Toast.makeText(this,
            "Sin permiso de notificaciones no podremos avisarte. Puedes activarlo en los ajustes de Android.",
            Toast.LENGTH_LONG).show()
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        supportActionBar?.title = "DobleCheck ✓✓"

        web = findViewById(R.id.web)
        swipe = findViewById(R.id.swipe)

        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.userAgentString = web.settings.userAgentString + " DobleCheckApp/" + BuildConfig.VERSION_NAME
        web.addJavascriptInterface(Bridge(), "DobleCheckApp")
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url
                if (url.host == siteHost) return false
                // los artículos de los medios se abren en el navegador
                return try {
                    startActivity(Intent(Intent.ACTION_VIEW, url)); true
                } catch (e: Exception) { false }
            }

            override fun onPageFinished(view: WebView, url: String) {
                swipe.isRefreshing = false
            }
        }

        swipe.setColorSchemeColors(ContextCompat.getColor(this, R.color.check))
        swipe.setOnRefreshListener { web.reload() }
        swipe.setOnChildScrollUpCallback { _, _ -> web.scrollY > 0 }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (web.canGoBack()) web.goBack() else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })

        if (savedInstanceState == null) open(intent) else web.restoreState(savedInstanceState)

        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) askPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        open(intent)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    private fun open(intent: Intent?) {
        val id = intent?.getIntExtra("story", -1) ?: -1
        web.loadUrl(BuildConfig.SITE_URL + if (id > 0) "#/noticia/$id" else "")
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, 1, 0, "🔔 Siguiendo").setShowAsAction(MenuItem.SHOW_AS_ACTION_IF_ROOM)
        menu.add(0, 2, 1, "Ajustes de avisos")
        menu.add(0, 3, 2, "Actualizar")
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean = when (item.itemId) {
        1 -> { startActivity(Intent(this, FollowingActivity::class.java)); true }
        2 -> { startActivity(Intent(this, SettingsActivity::class.java)); true }
        3 -> { web.reload(); true }
        else -> super.onOptionsItemSelected(item)
    }

    /** Lo que la web puede pedir a la app (botón «Seguir» de cada noticia). */
    inner class Bridge {
        @JavascriptInterface
        fun isFollowing(id: Int): Boolean = Store(this@MainActivity).isFollowing(id)

        @JavascriptInterface
        fun toggleFollow(id: Int, headline: String): Boolean {
            val store = Store(this@MainActivity)
            return if (store.isFollowing(id)) {
                store.unfollow(id); false
            } else {
                store.follow(id, headline); true
            }
        }

        @JavascriptInterface
        fun openSettings() {
            runOnUiThread { startActivity(Intent(this@MainActivity, SettingsActivity::class.java)) }
        }
    }
}
