plugins {
    id("com.android.application") version "8.5.2" apply false
    // The org.jetbrains.kotlin.plugin.compose Gradle plugin only exists from
    // Kotlin 2.0.0 onward (it replaced the old composeOptions{} approach) -
    // both entries must stay on a 2.0+ Kotlin version together.
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.0.21" apply false
}
