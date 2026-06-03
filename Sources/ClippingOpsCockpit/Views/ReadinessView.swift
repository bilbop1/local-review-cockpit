import SwiftUI

struct ReadinessView: View {
    @ObservedObject var store: OpsStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                SectionHeader(
                    title: "Readiness",
                    subtitle: "A short truth board first, with proof details tucked underneath."
                )

                if let report = store.readiness {
                    overview(report)
                    milestoneGrid(report)
                    proofList(report)
                } else {
                    EmptyStateView(title: "No Readiness Report", message: "Refresh to load the readiness report.", systemImage: "checkmark.seal")
                        .frame(height: 340)
                }
            }
            .padding(22)
        }
    }

    private func overview(_ report: ReadinessReport) -> some View {
        LiquidPanel(tint: statusColor(report.overall)) {
            HStack(alignment: .center, spacing: 16) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Overall")
                        .font(.headline)
                    Text("Generated \(displayDateTime(report.generatedAt))")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                StatusPill(text: displayUserStatus(report.overall), systemImage: "checkmark.seal")
            }
        }
    }

    private func milestoneGrid(_ report: ReadinessReport) -> some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
            ForEach(milestoneOrder) { item in
                if let milestone = report.milestones[item.id] {
                    ReadinessMilestoneCard(title: item.title, milestone: milestone)
                }
            }
        }
    }

    private func proofList(_ report: ReadinessReport) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Proof Rows")
                .font(.headline)
            ForEach(report.features) { feature in
                DisclosureGroup {
                    VStack(alignment: .leading, spacing: 8) {
                        InfoRow(label: "Evidence", value: feature.evidence)
                        if !feature.blocker.isEmpty {
                            Text(feature.blocker)
                                .font(.callout)
                                .foregroundStyle(.orange)
                                .textSelection(.enabled)
                        }
                    }
                    .padding(.top, 8)
                } label: {
                    HStack {
                        Text(feature.name)
                            .font(.callout.weight(.medium))
                        Spacer()
                        StatusPill(text: displayUserStatus(feature.status))
                    }
                }
                .padding(14)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
            }
        }
    }

    private var milestoneOrder: [MilestonePresentation] {
        [
            MilestonePresentation(id: "internal_local_ready", title: "Internal Local"),
            MilestonePresentation(id: "buddy_no_key_ready", title: "Buddy No-Key"),
            MilestonePresentation(id: "codex_handoff_ready", title: "Codex Handoff"),
            MilestonePresentation(id: "customer_ship_ready", title: "Prebuilt Mac App")
        ]
    }
}

private struct MilestonePresentation: Identifiable {
    var id: String
    var title: String
}

private struct ReadinessMilestoneCard: View {
    var title: String
    var milestone: ReadinessMilestone

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Image(systemName: milestone.ready ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                    .foregroundStyle(statusColor(milestone.status))
                Spacer()
            }
            Text(title)
                .font(.headline)
            StatusPill(text: displayUserStatus(milestone.status))
            if let blocker = milestone.blockers.first, !blocker.isEmpty {
                Text(shortText(blocker, limit: 110))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            } else {
                Text("No current blocker.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, minHeight: 132, alignment: .topLeading)
        .padding(14)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
    }
}
