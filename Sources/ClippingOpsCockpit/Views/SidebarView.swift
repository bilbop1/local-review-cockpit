import SwiftUI

struct SidebarView: View {
    @Binding var selection: AppSection
    @ObservedObject var store: OpsStore
    @AppStorage("showAdvancedWorkbench") private var showAdvancedWorkbench = false

    var body: some View {
        List(selection: $selection) {
            Section("Cockpit") {
                ForEach(AppSection.operatorSections) { section in
                    sidebarRow(section)
                }
            }
            Section("System") {
                sidebarRow(.settings)
            }
            DisclosureGroup(isExpanded: $showAdvancedWorkbench) {
                ForEach(AppSection.agentSections) { section in
                    sidebarRow(section)
                }
            } label: {
                Label("Advanced", systemImage: "slider.horizontal.3")
                    .foregroundStyle(.secondary)
            }
        }
        .listStyle(.sidebar)
        .accessibilityIdentifier("sidebar")
        .safeAreaInset(edge: .bottom) {
            sidebarFooter
        }
    }

    private func sidebarRow(_ section: AppSection) -> some View {
        Label(section.title, systemImage: section.systemImage)
            .tag(section)
            .accessibilityIdentifier("sidebar-\(section.rawValue)")
            .accessibilityLabel(section.title)
    }

    private var sidebarFooter: some View {
        VStack(alignment: .leading, spacing: 8) {
            Divider()
            HStack {
                Circle()
                    .fill(statusColor(store.health?.status ?? "blocked"))
                    .frame(width: 8, height: 8)
                Text(store.health.map { displayStatus($0.status) } ?? "Connecting")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                if store.isLoading {
                    ProgressView()
                        .controlSize(.small)
                }
            }
            .padding(.horizontal, 14)
            .padding(.bottom, 10)
        }
    }
}
