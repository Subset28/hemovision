// ─────────────────────────────────────────────────────────────────────────────
//  CAREGIVER SERVICE — Conditional Dispatcher
// ─────────────────────────────────────────────────────────────────────────────

export 'caregiver_service_web.dart' 
  if (dart.library.ffi) 'caregiver_service_native.dart';
