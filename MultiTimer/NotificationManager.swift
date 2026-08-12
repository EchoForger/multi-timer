import Foundation
import MultiTimerCore
import UserNotifications

final class NotificationManager: NSObject, UNUserNotificationCenterDelegate {
    private let center = UNUserNotificationCenter.current()
    private weak var model: AppModel?

    func configure(model: AppModel) {
        self.model = model
        center.delegate = self
        let extend = UNNotificationAction(identifier: "extend-five", title: "+5 minutes")
        let skip = UNNotificationAction(identifier: "skip-rest", title: "Skip break")
        let startFocus = UNNotificationAction(
            identifier: "start-focus",
            title: NSLocalizedString("Start Focus", comment: "Notification")
        )
        center.setNotificationCategories([
            UNNotificationCategory(identifier: "timer-finished", actions: [extend], intentIdentifiers: []),
            UNNotificationCategory(identifier: "work-finished", actions: [extend, skip], intentIdentifiers: []),
            UNNotificationCategory(identifier: "rest-finished", actions: [startFocus], intentIdentifiers: []),
        ])
        requestAuthorization(completion: {})
    }

    func requestAuthorization(completion: @escaping () -> Void) {
        center.requestAuthorization(options: [.alert, .sound]) { _, _ in completion() }
    }

    func authorizationStatus(completion: @escaping (UNAuthorizationStatus) -> Void) {
        center.getNotificationSettings { completion($0.authorizationStatus) }
    }

    func timerFinished(_ timer: TimerRecord) {
        send(
            title: timer.label,
            body: NSLocalizedString("Timer finished.", comment: "Notification"),
            category: "timer-finished",
            sound: .default,
            userInfo: ["timerID": timer.id]
        )
    }

    func pomodoroFinished(_ phase: PomodoroPhase) {
        if phase == .work {
            send(
                title: NSLocalizedString("Focus complete", comment: "Notification"),
                body: NSLocalizedString("Time for a break.", comment: "Notification"),
                category: "work-finished",
                sound: UNNotificationSound(named: UNNotificationSoundName("Glass.aiff"))
            )
        } else {
            send(
                title: NSLocalizedString("Break complete", comment: "Notification"),
                body: NSLocalizedString("Ready for another focus session?", comment: "Notification"),
                category: "rest-finished",
                sound: UNNotificationSound(named: UNNotificationSoundName("Submarine.aiff"))
            )
        }
    }

    private func send(
        title: String,
        body: String,
        category: String,
        sound: UNNotificationSound,
        userInfo: [AnyHashable: Any] = [:]
    ) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.categoryIdentifier = category
        content.sound = sound
        content.userInfo = userInfo
        center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        Task { @MainActor [weak self] in
            guard let model = self?.model else { completionHandler(); return }
            switch response.actionIdentifier {
            case "extend-five":
                if let timerID = response.notification.request.content.userInfo["timerID"] as? String {
                    model.restart(timerID)
                    model.setRemaining(timerID, seconds: 300)
                } else {
                    model.extendPomodoro()
                }
            case "skip-rest": model.skipPomodoro()
            case "start-focus": model.startPomodoro()
            default: break
            }
            completionHandler()
        }
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound])
    }
}
