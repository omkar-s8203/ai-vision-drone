package com.aivisiondrone.groundstation.comms

import org.json.JSONObject

/** org.json's optX methods don't distinguish "missing" from explicit JSON
 * null, which the Python side sends often (e.g. no target selected yet). */
fun JSONObject.optDoubleOrNull(key: String): Double? =
    if (has(key) && !isNull(key)) getDouble(key) else null

fun JSONObject.optIntOrNull(key: String): Int? =
    if (has(key) && !isNull(key)) getInt(key) else null

fun JSONObject.optStringOrNull(key: String): String? =
    if (has(key) && !isNull(key)) getString(key) else null
