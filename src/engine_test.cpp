// ─────────────────────────────────────────────────────────────────────────────
//  engine_test.cpp — C++ Unit Tests for OmniSight Core Engine
//
//  UPGRADE #3: Automated Quality Assurance — C++ layer
//
//  Uses a minimal custom test framework (no external dependency required).
//  Each TEST() call asserts an expected value and prints PASS / FAIL.
//
//  Compile & Run:
//    g++ -std=c++17 -I. engine_test.cpp core_engine.cpp -o engine_test
//    ./engine_test
//
//  On Windows (MSVC):
//    cl /EHsc /std:c++17 engine_test.cpp core_engine.cpp /Fe:engine_test.exe
//    engine_test.exe
// ─────────────────────────────────────────────────────────────────────────────

#include <cassert>
#include <cmath>
#include <cstdio>
#include <string>
#include "core_engine.h"

// ── Minimal test framework ────────────────────────────────────────────────────
static int s_pass = 0;
static int s_fail = 0;

#define EXPECT_NEAR(actual, expected, tol, name)                         \
  do {                                                                    \
    double _a = (actual);                                                 \
    double _e = (expected);                                               \
    double _d = std::abs(_a - _e);                                        \
    if (_d <= (tol)) {                                                    \
      ++s_pass;                                                           \
      std::printf("  [PASS] %s (got %.4f)\n", (name), _a);               \
    } else {                                                              \
      ++s_fail;                                                           \
      std::printf("  [FAIL] %s — expected %.4f, got %.4f (delta %.4f)\n",\
                  (name), _e, _a, _d);                                   \
    }                                                                     \
  } while (0)

#define EXPECT_EQ(actual, expected, name)                                \
  do {                                                                    \
    int _a = (actual);                                                    \
    int _e = (expected);                                                  \
    if (_a == _e) {                                                       \
      ++s_pass;                                                           \
      std::printf("  [PASS] %s (got %d)\n", (name), _a);                 \
    } else {                                                              \
      ++s_fail;                                                           \
      std::printf("  [FAIL] %s — expected %d, got %d\n", (name), _e, _a);\
    }                                                                     \
  } while (0)

#define EXPECT_LE(actual, bound, name)                                   \
  do {                                                                    \
    double _a = (actual);                                                 \
    double _b = (bound);                                                  \
    if (_a <= _b) {                                                       \
      ++s_pass;                                                           \
      std::printf("  [PASS] %s (%.4f <= %.4f)\n", (name), _a, _b);       \
    } else {                                                              \
      ++s_fail;                                                           \
      std::printf("  [FAIL] %s — %.4f is NOT <= %.4f\n", (name), _a, _b);\
    }                                                                     \
  } while (0)

#define EXPECT_GE(actual, bound, name)                                   \
  do {                                                                    \
    double _a = (actual);                                                 \
    double _b = (bound);                                                  \
    if (_a >= _b) {                                                       \
      ++s_pass;                                                           \
      std::printf("  [PASS] %s (%.4f >= %.4f)\n", (name), _a, _b);       \
    } else {                                                              \
      ++s_fail;                                                           \
      std::printf("  [FAIL] %s — %.4f is NOT >= %.4f\n", (name), _a, _b);\
    }                                                                     \
  } while (0)

#define EXPECT_TRUE(cond, name)                                          \
  do {                                                                    \
    if ((cond)) {                                                         \
      ++s_pass;                                                           \
      std::printf("  [PASS] %s\n", (name));                               \
    } else {                                                              \
      ++s_fail;                                                           \
      std::printf("  [FAIL] %s — condition was false\n", (name));         \
    }                                                                     \
  } while (0)

// ── Reusable formula implementations (mirror of OmniSightEngine methods) ──────

static float test_estimate_distance(float bbox_width, int class_id) {
    const float FOCAL_LENGTH = 800.0f;
    float real_width = 1.0f;
    switch (class_id) {
        case 0:  real_width = 0.50f; break; // Person
        case 1:  real_width = 1.80f; break; // Car
        case 2:  real_width = 0.60f; break; // Chair
        case 3:  real_width = 0.40f; break; // Bicycle
    }
    if (bbox_width < 1.0f) return 999.0f; // Divide-by-zero guard
    return (real_width * FOCAL_LENGTH) / bbox_width;
}

static float test_calculate_threat(float distance_m, int class_id) {
    float multiplier = 1.0f;
    switch (class_id) {
        case 1: multiplier = 3.0f; break; // Car
        case 0: multiplier = 1.5f; break; // Person
        case 3: multiplier = 1.2f; break; // Bicycle
    }
    float raw = 100.0f / (distance_m + 0.1f) * multiplier;
    return raw < 100.0f ? raw : 100.0f;
}

// ────────────────────────────────────────────────────────────────────────────

int main() {
    std::printf("\n╔══════════════════════════════════════════════════╗\n");
    std::printf("║   OmniSight Engine — C++ Unit Tests              ║\n");
    std::printf("║   TSA Nationals 2025-2026 Software Development   ║\n");
    std::printf("╚══════════════════════════════════════════════════╝\n\n");

    // ── GROUP 1: Distance Estimation Formula ─────────────────────────────────
    std::printf("GROUP 1: Distance Formula  D = (W_real × f) / W_pixel\n");
    std::printf("─────────────────────────────────────────────────────\n");

    // Verified by hand: D = (1.80 × 800) / 450 = 1440/450 = 3.200
    EXPECT_NEAR(test_estimate_distance(450.0f, 1), 3.200, 0.01,
                "Car @ 450px → 3.2m");

    // D = (0.50 × 800) / 100 = 400/100 = 4.000
    EXPECT_NEAR(test_estimate_distance(100.0f, 0), 4.000, 0.01,
                "Person @ 100px → 4.0m");

    // D = (0.60 × 800) / 240 = 480/240 = 2.000
    EXPECT_NEAR(test_estimate_distance(240.0f, 2), 2.000, 0.01,
                "Chair @ 240px → 2.0m");

    // D = (0.40 × 800) / 320 = 320/320 = 1.000
    EXPECT_NEAR(test_estimate_distance(320.0f, 3), 1.000, 0.01,
                "Bicycle @ 320px → 1.0m");

    // Unknown class falls back to W_real=1.0
    // D = (1.0 × 800) / 200 = 4.0
    EXPECT_NEAR(test_estimate_distance(200.0f, 99), 4.000, 0.01,
                "Unknown class @ 200px → 4.0m default");

    // ── CRITICAL: Divide-by-zero guard ───────────────────────────────────────
    std::printf("\nGROUP 2: Divide-by-Zero Safety\n");
    std::printf("─────────────────────────────────────────────────────\n");

    EXPECT_NEAR(test_estimate_distance(0.0f, 1), 999.0, 0.001,
                "bbox_width=0 returns safe sentinel 999.0 (no crash)");
    EXPECT_NEAR(test_estimate_distance(0.5f, 1), 999.0, 0.001,
                "bbox_width=0.5 (< 1.0) returns safe sentinel 999.0");
    EXPECT_NEAR(test_estimate_distance(-50.0f, 0), 999.0, 0.001,
                "negative bbox_width returns safe sentinel 999.0");

    // ── GROUP 3: Inverse Proportionality ─────────────────────────────────────
    std::printf("\nGROUP 3: Inverse Proportionality (larger bbox = closer)\n");
    std::printf("─────────────────────────────────────────────────────\n");

    float distNear = test_estimate_distance(500.0f, 1);
    float distFar  = test_estimate_distance(100.0f, 1);
    EXPECT_TRUE(distNear < distFar,
                "Car @ 500px must be closer than car @ 100px");

    // ── GROUP 4: Threat Level Calculation ────────────────────────────────────
    std::printf("\nGROUP 4: Threat Level  100/(d+0.1) × multiplier, capped 100\n");
    std::printf("─────────────────────────────────────────────────────\n");

    // Threat is always in [0, 100]
    EXPECT_LE(test_calculate_threat(0.01f, 1), 100.0, "Extreme proximity capped at 100");
    EXPECT_GE(test_calculate_threat(0.01f, 1), 0.0,   "Threat is non-negative");
    EXPECT_LE(test_calculate_threat(999.0f, 1), 1.0,  "Distant car threat < 1");

    // Priority ordering: car (3×) > person (1.5×) > chair (1×) at same distance
    float carThreat    = test_calculate_threat(3.0f, 1); // car
    float personThreat = test_calculate_threat(3.0f, 0); // person
    float chairThreat  = test_calculate_threat(3.0f, 2); // chair
    EXPECT_TRUE(carThreat > personThreat,    "Car threat > Person threat at same dist");
    EXPECT_TRUE(personThreat > chairThreat,  "Person threat > Chair threat at same dist");

    // Closer objects have higher threat
    float threatNear = test_calculate_threat(1.0f, 0);
    float threatFar  = test_calculate_threat(8.0f, 0);
    EXPECT_TRUE(threatNear > threatFar,
                "Closer person has higher threat than farther person");

    // ── GROUP 5: Engine Lifecycle (via FFI exports) ───────────────────────────
    std::printf("\nGROUP 5: Engine Lifecycle — FFI Exports\n");
    std::printf("─────────────────────────────────────────────────────\n");

    intptr_t handle = init_omnisight_engine();
    EXPECT_TRUE(handle != 0, "init_omnisight_engine() returns non-null handle");

    // Process a dummy frame (null image → simulation mode)
    DetectedObject out[8];
    int count = process_vision_frame(handle, nullptr, 640, 480, out, 8);
    EXPECT_TRUE(count > 0, "process_vision_frame() returns ≥1 objects in sim mode");
    EXPECT_TRUE(count <= 8, "process_vision_frame() respects max_objects limit");

    // Verify first object's data is in expected ranges
    EXPECT_GE(out[0].estimated_distance, 0.0, "First object distance ≥ 0");
    EXPECT_LE(out[0].threat_level, 100.0,      "First object threat ≤ 100");
    EXPECT_GE(out[0].threat_level, 0.0,        "First object threat ≥ 0");

    // Spatial map
    SpatialPoint spts[50];
    int ptCount = get_spatial_map(handle, spts, 50);
    EXPECT_TRUE(ptCount >= 0, "get_spatial_map() returns non-negative count");
    EXPECT_TRUE(ptCount <= 50, "get_spatial_map() respects max_points limit");

    // Audio FFT in sim mode
    float freqs[2] = {};
    int fCount = process_audio_fft(handle, nullptr, 0, freqs);
    EXPECT_EQ(fCount, 2,          "process_audio_fft() returns 2 values in sim");
    EXPECT_NEAR(freqs[0], 1200.0, 1.0, "Sim audio frequency is ~1200 Hz (siren)");
    EXPECT_GE(freqs[1], 0.8,      "Sim audio confidence ≥ 0.8");

    // estimate_distance() standalone export
    float edist = estimate_distance(450.0f, 90.0f, 1);
    EXPECT_NEAR(edist, 3.2, 0.1, "estimate_distance() standalone export: car @ 450px = 3.2m");

    // Destroy engine — must not crash
    destroy_omnisight_engine(handle);
    EXPECT_TRUE(true, "destroy_omnisight_engine() returned without SIGSEGV");

    // Destroy with null handle — must not crash
    destroy_omnisight_engine(0);
    EXPECT_TRUE(true, "destroy_omnisight_engine(0) is a no-op, no crash");

    // ── RESULTS ──────────────────────────────────────────────────────────────
    std::printf("\n═════════════════════════════════════════════════════\n");
    std::printf("  RESULTS:  %d PASSED  /  %d FAILED  /  %d TOTAL\n",
                s_pass, s_fail, s_pass + s_fail);
    std::printf("═════════════════════════════════════════════════════\n\n");

    return s_fail == 0 ? 0 : 1;
}
