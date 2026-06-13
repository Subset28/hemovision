

import OmniSightKit


import SwiftUI

@main
struct OmniSightAppEntry: App {
    
    @UIApplicationDelegateAdaptor(AppDelegate.self) var delegate
    
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
