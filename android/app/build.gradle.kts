plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// La firma de las versiones publicadas viene de GitHub Actions (secretos del repositorio).
// Sin ellos se firma con la clave de depuración: sirve para probar, pero cada compilación
// tendría otra firma y Android no dejaría actualizar sin desinstalar.
val keystoreFile: String? = System.getenv("KEYSTORE_FILE")

android {
    namespace = "es.doblecheck.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "es.doblecheck.app"
        minSdk = 24
        targetSdk = 35
        versionCode = (System.getenv("VERSION_CODE") ?: "1").toInt()
        versionName = System.getenv("VERSION_NAME") ?: "1.0-dev"
        buildConfigField("String", "SITE_URL", "\"https://alexample.github.io/noticias-espana/\"")
    }

    buildFeatures {
        buildConfig = true
    }

    signingConfigs {
        create("release") {
            if (keystoreFile != null) {
                storeFile = file(keystoreFile)
                storePassword = System.getenv("KEYSTORE_PASSWORD")
                keyAlias = System.getenv("KEY_ALIAS") ?: "doblecheck"
                keyPassword = System.getenv("KEYSTORE_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = if (keystoreFile != null) signingConfigs.getByName("release")
                            else signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    lint {
        abortOnError = false
        checkReleaseBuilds = false
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.preference:preference-ktx:1.2.1")
    implementation("androidx.work:work-runtime-ktx:2.9.1")
    implementation("androidx.swiperefreshlayout:swiperefreshlayout:1.1.0")
}
