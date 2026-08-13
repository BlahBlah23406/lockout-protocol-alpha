package com.lockoutprotocol.guardian.service

/** Tiny shared state: which package is currently foreground. */
object ForegroundApp {
    @Volatile var current: String = ""
        private set
    @Volatile var lastChangeAt: Long = 0
        private set
    @Volatile var accessibilityConnected: Boolean = false

    fun update(pkg: String) {
        current = pkg
        lastChangeAt = System.currentTimeMillis()
    }
}
