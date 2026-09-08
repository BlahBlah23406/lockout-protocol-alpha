package com.lockoutprotocol.guardian

import com.lockoutprotocol.guardian.ai.ProviderKind
import com.lockoutprotocol.guardian.ai.Providers
import com.lockoutprotocol.guardian.focus.Accountability
import com.lockoutprotocol.guardian.focus.FocusSession
import com.lockoutprotocol.guardian.focus.LearnedPolicy
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Unit tests for focus mode: sessions, the provider wire formats, and the never-block-on-failure
 * rule. Plain JVM tests — nothing here needs a device, a network, or a screen.
 *
 * These mirror `windows/tests/test_focus.py` case for case on purpose. The three ports have to
 * agree about what a verdict means and what a session watches, and the cheapest way to keep them
 * honest is to ask them the same questions.
 */
class FocusTest {

    // ---- sessions --------------------------------------------------------------------------

    @Test
    fun `watchlist is defaults plus extras minus allowed`() {
        val s = FocusSession(task = "math test prep", extraApps = setOf("com.valvesoftware.android"),
            allowedApps = setOf("com.slack"))
        assertEquals(
            setOf("com.android.chrome", "com.valvesoftware.android"),
            s.watchlist(setOf("com.android.chrome", "com.slack")))
    }

    @Test
    fun `watchlist tracks later edits to the defaults`() {
        // The session stores a delta, not a snapshot: editing the default list mid-session is
        // expected to take effect, which a copied list would silently get wrong.
        val s = FocusSession(task = "essay", extraApps = setOf("com.game"))
        assertEquals(setOf("com.android.chrome", "com.game"),
            s.watchlist(setOf("com.android.chrome")))
        assertEquals(setOf("com.android.chrome", "org.mozilla.firefox", "com.game"),
            s.watchlist(setOf("com.android.chrome", "org.mozilla.firefox")))
    }

    @Test
    fun `an excused app wins over a default`() {
        val s = FocusSession(task = "answering support tickets", allowedApps = setOf("com.slack"))
        assertFalse("com.slack" in s.watchlist(setOf("com.slack", "com.android.chrome")))
    }

    @Test
    fun `interval is clamped both ways`() {
        assertEquals(FocusSession.MIN_INTERVAL, FocusSession.clampInterval(1))
        assertEquals(FocusSession.MAX_INTERVAL, FocusSession.clampInterval(99_999))
        assertEquals(120, FocusSession.clampInterval(120))
    }

    @Test
    fun `an open-ended session never expires`() {
        val s = FocusSession(task = "reading", plannedMinutes = 0)
        assertEquals(null, s.remainingMs)
        assertFalse(s.isOver)
    }

    @Test
    fun `a timed session expires`() {
        val s = FocusSession(task = "reading", plannedMinutes = 30,
            startedAt = System.currentTimeMillis() - 31 * 60_000L)
        assertTrue(s.isOver)
        assertEquals(0L, s.remainingMs)
    }

    @Test
    fun `only locked sessions hold their own exit`() {
        assertFalse(Accountability.SELF.requiresPasscodeToEnd)
        assertTrue(Accountability.LOCKED.requiresPasscodeToEnd)
        assertFalse(Accountability.SELF.alertsPartner)
        assertTrue(Accountability.LOCKED.alertsPartner)
    }

    @Test
    fun `an unknown accountability value falls back to self`() {
        // Fail towards the WEAKER mode. A corrupt prefs file must not silently promote someone
        // into a locked session whose passcode they never set.
        assertEquals(Accountability.SELF, Accountability.from("admin"))
        assertEquals(Accountability.SELF, Accountability.from(null))
        assertEquals(Accountability.LOCKED, Accountability.from("locked"))
    }

    @Test
    fun `session round-trips through json`() {
        val s = FocusSession(task = "write the essay", plannedMinutes = 45, intervalSeconds = 90,
            accountability = Accountability.LOCKED, extraApps = setOf("a"), allowedApps = setOf("b"))
        s.checks = 12
        s.offTaskCount = 3
        s.overrideCount = 1

        val back = FocusSession.fromJson(JSONObject(s.toJson().toString()))
        assertEquals(s.id, back.id)
        assertEquals(s.task, back.task)
        assertEquals(Accountability.LOCKED, back.accountability)
        assertEquals(setOf("a"), back.extraApps)
        assertEquals(setOf("b"), back.allowedApps)
        assertEquals(12, back.checks)
        assertEquals(3, back.offTaskCount)
        assertEquals(1, back.overrideCount)
    }

    // ---- verdict parsing -------------------------------------------------------------------

    @Test
    fun `plain on-task answer parses`() {
        val v = Providers.parseFocusJson("""{"on_task": true, "confidence": 0.9}""")
        assertTrue(v.onTask)
        assertFalse(v.offTask)
        assertEquals(0.9, v.confidence, 0.001)
    }

    @Test
    fun `off-task answer keeps the reason`() {
        val v = Providers.parseFocusJson(
            """{"on_task": false, "reason": "Netflix playing The Office", "confidence": 0.95}""")
        assertTrue(v.offTask)
        assertTrue(v.reason.contains("Netflix"))
    }

    @Test
    fun `markdown fences are stripped`() {
        // Small models fence their JSON no matter what the prompt says; throwing that answer away
        // would turn a correct verdict into an unnecessary "couldn't verify".
        val v = Providers.parseFocusJson("```json\n{\"on_task\": false, \"reason\": \"game\"}\n```")
        assertTrue(v.offTask)
        assertEquals("game", v.reason)
    }

    @Test
    fun `unreadable is undetermined not a block`() {
        val v = Providers.parseFocusJson("""{"unreadable": true}""")
        assertTrue(v.undetermined)
        assertFalse(v.offTask)
    }

    @Test
    fun `garbage is undetermined not a block`() {
        for (bad in listOf("not json", "", "{}", """{"on_task": "yes"}""", """{"on_task": null}""")) {
            val v = Providers.parseFocusJson(bad)
            assertTrue("should be undetermined: $bad", v.undetermined)
            assertFalse("must never read as off task: $bad", v.offTask)
        }
    }

    @Test
    fun `confidence is clamped`() {
        assertEquals(1.0,
            Providers.parseFocusJson("""{"on_task": true, "confidence": 7}""").confidence, 0.001)
        assertEquals(0.0,
            Providers.parseFocusJson("""{"on_task": true, "confidence": -3}""").confidence, 0.001)
    }

    // ---- provider envelopes ----------------------------------------------------------------

    private val answer = """{"on_task": false, "reason": "YouTube gaming stream", "confidence": 0.8}"""

    @Test
    fun `every provider envelope reaches the same verdict`() {
        val bodies = mapOf(
            ProviderKind.OLLAMA to JSONObject().put("message",
                JSONObject().put("content", answer)).toString(),
            ProviderKind.OPENAI to """{"choices":[{"message":{"content":${JSONObject.quote(answer)}}}]}""",
            ProviderKind.CUSTOM to """{"choices":[{"message":{"content":${JSONObject.quote(answer)}}}]}""",
            ProviderKind.ANTHROPIC to """{"content":[{"type":"text","text":${JSONObject.quote(answer)}}]}""",
        )
        for ((kind, body) in bodies) {
            val v = Providers.parseResponse(kind, body)
            assertTrue("$kind should parse as off task", v.offTask)
            assertTrue(v.reason.contains("gaming"))
        }
    }

    @Test
    fun `a wrong envelope is undetermined`() {
        val v = Providers.parseResponse(ProviderKind.OPENAI,
            """{"error":{"message":"model not found"}}""")
        assertTrue(v.undetermined)
        assertFalse(v.offTask)
    }

    // ---- request building ------------------------------------------------------------------

    private fun cfg(kind: ProviderKind, base: String) =
        Providers.Config(kind, base, "some-model", listOf("k"), "test")

    @Test
    fun `ollama attaches the image and hits api chat`() {
        val built = Providers.buildRequest(cfg(ProviderKind.OLLAMA, "http://192.168.1.10:11434"),
            "B64", "sys", "usr")
        assertEquals("http://192.168.1.10:11434/api/chat", built.url)
        val images = built.payload.getJSONArray("messages")
            .getJSONObject(1).getJSONArray("images")
        assertEquals("B64", images.getString(0))
    }

    @Test
    fun `openai uses a data uri`() {
        val built = Providers.buildRequest(cfg(ProviderKind.OPENAI, "https://api.openai.com"),
            "B64", "sys", "usr")
        assertEquals("https://api.openai.com/v1/chat/completions", built.url)
        val url = built.payload.getJSONArray("messages").getJSONObject(1)
            .getJSONArray("content").getJSONObject(1)
            .getJSONObject("image_url").getString("url")
        assertEquals("data:image/jpeg;base64,B64", url)
    }

    @Test
    fun `a base url already ending in v1 is not doubled`() {
        // The single most common misconfiguration: pasting a gateway URL that already ends in /v1
        // and getting /v1/v1/chat/completions.
        val built = Providers.buildRequest(cfg(ProviderKind.CUSTOM, "http://10.0.0.5:1234/v1"),
            "B64", "sys", "usr")
        assertEquals("http://10.0.0.5:1234/v1/chat/completions", built.url)
    }

    @Test
    fun `anthropic sends a base64 image block and a version header`() {
        val built = Providers.buildRequest(cfg(ProviderKind.ANTHROPIC, "https://api.anthropic.com"),
            "B64", "sys", "usr")
        assertEquals("https://api.anthropic.com/v1/messages", built.url)
        assertEquals("sys", built.payload.getString("system"))
        val data = built.payload.getJSONArray("messages").getJSONObject(0)
            .getJSONArray("content").getJSONObject(0)
            .getJSONObject("source").getString("data")
        assertEquals("B64", data)
        assertTrue(built.extraHeaders.containsKey("anthropic-version"))
    }

    @Test
    fun `auth header location differs by provider`() {
        assertEquals(mapOf("x-api-key" to "K"),
            Providers.authHeaders(cfg(ProviderKind.ANTHROPIC, "x"), "K"))
        assertEquals(mapOf("Authorization" to "Bearer K"),
            Providers.authHeaders(cfg(ProviderKind.OPENAI, "x"), "K"))
        assertTrue(Providers.authHeaders(cfg(ProviderKind.OLLAMA, "x"), "").isEmpty())
    }

    // ---- the never-block-on-failure rule ---------------------------------------------------

    @Test
    fun `transient codes are classified as transient`() {
        for (code in listOf(408, 429, 500, 502, 503, 504)) {
            assertTrue("$code should be transient", Providers.isTransientCode(code))
        }
        for (code in listOf(200, 404, 418)) {
            assertFalse("$code should not be transient", Providers.isTransientCode(code))
        }
    }

    @Test
    fun `key-exhausted codes trigger failover`() {
        for (code in listOf(401, 402, 403, 429)) {
            assertTrue("$code should mean this key is out", Providers.isKeyExhaustedCode(code))
        }
        assertFalse(Providers.isKeyExhaustedCode(500))
    }

    @Test
    fun `a missing model is undetermined not a block`() {
        // Guards the whole class of "our configuration is broken" failures: they cost the user
        // nothing. Checked via validateConfig so the test needs no Bitmap.
        val v = Providers.validateConfig(
            Providers.Config(ProviderKind.OLLAMA, "http://x", "", emptyList(), "t"))
        assertNotNull(v)
        assertTrue(v!!.undetermined)
        assertFalse(v.offTask)
    }

    @Test
    fun `a missing server url is undetermined not a block`() {
        val v = Providers.validateConfig(
            Providers.Config(ProviderKind.OLLAMA, "", "m", emptyList(), "t"))
        assertNotNull(v)
        assertTrue(v!!.undetermined)
        assertFalse(v.offTask)
    }

    @Test
    fun `a usable config validates clean`() {
        assertEquals(null, Providers.validateConfig(
            Providers.Config(ProviderKind.OLLAMA, "http://x", "m", emptyList(), "t")))
    }

    // ---- prompt ---------------------------------------------------------------------------

    @Test
    fun `task app and title all reach the model`() {
        val p = Providers.userPrompt("math test prep", "Chrome", "Khan Academy — integrals")
        assertTrue(p.contains("math test prep"))
        assertTrue(p.contains("Chrome"))
        assertTrue(p.contains("Khan Academy"))
    }

    @Test
    fun `learned notes are labelled as settled`() {
        val p = Providers.userPrompt("t", "a", "b", extraNotes = "Drive shows my course PDFs")
        assertTrue(p.contains("PREVIOUSLY CONFIRMED"))
        assertTrue(p.contains("course PDFs"))
    }

    @Test
    fun `empty notes add no section`() {
        assertFalse(Providers.userPrompt("t", "a", "b", extraNotes = "   ")
            .contains("PREVIOUSLY CONFIRMED"))
    }

    @Test
    fun `system prompt defaults to on-task`() {
        // The asymmetry against false alarms is a product decision, so it is pinned by a test.
        assertTrue(Providers.FOCUS_SYSTEM.contains("DEFAULT TO on_task"))
    }

    // ---- the learner lookup key ------------------------------------------------------------

    @Test
    fun `lookup key matches the learner's normalisation`() {
        // Must agree character for character with `learner/policy.py:lookup_key` and the Swift
        // client, or a learned policy silently never matches on this platform.
        assertEquals("math-test-prep|com.android.chrome",
            LearnedPolicy.lookupKey("working on math test prep", "com.android.chrome"))
        assertEquals("applying-jobs|com.android.chrome",
            LearnedPolicy.lookupKey("applying for jobs", "com.android.chrome"))
        assertEquals("essay-industrial-revolution|com.google.docs",
            LearnedPolicy.lookupKey("essay on the industrial revolution", "com.google.docs"))
    }

    @Test
    fun `lookup key truncates to four significant words`() {
        assertEquals("revising-integration-parts-friday|com.android.chrome",
            LearnedPolicy.lookupKey(
                "revising integration by parts for Friday's calculus test", "com.android.chrome"))
    }

    @Test
    fun `lookup key lower-cases the package`() {
        // Android package names are conventionally lower-case but not required to be, and the
        // learner lower-cases before writing the key.
        assertEquals("math-test-prep|com.example.myapp",
            LearnedPolicy.lookupKey("math test prep", "com.Example.MyApp"))
    }

    @Test
    fun `provider presets are all well formed`() {
        assertTrue(Providers.presets.isNotEmpty())
        for (preset in Providers.presets) {
            assertNotNull(Providers.preset(preset.id))
            assertTrue("${preset.id} needs a hint", preset.hint.isNotBlank())
            // Only the free-form "custom" entry is allowed to ship without a URL and model.
            if (preset.id != "custom") {
                assertTrue("${preset.id} needs a base URL", preset.baseUrl.isNotBlank())
                assertTrue("${preset.id} needs a model", preset.model.isNotBlank())
            }
        }
    }

    @Test
    fun `learned threshold ceiling is below one`() {
        // The client-side ceiling on how far learning may erode the monitor. If this ever reached
        // 1.0, a generated policy file could switch blocking off entirely.
        assertTrue(LearnedPolicy.MAX_THRESHOLD < 1.0)
        assertEquals(0.85, LearnedPolicy.MAX_THRESHOLD, 0.001)
    }
}
