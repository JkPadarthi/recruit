plugins {
    id("com.android.application") version "8.7.2" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
    // google-services is only needed once you drop in your google-services.json.
    // Commented out so the project still syncs before Firebase setup is done.
    // id("com.google.gms.google-services") version "4.4.2" apply false
}
