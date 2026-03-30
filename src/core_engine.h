#ifndef CORE_ENGINE_H
#define CORE_ENGINE_H

#include <cstdint>

#ifdef _WIN32
#define FFI_PLUGIN_EXPORT __declspec(dllexport)
#else
#define FFI_PLUGIN_EXPORT __attribute__((visibility("default"))) __attribute__((used))
#endif

extern "C" {

    // Struct for sending object bounding box and distance back to Flutter
    struct DetectedObject {
        int class_id;
        float x;
        float y;
        float width;
        float height;
        float estimated_distance;
        float threat_level; // Calculated from distance and size
    };

    // System initialization and destruction
    FFI_PLUGIN_EXPORT intptr_t init_omnisight_engine();
    FFI_PLUGIN_EXPORT void destroy_omnisight_engine(intptr_t engine_handle);

    // Module A: Vision Processing (Placeholder for OpenCV/YOLO inference)
    // Processes a single frame and returns the number of detected objects. 
    // Populates the out_objects array.
    FFI_PLUGIN_EXPORT int process_vision_frame(intptr_t engine_handle, uint8_t* image_data, int width, int height, DetectedObject* out_objects, int max_objects);

    // Module B: Audio Processing (Placeholder for FFT/Microphone capture)
    // Analyzes audio and returns dominant frequency characteristics or triggers
    FFI_PLUGIN_EXPORT int process_audio_fft(intptr_t engine_handle, float* audio_buffer, int buffer_size, float* out_frequencies);

    // Master calculation for custom distance estimation
    FFI_PLUGIN_EXPORT float estimate_distance(float bbox_width, float bbox_height, int class_id);

}

#endif // CORE_ENGINE_H
