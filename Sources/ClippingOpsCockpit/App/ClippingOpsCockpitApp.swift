import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
}

@main
struct ClippingOpsCockpitApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup("Clipping Ops Cockpit", id: "main") {
            ContentView()
                .frame(minWidth: 1120, minHeight: 720)
        }
        .commands {
            CommandMenu("Operations") {
                Button("Refresh") {
                    NotificationCenter.default.post(name: .refreshOperations, object: nil)
                }
                .keyboardShortcut("r", modifiers: [.command])

                Button("Build Latest Reviews") {
                    NotificationCenter.default.post(name: .renderSelectedFeederKits, object: nil)
                }
                .keyboardShortcut("d", modifiers: [.command, .shift])

                Button("Refresh Campaigns") {
                    NotificationCenter.default.post(name: .runCampaignGate, object: nil)
                }
                .keyboardShortcut("g", modifiers: [.command, .shift])

                Divider()

                Button("Dashboard") {
                    NotificationCenter.default.post(name: .selectOperationsSection, object: AppSection.dashboard.rawValue)
                }
                .keyboardShortcut("1", modifiers: [.command])

                Button("Campaigns") {
                    NotificationCenter.default.post(name: .selectOperationsSection, object: AppSection.campaignGate.rawValue)
                }
                .keyboardShortcut("2", modifiers: [.command])

                Button("Sources") {
                    NotificationCenter.default.post(name: .selectOperationsSection, object: AppSection.sourceManager.rawValue)
                }
                .keyboardShortcut("3", modifiers: [.command])

                Button("Clip Index") {
                    NotificationCenter.default.post(name: .selectOperationsSection, object: AppSection.clipIndex.rawValue)
                }
                .keyboardShortcut("4", modifiers: [.command])

                Button("Nominations") {
                    NotificationCenter.default.post(name: .selectOperationsSection, object: AppSection.nominations.rawValue)
                }
                .keyboardShortcut("5", modifiers: [.command])

                Button("Render Queue") {
                    NotificationCenter.default.post(name: .selectOperationsSection, object: AppSection.renderQueue.rawValue)
                }
                .keyboardShortcut("6", modifiers: [.command])

                Button("Review Kits") {
                    NotificationCenter.default.post(name: .selectOperationsSection, object: AppSection.reviewKits.rawValue)
                }
                .keyboardShortcut("7", modifiers: [.command])

                Button("Agents / Jobs") {
                    NotificationCenter.default.post(name: .selectOperationsSection, object: AppSection.agents.rawValue)
                }
                .keyboardShortcut("8", modifiers: [.command])

                Button("Readiness") {
                    NotificationCenter.default.post(name: .selectOperationsSection, object: AppSection.readiness.rawValue)
                }
                .keyboardShortcut("9", modifiers: [.command])

                Button("Audit Log") {
                    NotificationCenter.default.post(name: .selectOperationsSection, object: AppSection.auditLog.rawValue)
                }
                .keyboardShortcut("0", modifiers: [.command])

                Button("Settings") {
                    NotificationCenter.default.post(name: .selectOperationsSection, object: AppSection.settings.rawValue)
                }
                .keyboardShortcut(",", modifiers: [.command, .shift])
            }
        }

        Settings {
            SettingsView(store: OpsStore())
                .frame(width: 760, height: 520)
        }
    }
}
