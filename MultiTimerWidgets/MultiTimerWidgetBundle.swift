import SwiftUI
import WidgetKit

@main
struct MultiTimerWidgetBundle: WidgetBundle {
    var body: some Widget {
        FavoritePresetsWidget()
        CurrentTimerWidget()
        TimerLiveActivity()
    }
}
