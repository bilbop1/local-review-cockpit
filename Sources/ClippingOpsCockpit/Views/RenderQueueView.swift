import SwiftUI

struct RenderQueueView: View {
    @ObservedObject var store: OpsStore

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionHeader(title: "Render Queue", subtitle: "Hermes-owned job intents, deterministic worker results, and blocked-because messages.")
                .padding(22)
            if store.renderQueue.isEmpty {
                EmptyStateView(title: "No Jobs", message: "No worker jobs have run yet.", systemImage: "progress.indicator")
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        ForEach(store.renderQueue) { job in
                            VStack(alignment: .leading, spacing: 9) {
                                HStack(alignment: .firstTextBaseline) {
                                    VStack(alignment: .leading, spacing: 3) {
                                        Text(job.name)
                                            .font(.headline)
                                        Text(job.kind)
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    StatusPill(text: job.status)
                                }
                                InfoRow(label: "Stage", value: job.stage)
                                if !job.intent.isEmpty {
                                    InfoRow(label: "Intent", value: job.intent)
                                }
                                if !job.campaignSlug.isEmpty {
                                    InfoRow(label: "Campaign", value: job.campaignSlug)
                                }
                                InfoRow(label: "Hermes profile", value: job.hermesProfile)
                                if !job.claimedBy.isEmpty {
                                    InfoRow(label: "Claimed by", value: job.claimedBy)
                                }
                                ProgressView(value: Double(job.progress), total: 100)
                                    .frame(maxWidth: 240)
                                if !job.error.isEmpty {
                                    Text(shortText(job.error, limit: 160))
                                        .font(.callout)
                                        .foregroundStyle(.red)
                                        .textSelection(.enabled)
                                }
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
