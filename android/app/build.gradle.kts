plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.jkpadarthi.recruit"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.jkpadarthi.recruit"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"

        // One place to change if the domain ever moves.
        buildConfigField("String", "BASE_URL", "\"https://recruit.jaswanth.me\"")
    }

    buildTypes {
        debug {
            isMinifyEnabled = false
            applicationIdSuffix = ".debug"   // lets debug + release live side by side
        }
        release {
            isMinifyEnabled = false
            // Signing is configured in Android Studio: Build > Generate Signed App Bundle
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.3")

    // Firebase Cloud Messaging. The google-services plugin is applied once you
    // drop app/google-services.json in place (see README.md in this directory).
    implementation(platform("com.google.firebase:firebase-bom:33.5.1"))
    implementation("com.google.firebase:firebase-messaging")
}
