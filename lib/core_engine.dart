// ─────────────────────────────────────────────────────────────────────────────
//  OmniSight Engine — Conditional Dispatcher
//
//  This file dynamically exports the correct implementation of the vision
//  engine based on the platform's capabilities.
//
//  • Native (Mobile/Desktop): Uses dart:ffi for direct C++ Yolo inference.
//  • Web (Chrome/Edge):       Uses a mock shim to allow UI/Layout validation.
// ─────────────────────────────────────────────────────────────────────────────

export 'core_engine_web.dart' 
  if (dart.library.ffi) 'core_engine_ffi.dart';
