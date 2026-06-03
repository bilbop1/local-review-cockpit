import SwiftUI

struct CampaignGateView: View {
    @ObservedObject var store: OpsStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                SectionHeader(
                    title: "Campaigns",
                    subtitle: "Refresh the briefs before building new reviews so every clip stays on request."
                )

                if let gate = store.campaignGate {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            StatusPill(text: gate.status)
                            Spacer()
                            Button {
                                Task { await store.runCampaignGate() }
                            } label: {
                                Label("Refresh Campaigns", systemImage: "magnifyingglass")
                            }
                        }
                        InfoRow(label: "Visible campaigns", value: "\(gate.visibleCampaignCount)")
                        InfoRow(label: "Verified source routes", value: "\(gate.selectedFeederCount)")
                        InfoRow(label: "Started", value: gate.startedAt)
                        InfoRow(label: "Finished", value: gate.finishedAt ?? "")
                        Divider()
                        Text("Current Blocker")
                            .font(.headline)
                        Text(gate.blocker)
                            .textSelection(.enabled)
                        Text("Notes")
                            .font(.headline)
                        Text(gate.notes)
                            .textSelection(.enabled)
                            .foregroundStyle(.secondary)
                    }
                    .padding(16)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
                } else {
                    EmptyStateView(title: "No Gate State", message: "The backend has not returned campaign gate state yet.", systemImage: "checklist")
                }

                VStack(alignment: .leading, spacing: 10) {
                    Text("Campaign Evidence")
                        .font(.headline)
                    if store.campaignEvidence.isEmpty {
                        Text("No campaign evidence has been stored yet.")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(store.campaignEvidence) { item in
                            VStack(alignment: .leading, spacing: 6) {
                                HStack {
                                    Text(item.title.isEmpty ? item.evidenceType : item.title)
                                        .font(.headline)
                                    Spacer()
                                    StatusPill(text: item.evidenceType)
                                }
                                InfoRow(label: "URL", value: item.sourceURL)
                                InfoRow(label: "Screenshot", value: item.screenshotPath)
                                if !item.extractedText.isEmpty {
                                    Text(item.extractedText)
                                        .font(.callout)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(5)
                                        .textSelection(.enabled)
                                }
                            }
                            .padding(12)
                            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 8))
                        }
                    }
                }
                .padding(16)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))

                VStack(alignment: .leading, spacing: 10) {
                    Text("Active Projects")
                        .font(.headline)
                    if store.campaignProjects.isEmpty {
                        Text("Source-backed campaigns have not loaded yet.")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(store.campaignProjects) { project in
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    Text(project.name)
                                        .font(.headline)
                                    Spacer()
                                    StatusPill(text: displayUserStatus(project.status))
                                }
                                InfoRow(label: "Approved", value: "\(project.approvedCount)/\(project.reviewTargetCount)")
                                InfoRow(label: "Source ready", value: "\(project.sourceReadyCount)")
                                if project.watermarkRequired {
                                    InfoRow(label: "Watermark", value: project.watermarkReady ? "Installed" : "Needed")
                                }
                                if !project.blocker.isEmpty {
                                    Text(project.blocker)
                                        .font(.callout)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .padding(12)
                            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 8))
                        }
                    }
                }
                .padding(16)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))

                VStack(alignment: .leading, spacing: 10) {
                    Text("How Reviews Stay On-Brief")
                        .font(.headline)
                    Text("Inspect the current campaign brief, confirm the creator request, verify a usable clip source, then build only reviews that match the brief.")
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
                .padding(16)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
            }
            .padding(22)
        }
    }
}
