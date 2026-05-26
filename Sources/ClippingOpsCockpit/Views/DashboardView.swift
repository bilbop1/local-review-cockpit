import SwiftUI

struct DashboardView: View {
    @ObservedObject var store: OpsStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                hero
                metrics
                reviewActions
                gateBand
                latestJobs
            }
            .padding(22)
        }
        .background(.background)
    }

    private var hero: some View {
        LiquidPanel(tint: statusColor(store.readiness?.overall ?? "blocked")) {
            HStack(alignment: .center, spacing: 18) {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Review Cockpit")
                        .font(.system(size: 34, weight: .semibold, design: .rounded))
                    Text(store.readiness?.milestoneLine ?? "Review the newest captioned clips and keep the production gates honest.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 8) {
                    StatusPill(text: store.health?.campaignStatus ?? "blocked", systemImage: "checklist.checked")
                    StatusPill(text: store.readiness?.overall ?? "red", systemImage: "checkmark.seal")
                }
            }
        }
        .accessibilityIdentifier("dashboard-hero")
    }

    private var metrics: some View {
        let counts = store.summary?.counts
        return LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 12), count: 3), spacing: 12) {
            MetricTile(title: "Reviews Waiting", value: "\(counts?.approvalsNeeded ?? 0)", systemImage: "hand.tap", tint: .orange)
            DashboardInfoTile(title: "Latest Rendered", value: latestRenderedText, detail: "Newest review kit", systemImage: "wand.and.stars", tint: .green)
            DashboardInfoTile(title: "Campaign Status", value: displayUserStatus(store.campaignGate?.status ?? "blocked"), detail: store.campaignGate?.blocker ?? "Waiting for campaign state.", systemImage: "checklist.checked", tint: statusColor(store.campaignGate?.status ?? "blocked"))
            DashboardInfoTile(title: "Subtitle Proof", value: subtitleProofStatus, detail: "Burned-in captions required", systemImage: "captions.bubble", tint: statusColor(subtitleProofStatus))
            DashboardInfoTile(title: "Customer Ship Blocker", value: customerShipBlocker, detail: "Distribution gate", systemImage: "shippingbox", tint: statusColor(customerShipBlocker))
            MetricTile(title: "All Reviews", value: "\(counts?.reviewKits ?? 0)", systemImage: "play.rectangle", tint: .blue)
        }
    }

    private var reviewActions: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Next Best Actions", systemImage: "bolt.circle")
                    .font(.headline)
                Spacer()
                StatusPill(text: "manual approval only", systemImage: "hand.raised.fill")
            }
            HStack {
                Button {
                    Task { await store.renderSelectedFeederKits() }
                } label: {
                    Label("Build Latest Reviews", systemImage: "bolt.badge.play")
                }
                .accessibilityIdentifier("dashboard-render-feeders")

                Button {
                    Task { await store.runCampaignGate() }
                } label: {
                    Label("Refresh Campaigns", systemImage: "magnifyingglass")
                }
                .accessibilityIdentifier("dashboard-gate-refresh-campaigns")

                Spacer()
            }
            Text("Builds review-ready clips for manual approval. It does not post, submit payouts, or change accounts.")
                .font(.callout)
                .foregroundStyle(.secondary)
        }
        .modifier(PanelModifier(tint: .orange))
        .accessibilityIdentifier("dashboard-next-actions")
    }

    private var gateBand: some View {
        LiquidPanel(tint: .green) {
            VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Campaigns", systemImage: "checklist.checked")
                    .font(.headline)
                Spacer()
                StatusPill(text: store.campaignGate?.status ?? "blocked")
            }
            Text(store.campaignGate?.blocker ?? "Waiting for backend state.")
                .font(.callout)
                .foregroundStyle(.secondary)
            HStack {
                Button {
                    Task { await store.runCampaignGate() }
                } label: {
                    Label("Refresh Campaigns", systemImage: "magnifyingglass")
                }
                .accessibilityIdentifier("dashboard-run-gate")
                Button {
                    Task { await store.renderSelectedFeederKits() }
                } label: {
                    Label("Build Latest Reviews", systemImage: "bolt.badge.play")
                }
                .accessibilityIdentifier("dashboard-gate-build-latest-reviews")
                Spacer()
            }
        }
        }
        .accessibilityIdentifier("dashboard-gate-panel")
    }

    private var latestJobs: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Latest Jobs")
                .font(.headline)
            if store.renderQueue.isEmpty {
                Text("No jobs yet.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(store.renderQueue.prefix(5)) { job in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(job.name)
                                .font(.callout.weight(.medium))
                            Text(job.stage)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        StatusPill(text: job.status)
                    }
                    Divider()
                }
            }
        }
        .modifier(PanelModifier(tint: .secondary))
        .accessibilityIdentifier("dashboard-latest-jobs")
    }
}

private struct PanelModifier: ViewModifier {
    var tint: Color

    func body(content: Content) -> some View {
        content
            .padding(16)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(tint.opacity(0.16), lineWidth: 1)
            }
    }
}

private extension ReadinessReport {
    var milestoneLine: String {
        let internalStatus = features.first { $0.name == "Production feeder render proof" }?.status ?? "unknown"
        let guiStatus = features.first { $0.name == "GUI crash/control QA" }?.status ?? "unknown"
        return "reviews \(displayUserStatus(internalStatus)) / app QA \(displayUserStatus(guiStatus))"
    }
}

private extension DashboardView {
    var latestRenderedText: String {
        guard let kit = store.reviewKits.sorted(by: {
            (parseDate($0.renderedAt ?? $0.createdAt) ?? .distantPast) > (parseDate($1.renderedAt ?? $1.createdAt) ?? .distantPast)
        }).first else {
            return "None"
        }
        return compactDateTime(kit.renderedAt ?? kit.createdAt)
    }

    var subtitleProofStatus: String {
        store.readiness?.features.first { $0.name == "Burned-in subtitle proof" }?.status ?? "unknown"
    }

    var customerShipBlocker: String {
        if let milestone = store.readiness?.milestones["customer_ship_ready"], milestone.ready {
            return "Ready"
        }
        return "Signing"
    }
}

private struct DashboardInfoTile: View {
    var title: String
    var value: String
    var detail: String
    var systemImage: String
    var tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack {
                Image(systemName: systemImage)
                    .foregroundStyle(tint)
                Spacer()
            }
            Text(value.isEmpty ? "Unknown" : value)
                .font(.headline)
                .lineLimit(2)
                .minimumScaleFactor(0.78)
            Text(title)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
            Text(shortText(detail, limit: 88))
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .frame(maxWidth: .infinity, minHeight: 118, alignment: .leading)
        .padding(14)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
    }
}
