package es.doblecheck.app

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import java.util.concurrent.TimeUnit

/** Tarea periódica de Android (WorkManager): descarga el feed y decide los avisos. */
class FeedWorker(ctx: Context, params: WorkerParameters) : Worker(ctx, params) {

    override fun doWork(): Result = try {
        val feed = FeedClient.fetch(applicationContext, force = inputData.getBoolean("force", false))
        if (feed != null) Engine(applicationContext).run(feed)
        Result.success()
    } catch (e: Exception) {
        if (runAttemptCount < 2) Result.retry() else Result.success()
    }

    companion object {
        private val network = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

        fun schedule(ctx: Context, replace: Boolean = false) {
            val minutes = Prefs(ctx).interval.toLong().coerceAtLeast(15)
            val req = PeriodicWorkRequestBuilder<FeedWorker>(minutes, TimeUnit.MINUTES)
                .setConstraints(network)
                .build()
            WorkManager.getInstance(ctx).enqueueUniquePeriodicWork(
                "feed",
                if (replace) ExistingPeriodicWorkPolicy.UPDATE else ExistingPeriodicWorkPolicy.KEEP,
                req,
            )
        }

        fun runNow(ctx: Context) {
            val req = OneTimeWorkRequestBuilder<FeedWorker>()
                .setConstraints(network)
                .setInputData(workDataOf("force" to true))
                .build()
            WorkManager.getInstance(ctx).enqueueUniqueWork("feed-now", ExistingWorkPolicy.REPLACE, req)
        }
    }
}
