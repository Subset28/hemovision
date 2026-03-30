#ifndef CORE_ENGINE_H
#define CORE_ENGINE_H

#include <cstdint>

#ifdef _WIN32
#define FFI_PLUGIN_EXPORT __declspec(dllexport)
#else
#define FFI_PLUGIN_EXPORT __attribute__((visibility("default"))) __attribute__((used))
#endif

extern "C" {

    // ─────────────────────────────────────────────────────────────────────────
    //  DATA STRUCTURES — mirrored in Dart via dart:ffi Struct definitions
    // ─────────────────────────────────────────────────────────────────────────

    struct DetectedObject {
        int   class_id;             // 0=Person 1=Car 2=Chair etc.
        float x;                    // Bounding box center X (pixels)
        float y;                    // Bounding box center Y (pixels)
        float width;                // Bounding box width (pixels)
        float height;               // Bounding box height (pixels)
        float estimated_distance;   // Meters (focal-length inverse formula)
        float threat_level;         // 0-100 composite threat score
    };

    struct SpatialPoint {
        float x;                    // World X coordinate
        float y;                    // World Y coordinate
        float z;                    // Distance / depth estimate
        int   persistence_frames;   // Lifespan counter (decays to 0 → delete)
    };

    // ─────────────────────────────────────────────────────────────────────────
    //  LIFECYCLE
    // ─────────────────────────────────────────────────────────────────────────

    FFI_PLUGIN_EXPORT intptr_t init_omnisight_engine();
    FFI_PLUGIN_EXPORT void     destroy_omnisight_engine(intptr_t engine_handle);

    // ─────────────────────────────────────────────────────────────────────────
    //  MODULE A — Vision Processing
    //  Processes one camera frame and fills out_objects[0..n-1].
    //  Returns: number of objects detected (≤ max_objects).
    // ─────────────────────────────────────────────────────────────────────────
    FFI_PLUGIN_EXPORT int process_vision_frame(
        intptr_t        engine_handle,
        uint8_t*        image_data,     // Raw RGBA/RGB pixel bytes (may be null in sim)
        int             width,
        int             height,
        DetectedObject* out_objects,
        int             max_objects
    );

    // ─────────────────────────────────────────────────────────────────────────
    //  MODULE B — Audio FFT Processing
    //  Analyzes a raw float audio buffer.
    //  out_frequencies[0] = dominant frequency (Hz)
    //  out_frequencies[1] = confidence (0.0–1.0)
    //  Returns: number of values written to out_frequencies.
    // ─────────────────────────────────────────────────────────────────────────
    FFI_PLUGIN_EXPORT int process_audio_fft(
        intptr_t engine_handle,
        float*   audio_buffer,      // Raw PCM samples (null in sim)
        int      buffer_size,
        float*   out_frequencies
    );

    // ─────────────────────────────────────────────────────────────────────────
    //  MODULE D — SLAM-lite Spatial Map Access
    //  Copies up to max_points points from the engine's spatial memory.
    //  Returns: number of points actually copied.
    // ─────────────────────────────────────────────────────────────────────────
    FFI_PLUGIN_EXPORT int get_spatial_map(
        intptr_t      engine_handle,
        SpatialPoint* out_points,
        int           max_points
    );

    // ─────────────────────────────────────────────────────────────────────────
    //  UTILITY
    // ─────────────────────────────────────────────────────────────────────────
    FFI_PLUGIN_EXPORT float estimate_distance(
        float bbox_width,
        float bbox_height,
        int   class_id
    );

}

#endif // CORE_ENGINE_H
