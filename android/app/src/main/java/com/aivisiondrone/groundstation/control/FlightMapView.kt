package com.aivisiondrone.groundstation.control

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import com.aivisiondrone.groundstation.telemetry.LatLon
import com.aivisiondrone.groundstation.ui.theme.DroneColors
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min

private const val METERS_PER_DEGREE_LAT = 111_320.0
private fun metersPerDegreeLon(refLatDeg: Double): Double = METERS_PER_DEGREE_LAT * cos(Math.toRadians(refLatDeg))

private data class LocalPoint(val eastM: Float, val northM: Float)

private fun toLocal(point: LatLon, ref: LatLon): LocalPoint {
    val north = ((point.lat - ref.lat) * METERS_PER_DEGREE_LAT).toFloat()
    val east = ((point.lon - ref.lon) * metersPerDegreeLon(ref.lat)).toFloat()
    return LocalPoint(east, north)
}

/**
 * A fully offline, vector-drawn position map - no online map tiles, ever
 * (this project uses no internet access anywhere, by design - see the
 * root README's "Offline operation" section). Plots the drone's current
 * position, home, its accumulated flight path (FlightPathTrail.kt), and -
 * when active - the planned grid-search route (GridSearchControls.kt),
 * all as local-meters offsets from a reference point (home if known,
 * otherwise the drone's own current position) using a flat
 * equirectangular approximation. That approximation is entirely adequate
 * at the scale a companion-computer drone actually operates over
 * (hundreds of meters to a few km) - it is not meant for long-range
 * navigation, and the Pi's own guidance math (companion/guidance/geo.py)
 * uses real spherical geodesy, not this simplified local view.
 *
 * A field request: "live map view (drone position, home, flight path)."
 */
@Composable
fun FlightMapView(
    droneLat: Double?,
    droneLon: Double?,
    headingDeg: Double?,
    homeLat: Double?,
    homeLon: Double?,
    flightPath: List<LatLon>,
    gridSearchWaypoints: List<LatLon>,
    gridSearchCurrentIndex: Int,
    modifier: Modifier = Modifier,
) {
    val reference = when {
        homeLat != null && homeLon != null -> LatLon(homeLat, homeLon)
        droneLat != null && droneLon != null -> LatLon(droneLat, droneLon)
        else -> null
    }

    Canvas(modifier = modifier.fillMaxWidth().aspectRatio(1f)) {
        if (reference == null) return@Canvas

        val home = if (homeLat != null && homeLon != null) toLocal(LatLon(homeLat, homeLon), reference) else null
        val drone = if (droneLat != null && droneLon != null) toLocal(LatLon(droneLat, droneLon), reference) else null
        val path = flightPath.map { toLocal(it, reference) }
        val waypoints = gridSearchWaypoints.map { toLocal(it, reference) }

        val allPoints = buildList {
            home?.let { add(it) }
            drone?.let { add(it) }
            addAll(path)
            addAll(waypoints)
        }
        if (allPoints.isEmpty()) return@Canvas

        val maxExtentM = allPoints.maxOf { max(abs(it.eastM), abs(it.northM)) }
        // Padding around the plotted extent, and a sane floor so a
        // stationary aircraft right at home doesn't zoom in to a
        // meaningless few centimeters of canvas.
        val halfSpanM = max(maxExtentM * 1.25f, 10f)
        val scale = (min(size.width, size.height) / 2f) / halfSpanM
        val center = Offset(size.width / 2f, size.height / 2f)

        fun toScreen(p: LocalPoint): Offset = Offset(center.x + p.eastM * scale, center.y - p.northM * scale)

        // Range rings for a sense of scale, not precise measurement.
        drawCircle(DroneColors.SurfaceElevated, radius = halfSpanM * scale, center = center, style = Stroke(width = 1f))
        drawCircle(
            DroneColors.SurfaceElevated,
            radius = halfSpanM * scale / 2f,
            center = center,
            style = Stroke(width = 1f),
        )

        if (path.size >= 2) {
            val pathShape = Path()
            val first = toScreen(path.first())
            pathShape.moveTo(first.x, first.y)
            for (point in path.drop(1)) {
                val screen = toScreen(point)
                pathShape.lineTo(screen.x, screen.y)
            }
            drawPath(pathShape, color = DroneColors.Accent.copy(alpha = 0.6f), style = Stroke(width = 3f))
        }

        if (waypoints.size >= 2) {
            val routeShape = Path()
            val first = toScreen(waypoints.first())
            routeShape.moveTo(first.x, first.y)
            for (point in waypoints.drop(1)) {
                val screen = toScreen(point)
                routeShape.lineTo(screen.x, screen.y)
            }
            drawPath(
                routeShape,
                color = DroneColors.Warning.copy(alpha = 0.8f),
                style = Stroke(width = 3f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(16f, 10f))),
            )
            waypoints.forEachIndexed { index, point ->
                val screen = toScreen(point)
                val visited = index < gridSearchCurrentIndex
                drawCircle(
                    color = if (visited) DroneColors.TextSecondary else DroneColors.Warning,
                    radius = 5f,
                    center = screen,
                )
            }
        }

        home?.let {
            val screen = toScreen(it)
            drawCircle(color = DroneColors.Safe, radius = 10f, center = screen, style = Stroke(width = 3f))
            drawCircle(color = DroneColors.Safe, radius = 3f, center = screen)
        }

        drone?.let {
            val screen = toScreen(it)
            if (headingDeg != null) {
                rotate(degrees = headingDeg.toFloat(), pivot = screen) {
                    val arrow = Path().apply {
                        moveTo(screen.x, screen.y - 14f)
                        lineTo(screen.x - 9f, screen.y + 10f)
                        lineTo(screen.x, screen.y + 4f)
                        lineTo(screen.x + 9f, screen.y + 10f)
                        close()
                    }
                    drawPath(arrow, color = DroneColors.Accent)
                }
            } else {
                drawCircle(color = DroneColors.Accent, radius = 8f, center = screen)
            }
        }
    }
}
