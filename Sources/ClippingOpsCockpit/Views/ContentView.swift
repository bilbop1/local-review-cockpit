import SwiftUI

struct ContentView: View {
    @StateObject private var store = OpsStore()
    @SceneStorage("selectedSection") private var selectedSectionID = AppSection.dashboard.rawValue

    private var selectedSection: AppSection {
        AppSection(rawValue: selectedSectionID) ?? .dashboard
    }

    private var selectedSectionBinding: Binding<AppSection> {
        Binding {
            selectedSection
        } set: { section in
            selectedSectionID = section.rawValue
        }
    }

    var body: some View {
        NavigationSplitView {
            SidebarView(selection: selectedSectionBinding, store: store)
        } detail: {
            detailView
                .navigationTitle(selectedSection.title)
                .toolbar {
                    ToolbarItemGroup {
                        Button {
                            Task { await store.renderSelectedFeederKits() }
                        } label: {
                            Label("Build Latest Reviews", systemImage: "bolt.badge.play")
                        }
                        .help("Build review-ready clips; this never publishes.")
                        .accessibilityIdentifier("toolbar-render-feeders")

                        Button {
                            Task { await store.refreshForSection(selectedSection) }
                        } label: {
                            Label("Refresh", systemImage: "arrow.clockwise")
                        }
                        .help("Refresh backend state")
                        .accessibilityIdentifier("toolbar-refresh")
                    }
                }
        }
        .accessibilityIdentifier("root-navigation-split")
        .task {
            await store.refreshAll()
        }
        .onReceive(NotificationCenter.default.publisher(for: .refreshOperations)) { _ in
            Task { await store.refreshAll() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .renderSelectedFeederKits)) { _ in
            Task { await store.renderSelectedFeederKits() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .runCampaignGate)) { _ in
            Task { await store.runCampaignGate() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .selectOperationsSection)) { notification in
            if let sectionID = notification.object as? String, AppSection(rawValue: sectionID) != nil {
                selectedSectionID = sectionID
            }
        }
        .onChange(of: selectedSectionID) { _, newValue in
            if AppSection(rawValue: newValue) == .reviewKits {
                Task { await store.refreshReviewSurface() }
            }
        }
    }

    @ViewBuilder
    private var detailView: some View {
        VStack(spacing: 0) {
            if let error = store.lastError {
                HStack {
                    Image(systemName: "exclamationmark.triangle.fill")
                    Text(error)
                        .lineLimit(2)
                    Spacer()
                }
                .font(.callout)
                .foregroundStyle(.red)
                .padding(.horizontal)
                .padding(.vertical, 8)
                .background(.red.opacity(0.08))
            } else if let message = store.lastActionMessage {
                HStack {
                    Image(systemName: "checkmark.circle")
                    Text(message)
                        .lineLimit(2)
                    Spacer()
                }
                .font(.callout)
                .foregroundStyle(.secondary)
                .padding(.horizontal)
                .padding(.vertical, 8)
                .background(.regularMaterial)
            }

            switch selectedSection {
            case .dashboard:
                DashboardView(store: store)
                    .accessibilityIdentifier(AppSection.dashboard.accessibilityID)
            case .campaignGate:
                CampaignGateView(store: store)
                    .accessibilityIdentifier(AppSection.campaignGate.accessibilityID)
            case .sourceManager:
                SourceManagerView(store: store)
                    .accessibilityIdentifier(AppSection.sourceManager.accessibilityID)
            case .clipIndex:
                ClipIndexView(store: store)
                    .accessibilityIdentifier(AppSection.clipIndex.accessibilityID)
            case .nominations:
                NominationsView(store: store)
                    .accessibilityIdentifier(AppSection.nominations.accessibilityID)
            case .renderQueue:
                RenderQueueView(store: store)
                    .accessibilityIdentifier(AppSection.renderQueue.accessibilityID)
            case .reviewKits:
                ReviewKitsView(store: store)
                    .accessibilityIdentifier(AppSection.reviewKits.accessibilityID)
            case .agents:
                AgentsJobsView(store: store)
                    .accessibilityIdentifier(AppSection.agents.accessibilityID)
            case .readiness:
                ReadinessView(store: store)
                    .accessibilityIdentifier(AppSection.readiness.accessibilityID)
            case .auditLog:
                AuditLogView(store: store)
                    .accessibilityIdentifier(AppSection.auditLog.accessibilityID)
            case .settings:
                SettingsView(store: store)
                    .accessibilityIdentifier(AppSection.settings.accessibilityID)
            }
        }
    }
}
