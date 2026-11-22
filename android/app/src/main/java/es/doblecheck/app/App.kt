package es.doblecheck.app

import android.app.Application
import androidx.preference.PreferenceManager

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        PreferenceManager.setDefaultValues(this, R.xml.prefs, false)
        Notifier.createChannels(this)
        FeedWorker.schedule(this)
    }
}
