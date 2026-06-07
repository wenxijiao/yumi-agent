plugins {
    kotlin("jvm") version "1.9.24"
    application
}

group = "io.yumi"
version = "0.1.0"

repositories {
    mavenCentral()
}

dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.code.gson:gson:2.10.1")
}

kotlin {
    jvmToolchain(17)
}

application {
    mainClass.set("io.yumi.edge.MainKt")
}
