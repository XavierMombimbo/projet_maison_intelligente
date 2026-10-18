import org.gradle.api.tasks.compile.JavaCompile

allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

val configuredBuildDir = System.getenv("SENTINELLE_MOBILE_BUILD_DIR")
val newBuildDir: Directory = if (configuredBuildDir.isNullOrBlank()) {
    rootProject.layout.buildDirectory.dir("../../build").get()
} else {
    rootProject.layout.dir(
        rootProject.providers.provider { rootProject.file(configuredBuildDir) },
    ).get()
}
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")
    tasks.withType<JavaCompile>().configureEach {
        options.isFork = false
    }
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
