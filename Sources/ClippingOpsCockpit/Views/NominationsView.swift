import SwiftUI

struct NominationsView: View {
    @ObservedObject var store: OpsStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                SectionHeader(title: "Viral Nominations", subtitle: "Rendering is intentionally scarce. Nominations need a reason before they become review kits.")
                if store.nominations.isEmpty {
                    EmptyStateView(title: "No Nominations", message: "No clips have passed scoring into the render lane yet.", systemImage: "sparkles.tv")
                        .frame(height: 360)
                } else {
                    ForEach(store.nominations) { nomination in
                        VStack(alignment: .leading, spacing: 10) {
                            HStack {
                                Text(nomination.nominationType.capitalized)
                                    .font(.headline)
                                Spacer()
                                StatusPill(text: nomination.status)
                            }
                            Text(nomination.scoreReason)
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)
                            InfoRow(label: "Target style", value: nomination.targetStyle)
                            InfoRow(label: "Created", value: nomination.createdAt)
                        }
                        .padding(16)
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
                    }
                }
            }
            .padding(22)
        }
    }
}
