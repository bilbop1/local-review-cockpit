import SwiftUI

struct DashboardView: View {
    @ObservedObject var store: OpsStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                hero
                metrics
                campaignProjects
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
            DashboardInfoTile(title: "Handoff Blocker", value: handoffBlocker, detail: "Source zip lane", systemImage: "shippingbox", tint: statusColor(handoffBlocker))
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

    private var campaignProjects: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Campaign Projects", systemImage: "rectangle.3.group")
                    .font(.headline)
                Spacer()
                StatusPill(text: "\(store.campaignProjects.reduce(0) { $0 + $1.approvedCount })/\(max(store.campaignProjects.reduce(0) { $0 + $1.reviewTargetCount }, 5)) approved", systemImage: "checkmark.circle")
            }
            if store.campaignProjects.isEmpty {
                EmptyStateView(title: "No Campaign Projects", message: "Refresh to load source-backed campaigns.", systemImage: "rectangle.3.group")
            } else {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 12), count: 3), spacing: 12) {
                    ForEach(store.campaignProjects) { project in
                        CampaignProjectCard(project: project, store: store)
                    }
                }
            }
        }
        .modifier(PanelModifier(tint: .blue))
        .accessibilityIdentifier("dashboard-campaign-projects")
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
        let internalStatus = features.first { $0.name == "Campaign review batch" }?.status
            ?? features.first { $0.name == "Three-campaign review batch" }?.status
            ?? features.first { $0.name == "Campaign review render proof" }?.status
            ?? "unknown"
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

    var handoffBlocker: String {
        if let milestone = store.readiness?.milestones["codex_handoff_ready"], milestone.ready {
            return "Ready"
        }
        if let blocker = store.readiness?.milestones["codex_handoff_ready"]?.blockers.first {
            return shortText(blocker, limit: 28)
        }
        if let milestone = store.readiness?.milestones["customer_ship_ready"], milestone.ready {
            return "Prebuilt ready"
        }
        return "Zip proof"
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

private struct CampaignProjectCard: View {
    var project: CampaignProject
    @ObservedObject var store: OpsStore

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(project.name)
                        .font(.headline)
                    Text("\(project.approvedCount)/\(project.reviewTargetCount) approved")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                StatusPill(text: displayUserStatus(project.status))
            }

            ProgressView(value: Double(project.approvedCount), total: Double(max(project.reviewTargetCount, 1)))
                .accessibilityIdentifier("campaign-project-progress-\(project.slug)")

            VStack(alignment: .leading, spacing: 4) {
                Label("\(project.sourceReadyCount) source-ready", systemImage: project.sourceReady ? "checkmark.circle" : "exclamationmark.circle")
                if project.watermarkRequired {
                    Label(project.watermarkReady ? "watermark installed" : "watermark needed", systemImage: project.watermarkReady ? "seal" : "seal.exclamationmark")
                }
                Label("\(project.renderedCount) rendered", systemImage: "wand.and.stars")
                Label(project.nextAction, systemImage: "arrow.forward.circle")
            }
            .font(.caption)
            .foregroundStyle(.secondary)

            if !project.blocker.isEmpty {
                Text(shortText(project.blocker, limit: 92))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }

            HStack(spacing: 8) {
                Button {
                    Task { await store.refreshCampaignProject(project) }
                } label: {
                    Label("Refresh Brief", systemImage: "arrow.clockwise")
                }
                .labelStyle(.iconOnly)
                .help("Refresh \(project.name) brief")
                .accessibilityIdentifier("campaign-\(project.slug)-refresh-brief")

                Button {
                    Task { await store.discoverCampaignSources(project) }
                } label: {
                    Label("Find Sources", systemImage: "magnifyingglass")
                }
                .labelStyle(.iconOnly)
                .help("Find \(project.name) sources")
                .accessibilityIdentifier("campaign-\(project.slug)-discover-sources")

                Button {
                    Task { await store.buildCampaignReviews(project) }
                } label: {
                    Label("Build Reviews", systemImage: "bolt.badge.play")
                }
                .labelStyle(.iconOnly)
                .help("Build \(project.name) reviews")
                .disabled(!project.sourceReady || (project.watermarkRequired && !project.watermarkReady))
                .accessibilityIdentifier("campaign-\(project.slug)-build-reviews")

                Spacer()
                if project.watermarkRequired && !project.watermarkReady, let url = URL(string: project.watermarkURL) {
                    Link(destination: url) {
                        Image(systemName: "seal.exclamationmark")
                    }
                    .help("Open watermark asset")
                    .accessibilityIdentifier("campaign-\(project.slug)-watermark")
                }
                if let url = URL(string: project.campaignURL) {
                    Link(destination: url) {
                        Image(systemName: "safari")
                    }
                    .help("Open campaign")
                    .accessibilityIdentifier("campaign-\(project.slug)-open")
                }
            }
            .buttonStyle(.borderless)
        }
        .frame(maxWidth: .infinity, minHeight: 210, alignment: .topLeading)
        .padding(14)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(statusColor(project.status).opacity(0.18), lineWidth: 1)
        }
        .accessibilityIdentifier("campaign-project-card-\(project.slug)")
    }
}
