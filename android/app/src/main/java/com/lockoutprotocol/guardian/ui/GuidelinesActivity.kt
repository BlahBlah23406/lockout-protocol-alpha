package com.lockoutprotocol.guardian.ui

import android.os.Bundle
import android.text.InputType
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.lockoutprotocol.guardian.data.Prefs

/** Free-text guidelines that get injected into the model prompt as the rule set. */
class GuidelinesActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = Prefs.get(this)

        val editor = EditText(this).apply {
            setText(prefs.guidelines)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
            minLines = 8
            gravity = android.view.Gravity.TOP
        }
        val save = Button(this).apply {
            text = "Save guidelines"
            setOnClickListener { prefs.guidelines = editor.text.toString(); Toast.makeText(this@GuidelinesActivity, "Saved", Toast.LENGTH_SHORT).show(); finish() }
        }
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 48, 48, 48)
            addView(TextView(this@GuidelinesActivity).apply { text = "Guidelines (what counts as a violation)"; textSize = 22f })
            addView(editor); addView(save)
        }
        setContentView(ScrollView(this).apply { addView(col) })
    }
}
