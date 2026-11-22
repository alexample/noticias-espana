package es.doblecheck.app

import android.content.Intent
import android.content.SharedPreferences
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.preference.EditTextPreference
import androidx.preference.Preference
import androidx.preference.PreferenceFragmentCompat
import androidx.preference.PreferenceManager

class SettingsActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        if (savedInstanceState == null) {
            supportFragmentManager.beginTransaction().replace(android.R.id.content, SettingsFragment()).commit()
        }
    }

    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }

    class SettingsFragment : PreferenceFragmentCompat(), SharedPreferences.OnSharedPreferenceChangeListener {
        override fun onCreatePreferences(savedInstanceState: Bundle?, rootKey: String?) {
            setPreferencesFromResource(R.xml.prefs, rootKey)

            for (key in listOf("keywords", "mute")) {
                findPreference<EditTextPreference>(key)?.summaryProvider =
                    Preference.SummaryProvider<EditTextPreference> { p ->
                        if (p.text.isNullOrBlank()) "Ninguno" else p.text
                    }
            }
            findPreference<Preference>("open_following")?.setOnPreferenceClickListener {
                startActivity(Intent(requireContext(), FollowingActivity::class.java)); true
            }
            findPreference<Preference>("system_channels")?.setOnPreferenceClickListener {
                val ctx = requireContext()
                val i = if (Build.VERSION.SDK_INT >= 26)
                    Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, ctx.packageName)
                else Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + ctx.packageName))
                startActivity(i); true
            }
            findPreference<Preference>("check_now")?.setOnPreferenceClickListener {
                FeedWorker.runNow(requireContext())
                Toast.makeText(requireContext(), "Buscando novedades…", Toast.LENGTH_SHORT).show(); true
            }
            findPreference<Preference>("test")?.setOnPreferenceClickListener {
                Notifier(requireContext()).test(); true
            }
        }

        override fun onResume() {
            super.onResume()
            PreferenceManager.getDefaultSharedPreferences(requireContext()).registerOnSharedPreferenceChangeListener(this)
        }

        override fun onPause() {
            PreferenceManager.getDefaultSharedPreferences(requireContext()).unregisterOnSharedPreferenceChangeListener(this)
            super.onPause()
        }

        override fun onSharedPreferenceChanged(sp: SharedPreferences?, key: String?) {
            if (key == "interval") FeedWorker.schedule(requireContext(), replace = true)
        }
    }
}
