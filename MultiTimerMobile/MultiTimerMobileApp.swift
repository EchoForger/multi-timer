import SwiftUI

@main
struct MultiTimerMobileApp: App {
    @StateObject private var model = MobileAppModel()

    var body: some Scene {
        WindowGroup {
            MobileRootView(model: model)
                .onOpenURL(perform: model.handle)
                .alert("End timer?", isPresented: Binding(
                    get: { model.pendingEndTimerID != nil },
                    set: { if !$0 { model.pendingEndTimerID = nil } }
                )) {
                    Button("Cancel", role: .cancel) { model.pendingEndTimerID = nil }
                    Button("End", role: .destructive) { model.confirmPendingEnd() }
                } message: {
                    Text("This action ends the timer on all synced devices.")
                }
        }
    }
}
