package com.aivisiondrone.groundstation.video

import android.content.ContentResolver
import android.content.ContentValues
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaMuxer
import android.net.Uri
import android.os.Handler
import android.os.HandlerThread
import android.os.ParcelFileDescriptor
import android.provider.MediaStore
import android.util.Log
import java.io.File
import java.nio.ByteBuffer
import org.webrtc.VideoFrame
import org.webrtc.VideoSink

private const val TAG = "LocalVideoRecorder"
private const val MIME_TYPE = MediaFormat.MIMETYPE_VIDEO_AVC
private const val BIT_RATE = 4_000_000
private const val FRAME_RATE = 20
private const val I_FRAME_INTERVAL_S = 2
private const val DEQUEUE_TIMEOUT_US = 10_000L

/**
 * Saves the operator's own local copy of the live video to this device's
 * storage, independent of the Pi's own local recording
 * (companion/comms/video_recorder.py) - both run at once from the same
 * Record button, so footage survives even if only one side is reachable
 * afterward (field request: "video should save in device also").
 *
 * Added as a second VideoSink alongside the SurfaceViewRenderer already
 * displaying this track (see FlyTab.kt). All encode work happens on its
 * own HandlerThread, never on the thread WebRTC calls onFrame() from -
 * this project's guiding priority is STABLE -> LOW LATENCY first, and nothing
 * about a local file save may be allowed to add latency to the operator's
 * live view.
 *
 * Encodes with MediaCodec (H.264) + MediaMuxer (MP4) rather than the
 * WebRTC library's own VideoFileRenderer, which writes raw uncompressed
 * YUV4MPEG2 frames - at 1280x720 that's roughly 1 GB/minute, impractical
 * on a phone and not a format any gallery/player app can open directly.
 *
 * Build-verified only (real gradle assembleDebug), not yet confirmed on a
 * real device - unlike this project's UI-only changes, getting this wrong
 * (a bad stride calculation, an encoder quirk on a specific device) could
 * produce a corrupt or unplayable file rather than something visibly
 * broken on screen, so treat the first real recording it produces as the
 * actual test and report back what you see.
 *
 * A real field report ("video is not saving in mobile device") turned out
 * to be a real bug, not an encoder/stride problem: this used to always
 * write to `Context.getExternalFilesDir(DIRECTORY_MOVIES)`, which is
 * *app-private* external storage - MediaMuxer happily wrote a valid file
 * there, but no Gallery/Photos app or file manager scans that location, so
 * from the operator's point of view the recording simply never appeared
 * anywhere. Fixed via `Output.MediaStoreEntry`: on API 29+ (this app's
 * real-world minimum in practice), the file is written straight into the
 * public `Movies/AI Vision Drone` collection through MediaStore, with
 * `IS_PENDING` held during the write so no app sees a half-written file -
 * no storage permission needed, since creating a new file this app owns is
 * exactly what scoped storage (API 29+) exists to allow without one.
 * `Output.LegacyFile` (the old behavior) is kept only as the API 26-28
 * fallback, where MediaStore's `RELATIVE_PATH`/`IS_PENDING` columns don't
 * exist yet.
 */
sealed class LocalRecordingOutput {
    /** API 29+: writes directly into the public Movies collection via
     * MediaStore, visible in Gallery/Photos and any file manager. */
    class MediaStoreEntry(val resolver: ContentResolver, val uri: Uri) : LocalRecordingOutput()

    /** API 26-28 fallback: MediaStore's scoped-storage columns
     * (RELATIVE_PATH/IS_PENDING) don't exist yet on these versions, so this
     * writes to app-private external storage instead - not Gallery-visible,
     * but consistent with this app's pre-scoped-storage behavior and needs
     * no runtime storage permission either. */
    class LegacyFile(val file: File) : LocalRecordingOutput()
}

class LocalVideoRecorder(private val output: LocalRecordingOutput) : VideoSink {
    private val thread = HandlerThread(TAG).apply { start() }
    private val handler = Handler(thread.looper)

    private var codec: MediaCodec? = null
    private var muxer: MediaMuxer? = null
    private var pfd: ParcelFileDescriptor? = null
    private var videoTrackIndex = -1
    private var muxerStarted = false
    private var configuredWidth = 0
    private var configuredHeight = 0
    private var startTimeNs = -1L

    @Volatile private var stopped = false

    override fun onFrame(frame: VideoFrame) {
        if (stopped) return
        frame.retain()
        handler.post {
            try {
                processFrame(frame)
            } catch (e: Exception) {
                Log.e(TAG, "Dropping a frame during local recording", e)
            } finally {
                frame.release()
            }
        }
    }

    private fun processFrame(frame: VideoFrame) {
        if (stopped) return
        val buffer = frame.buffer
        val width = buffer.width
        val height = buffer.height
        if (codec == null) {
            configure(width, height, frame.rotation)
        } else if (width != configuredWidth || height != configuredHeight) {
            // Resolution changing mid-recording isn't supported - stop
            // cleanly with whatever was captured so far rather than feed
            // the encoder mismatched frame sizes.
            Log.w(TAG, "Video resolution changed mid-recording ($configuredWidth x$configuredHeight -> " +
                "$width x $height) - stopping local recording early")
            finishOnHandlerThread()
            return
        }

        if (startTimeNs < 0) startTimeNs = frame.timestampNs
        val presentationTimeUs = (frame.timestampNs - startTimeNs) / 1000

        val i420 = buffer.toI420() ?: return
        try {
            encodeFrame(i420, presentationTimeUs)
        } finally {
            i420.release()
        }
        drainEncoder(endOfStream = false)
    }

    private fun configure(width: Int, height: Int, rotationDegrees: Int) {
        configuredWidth = width
        configuredHeight = height
        val format = MediaFormat.createVideoFormat(MIME_TYPE, width, height).apply {
            setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible)
            setInteger(MediaFormat.KEY_BIT_RATE, BIT_RATE)
            setInteger(MediaFormat.KEY_FRAME_RATE, FRAME_RATE)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, I_FRAME_INTERVAL_S)
        }
        codec = MediaCodec.createEncoderByType(MIME_TYPE).apply {
            configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            start()
        }
        muxer = when (val out = output) {
            is LocalRecordingOutput.MediaStoreEntry -> {
                val fd = out.resolver.openFileDescriptor(out.uri, "rw")
                    ?: throw java.io.IOException("Could not open MediaStore entry ${out.uri} for writing")
                pfd = fd
                MediaMuxer(fd.fileDescriptor, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            }
            is LocalRecordingOutput.LegacyFile ->
                MediaMuxer(out.file.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
        }.apply {
            // The raw buffer stays in the camera's native (unrotated)
            // orientation - WebRTC's own renderer applies `rotation` at
            // display time rather than baking it into the pixel data (see
            // org.webrtc.VideoFileRenderer for the same assumption). A
            // container-level orientation hint gets a correctly-oriented
            // playback in any standard player without us needing to
            // rotate every plane by hand. Must be set before start().
            setOrientationHint(rotationDegrees)
        }
    }

    private fun encodeFrame(i420: VideoFrame.I420Buffer, presentationTimeUs: Long) {
        val codec = codec ?: return
        val inputIndex = codec.dequeueInputBuffer(DEQUEUE_TIMEOUT_US)
        if (inputIndex < 0) {
            Log.w(TAG, "Encoder input buffer not available, dropping a frame")
            return
        }
        val image = codec.getInputImage(inputIndex)
        if (image == null) {
            // Shouldn't happen with COLOR_FormatYUV420Flexible, but don't
            // wedge the encoder if some device disagrees.
            codec.queueInputBuffer(inputIndex, 0, 0, presentationTimeUs, 0)
            return
        }
        val chromaWidth = (image.width + 1) / 2
        val chromaHeight = (image.height + 1) / 2
        copyPlane(i420.dataY, i420.strideY, image.planes[0], image.width, image.height)
        copyPlane(i420.dataU, i420.strideU, image.planes[1], chromaWidth, chromaHeight)
        copyPlane(i420.dataV, i420.strideV, image.planes[2], chromaWidth, chromaHeight)
        val frameSize = image.width * image.height * 3 / 2
        codec.queueInputBuffer(inputIndex, 0, frameSize, presentationTimeUs, 0)
    }

    /**
     * Copies one plane from an I420Buffer's own stride into a MediaCodec
     * input Image's plane, which may use a different rowStride and, for a
     * semi-planar (e.g. NV12) chroma plane, a pixelStride of 2 instead of
     * 1. Uses absolute-indexed get/put (not relative reads that mutate
     * buffer position) so this can't be thrown off by either buffer's
     * existing position. Deliberately a plain byte-by-byte loop rather
     * than a bulk copy for the interleaved case - correctness matters far
     * more here than throughput, since this can't be verified on a real
     * device from this dev machine; if it turns out to be a real CPU cost
     * on-device, it can be optimized once someone can actually profile it.
     */
    private fun copyPlane(src: ByteBuffer, srcStride: Int, dstPlane: android.media.Image.Plane, width: Int, height: Int) {
        val dst = dstPlane.buffer
        val dstStride = dstPlane.rowStride
        val pixelStride = dstPlane.pixelStride
        for (row in 0 until height) {
            val srcRowStart = row * srcStride
            val dstRowStart = row * dstStride
            for (col in 0 until width) {
                dst.put(dstRowStart + col * pixelStride, src.get(srcRowStart + col))
            }
        }
    }

    private fun drainEncoder(endOfStream: Boolean) {
        val codec = codec ?: return
        val muxer = muxer ?: return
        if (endOfStream) {
            val inputIndex = codec.dequeueInputBuffer(DEQUEUE_TIMEOUT_US)
            if (inputIndex >= 0) {
                codec.queueInputBuffer(inputIndex, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
            }
        }
        val bufferInfo = MediaCodec.BufferInfo()
        while (true) {
            val outputIndex = codec.dequeueOutputBuffer(bufferInfo, DEQUEUE_TIMEOUT_US)
            when {
                outputIndex == MediaCodec.INFO_TRY_AGAIN_LATER -> {
                    if (!endOfStream) return
                    // else: keep polling until the end-of-stream buffer actually comes through
                }
                outputIndex == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                    videoTrackIndex = muxer.addTrack(codec.outputFormat)
                    muxer.start()
                    muxerStarted = true
                }
                outputIndex >= 0 -> {
                    val outputBuffer = codec.getOutputBuffer(outputIndex)
                    if (outputBuffer != null) {
                        if (bufferInfo.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0) {
                            bufferInfo.size = 0
                        }
                        if (bufferInfo.size > 0 && muxerStarted) {
                            outputBuffer.position(bufferInfo.offset)
                            outputBuffer.limit(bufferInfo.offset + bufferInfo.size)
                            muxer.writeSampleData(videoTrackIndex, outputBuffer, bufferInfo)
                        }
                    }
                    codec.releaseOutputBuffer(outputIndex, false)
                    if (bufferInfo.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) {
                        return
                    }
                }
            }
        }
    }

    /** Stops recording and finalizes the MP4 (without this, the file's
     * moov atom is never written and the file won't play at all).
     * Asynchronous - onFinished runs on this recorder's own thread once
     * everything is flushed and released. */
    fun stop(onFinished: (() -> Unit)? = null) {
        stopped = true
        handler.post {
            finishOnHandlerThread()
            onFinished?.invoke()
        }
    }

    private fun finishOnHandlerThread() {
        stopped = true
        try {
            if (codec != null) drainEncoder(endOfStream = true)
        } catch (e: Exception) {
            Log.e(TAG, "Error draining encoder while finishing local recording", e)
        }
        try {
            codec?.stop()
        } catch (e: Exception) {
            Log.e(TAG, "codec.stop() failed", e)
        }
        codec?.release()
        codec = null
        try {
            if (muxerStarted) muxer?.stop()
        } catch (e: Exception) {
            Log.e(TAG, "muxer.stop() failed - the output file may be incomplete/unplayable", e)
        }
        try {
            muxer?.release()
        } catch (e: Exception) {
            Log.e(TAG, "muxer.release() failed", e)
        }
        muxer = null
        try {
            pfd?.close()
        } catch (e: Exception) {
            Log.e(TAG, "Closing the MediaStore file descriptor failed", e)
        }
        pfd = null
        val out = output
        if (out is LocalRecordingOutput.MediaStoreEntry) {
            // Only now does the recording become visible/complete to other
            // apps (Gallery, file managers) - IS_PENDING=1 was set at
            // insert time specifically so nothing sees a half-written file
            // mid-recording.
            try {
                val values = ContentValues().apply { put(MediaStore.Video.Media.IS_PENDING, 0) }
                out.resolver.update(out.uri, values, null, null)
            } catch (e: Exception) {
                Log.e(TAG, "Clearing IS_PENDING on the MediaStore entry failed", e)
            }
        }
        thread.quitSafely()
    }
}
