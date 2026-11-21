allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")
}

// firebase_core's release lint task crashes on AGP 8.x with compileSdk 37:
//   "Unexpected failure during lint analysis (this is a bug in lint...)"
// It is a tooling bug in a dependency's lint run, not something in our code, and
// it only affects `lintVital...Release`. `flutter analyze` is our static gate,
// so disable the release lint-vital pass rather than pinning AGP backwards.
subprojects {
    tasks.configureEach {
        if (name.startsWith("lintVital")) {
            enabled = false
        }
    }
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
