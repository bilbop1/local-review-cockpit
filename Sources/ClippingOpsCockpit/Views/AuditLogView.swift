import SwiftUI

struct AuditLogView: View {
    @ObservedObject var store: OpsStore

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionHeader(title: "Audit Log", subtitle: "Append-only operational truth trail.")
                .padding(22)
            if store.auditEvents.isEmpty {
                EmptyStateView(title: "No Audit Events", message: "Audit records will appear as jobs and review actions run.", systemImage: "list.bullet.clipboard")
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        ForEach(store.auditEvents) { event in
                            VStack(alignment: .leading, spacing: 8) {
                                HStack(alignment: .firstTextBaseline) {
                                    Text(event.action)
                                        .font(.headline)
                                    Spacer()
                                    Text(event.timestamp)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                HStack(spacing: 12) {
                                    Label(event.actor, systemImage: "person.circle")
                                    Text("\(event.targetType) / \(event.targetID)")
                                        .foregroundStyle(.secondary)
                                }
                                .font(.caption)
                                Text(shortText(event.result, limit: 180))
                                    .font(.callout)
                                    .textSelection(.enabled)
                            }
                            .padding(14)
                            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
                        }
                    }
                    .padding(.horizontal, 22)
                    .padding(.bottom, 22)
                }
            }
        }
    }
}
