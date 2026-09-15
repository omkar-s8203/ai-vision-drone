plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.aivisiondrone.groundstation"
    compileSdk = 35 // required by compose-bom 2025.12.01's libraries (Compose 1.10.0)

    defaultConfig {
        applicationId = "com.aivisiondrone.groundstation"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"

        // stream-webrtc-android's 32-bit native libraries (armeabi-v7a, x86)
        // were still not 16 KB page-aligned as of mid-2025; the ground
        // station only needs to run on real (arm64) phones/tablets and the
        // 64-bit emulator, so just don't ship the unaligned 32-bit ABIs.
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    buildFeatures {
        compose = true
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
    implementation(platform("androidx.compose:compose-bom:2025.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.6")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.6")

    // Compose pulls this in transitively for path-based clip/shape ops;
    // pin explicitly to a version built with 16 KB page-aligned native
    // libraries rather than whatever older version resolves transitively.
    implementation("androidx.graphics:graphics-path:1.1.0")

    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    // Republished, actively maintained Google WebRTC binaries for Android -
    // the original org.webrtc:google-webrtc artifact is no longer published.
    // Same org.webrtc.* API surface referenced in this module's code.
    // 1.1.1 predated GetStream's 16 KB page-alignment fixes - use current.
    implementation("io.getstream:stream-webrtc-android:1.3.10")

    debugImplementation("androidx.compose.ui:ui-tooling")
}
