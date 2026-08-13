package com.lockoutprotocol.guardian.service

/**
 * Temporary per-app overrides granted from the block screen. An override lets the user keep using
 * a flagged app, but stays in effect ONLY until that app loses focus and is brought back into
 * focus again — then it expires and the app is re-evaluated/re-blocked.
 */
object Overrides {
    private val active = HashSet<String>()
    private val leftFocus = HashSet<String>()

    @Synchronized
    fun grant(pkg: String) {
        active.add(pkg)
        leftFocus.remove(pkg)
    }

    @Synchronized
    fun isActive(pkg: String): Boolean = pkg in active

    /**
     * Call on every real (non-Guardian) foreground change. Marks overridden apps that are no
     * longer foreground as having left focus; expires the override once such an app returns.
     */
    @Synchronized
    fun onForeground(pkg: String) {
        for (a in active) if (a != pkg) leftFocus.add(a)
        if (pkg in active && pkg in leftFocus) {
            active.remove(pkg)
            leftFocus.remove(pkg)
        }
    }
}
