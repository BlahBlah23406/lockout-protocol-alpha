package com.lockoutprotocol.guardian.ui

import android.content.Context
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView

/**
 * LCARS-flavoured (Star Trek computer) UI helpers for our programmatic screens: black space
 * background, rounded "pill" controls, condensed bold type, and the orange/blue/lilac palette.
 */
object Lcars {
    const val BLACK = 0xFF000000.toInt()
    const val SPACE = 0xFF05070D.toInt()
    const val ORANGE = 0xFFFF9966.toInt()
    const val GOLD = 0xFFFFCC66.toInt()
    const val BLUE = 0xFF7FB0FF.toInt()
    const val LILAC = 0xFFCC88CC.toInt()
    const val RED = 0xFFE0533D.toInt()
    const val PANEL = 0xFF14182B.toInt()
    const val INK = 0xFFE8ECF8.toInt()

    val PALETTE = intArrayOf(ORANGE, BLUE, LILAC, GOLD)
    private val condensed: Typeface = Typeface.create("sans-serif-condensed", Typeface.BOLD)

    fun root(ctx: Context): LinearLayout = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        setBackgroundColor(SPACE)
        setPadding(40, 56, 40, 56)
    }

    /** The LCARS "elbow" header: a fat coloured sweep with a right-aligned title. */
    fun header(ctx: Context, text: String, color: Int = ORANGE): LinearLayout = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        layoutParams = lp().also { it.bottomMargin = 36 }
        addView(View(ctx).apply {
            background = round(color, 24f)
            layoutParams = LinearLayout.LayoutParams(120, 56)
        })
        addView(View(ctx).apply { layoutParams = LinearLayout.LayoutParams(20, 1) })
        addView(TextView(ctx).apply {
            this.text = text.uppercase()
            setTextColor(color); typeface = condensed; textSize = 26f
            letterSpacing = 0.12f
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            gravity = Gravity.END
        })
    }

    fun pill(ctx: Context, text: String, color: Int = ORANGE, onClick: () -> Unit): Button =
        Button(ctx).apply {
            this.text = text.uppercase()
            isAllCaps = true
            setTextColor(BLACK)
            typeface = condensed
            textSize = 15f
            letterSpacing = 0.05f
            stateListAnimator = null
            background = round(color, 70f)
            gravity = Gravity.CENTER
            setPadding(44, 32, 44, 32)
            layoutParams = lp().also { it.bottomMargin = 18 }
            setOnClickListener { onClick() }
        }

    fun titleBig(ctx: Context, text: String, color: Int = ORANGE): TextView = TextView(ctx).apply {
        this.text = text.uppercase()
        setTextColor(color); typeface = condensed; textSize = 40f
        letterSpacing = 0.18f; gravity = Gravity.CENTER
    }

    fun body(ctx: Context, text: String, color: Int = INK): TextView = TextView(ctx).apply {
        this.text = text
        setTextColor(color); textSize = 15f
        typeface = Typeface.create("sans-serif-condensed", Typeface.NORMAL)
        layoutParams = lp().also { it.bottomMargin = 16 }
    }

    /** A rounded dark info panel (LCARS readout). */
    fun panel(ctx: Context, text: String, color: Int = BLUE): TextView = TextView(ctx).apply {
        this.text = text
        setTextColor(color); textSize = 14f
        typeface = Typeface.MONOSPACE
        background = round(PANEL, 28f)
        setPadding(36, 32, 36, 32)
        layoutParams = lp().also { it.bottomMargin = 24 }
    }

    fun input(ctx: Context, hint: String, numeric: Boolean = false, password: Boolean = false): EditText =
        EditText(ctx).apply {
            this.hint = hint
            setHintTextColor(0xFF7A8296.toInt())
            setTextColor(INK)
            gravity = Gravity.CENTER
            textSize = 18f
            background = round(PANEL, 24f)
            setPadding(32, 28, 32, 28)
            inputType = when {
                numeric && password -> InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD
                numeric -> InputType.TYPE_CLASS_NUMBER
                password -> InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
                else -> InputType.TYPE_CLASS_TEXT
            }
            layoutParams = lp().also { it.bottomMargin = 16 }
        }

    fun spacer(ctx: Context, h: Int = 24): View = View(ctx).apply {
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, h)
    }

    private fun round(color: Int, radius: Float) = GradientDrawable().apply {
        cornerRadius = radius; setColor(color)
    }

    private fun lp() = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
    )
}
