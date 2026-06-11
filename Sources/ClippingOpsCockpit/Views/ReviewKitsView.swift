import AppKit
import AVFoundation
import SwiftUI

struct ReviewKitsView: View {
    @ObservedObject var store: OpsStore
    @State private var selectedKitID: String?
    @State private var rejectionNotes = ""
    @State private var filter = ReviewKitFilter.needsReview
    @State private var sort = ReviewKitSort.rendered
    @State private var campaignFilter = "all"
    @State private var searchText = ""
    @FocusState private var rejectionNotesFocused: Bool

    private var visibleKits: [RenderKit] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return store.reviewKits
            .filter { filter.matches($0) }
            .filter { kit in
                campaignFilter == "all" || (kit.campaignSlug ?? "") == campaignFilter
            }
            .filter { kit in
                guard !query.isEmpty else { return true }
                return [
                    kit.title,
                    kit.campaignName ?? "",
                    displayUserStatus(kit.reviewStatus),
                    kit.clipSourcePlatform ?? "",
                    kit.clipSourceURL ?? ""
                ]
                .joined(separator: " ")
                .lowercased()
                .contains(query)
            }
            .sorted { sort.isOrderedBefore($0, $1) }
    }

    private var selectedKit: RenderKit? {
        if let selectedKitID, let match = visibleKits.first(where: { $0.id == selectedKitID }) {
            return match
        }
        return visibleKits.first
    }

    var body: some View {
        HSplitView {
            kitList
                .frame(minWidth: 320, idealWidth: 390, maxWidth: 470)
            kitDetail
                .frame(minWidth: 660)
        }
        .searchable(text: $searchText, placement: .toolbar, prompt: "Search reviews")
        .onAppear {
            keepSelectionValid()
        }
        .task {
            await store.refreshReviewSurface()
            keepSelectionValid()
        }
        .onChange(of: selectedKitID) { _, _ in
            rejectionNotes = ""
        }
        .onChange(of: visibleKits.map(\.id)) { _, _ in
            keepSelectionValid()
        }
        .accessibilityIdentifier("review-kits-root")
    }

    private var kitList: some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionHeader(title: "Review Kits", subtitle: "Newest rendered reviews first. Approval prepares files only; it never publishes.")
                .padding([.horizontal, .top], 18)

            controls
                .padding(.horizontal, 18)
                .padding(.vertical, 12)

            if visibleKits.isEmpty {
                EmptyStateView(
                    title: "No Reviews Here",
                    message: "Try another filter or build the latest reviews from the Dashboard.",
                    systemImage: "play.rectangle"
                )
            } else {
                List(selection: $selectedKitID) {
                    ForEach(visibleKits) { kit in
                        ReviewKitRow(kit: kit)
                            .tag(kit.id)
                            .accessibilityIdentifier("review-kit-row-\(kit.id)")
                    }
                }
                .accessibilityIdentifier("review-kit-list")
            }
        }
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 10) {
            Picker("Filter", selection: $filter) {
                ForEach(ReviewKitFilter.allCases) { item in
                    Text(item.title).tag(item)
                }
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("review-kit-filter")

            Picker("Campaign", selection: $campaignFilter) {
                Text("All Campaigns").tag("all")
                ForEach(store.campaignProjects) { project in
                    Text(project.name).tag(project.slug)
                }
            }
            .pickerStyle(.menu)
            .accessibilityIdentifier("review-kit-campaign-filter")

            HStack {
                Label("\(visibleKits.count) shown", systemImage: "rectangle.stack")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Picker("Sort", selection: $sort) {
                    ForEach(ReviewKitSort.allCases) { item in
                        Text(item.title).tag(item)
                    }
                }
                .labelsHidden()
                .frame(width: 150)
                .accessibilityIdentifier("review-kit-sort")
            }
        }
    }

    @ViewBuilder
    private var kitDetail: some View {
        if let kit = selectedKit {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    detailHeader(kit)
                    videoPanel(kit: kit)
                    decisionPanel(kit: kit)
                    PublishPanel(store: store, kit: kit)
                    clipDetailsPanel(kit: kit)
                    technicalArtifactsPanel(kit: kit)
                }
                .padding(22)
            }
            .accessibilityIdentifier("review-kit-detail")
        } else {
            EmptyStateView(title: "No Kit Selected", message: "Select a review kit from the list.", systemImage: "play.rectangle")
        }
    }

    private func detailHeader(_ kit: RenderKit) -> some View {
        HStack(alignment: .top, spacing: 14) {
            VStack(alignment: .leading, spacing: 6) {
                Text(kit.title)
                    .font(.title2.weight(.semibold))
                    .lineLimit(2)
                HStack(spacing: 12) {
                    if let campaign = kit.campaignName, !campaign.isEmpty {
                        Label(campaign, systemImage: "rectangle.3.group")
                    }
                    Label("Rendered \(displayDateTime(kit.renderedAt ?? kit.createdAt))", systemImage: "wand.and.stars")
                    Label("Clip \(displayDateTime(kit.clipCreatedAt ?? kit.clipDiscoveredAt))", systemImage: "clock")
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 10) {
                StatusPill(text: displayUserStatus(kit.reviewStatus))
                HStack(spacing: 6) {
                    Button {
                        moveSelection(by: -1)
                    } label: {
                        Label("Previous", systemImage: "chevron.up")
                    }
                    .labelStyle(.iconOnly)
                    .keyboardShortcut("[", modifiers: [.command])
                    .disabled(!canMove(by: -1))
                    .help("Previous review")
                    .accessibilityIdentifier("review-kit-previous")

                    Button {
                        moveSelection(by: 1)
                    } label: {
                        Label("Next", systemImage: "chevron.down")
                    }
                    .labelStyle(.iconOnly)
                    .keyboardShortcut("]", modifiers: [.command])
                    .disabled(!canMove(by: 1))
                    .help("Next review")
                    .accessibilityIdentifier("review-kit-next")
                }
            }
        }
    }

    @ViewBuilder
    private func videoPanel(kit: RenderKit) -> some View {
        if let url = kit.videoURL {
            ReviewVideoPanel(kitID: kit.id, url: url, path: kit.reviewVideoPath)
                .id(kit.id)
        } else {
            VStack(spacing: 12) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 34))
                    .foregroundStyle(.red)
                Text("Preview Missing")
                    .font(.headline)
                Text("This review is blocked until the rendered video exists and previews in the app.")
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, minHeight: 260)
            .padding()
            .background(.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
        }
    }

    private func decisionPanel(kit: RenderKit) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Decision")
                    .font(.headline)
                Spacer()
                Text("Approval does not publish.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Button {
                    Task { await store.approve(kit: kit) }
                } label: {
                    Label("Approve for Prep", systemImage: "checkmark.circle")
                }
                .disabled(kit.videoURL == nil)
                .keyboardShortcut(.return, modifiers: [.command])
                .accessibilityIdentifier("review-kit-approve")

                TextField("Revision note required", text: $rejectionNotes, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(1...3)
                    .focused($rejectionNotesFocused)
                    .accessibilityIdentifier("review-kit-rejection-notes")

                Button {
                    rejectionNotesFocused = true
                } label: {
                    Label("Note", systemImage: "text.bubble")
                }
                .keyboardShortcut("r", modifiers: [.command])
                .accessibilityIdentifier("review-kit-focus-reject-note")

                Button {
                    Task {
                        await store.reject(kit: kit, notes: rejectionNotes)
                        rejectionNotes = ""
                    }
                } label: {
                    Label("Send Back", systemImage: "arrow.uturn.backward.circle")
                }
                .disabled(rejectionNotes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .accessibilityIdentifier("review-kit-reject")
            }
        }
        .padding(16)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
        .accessibilityIdentifier("review-kit-decision-panel")
    }

    private func clipDetailsPanel(kit: RenderKit) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Clip Details")
                .font(.headline)

            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 8) {
                InfoRow(label: "Broadcast", value: displayDateTime(kit.clipCreatedAt ?? kit.clipDiscoveredAt))
                InfoRow(label: "Kit created", value: displayDateTime(kit.createdAt))
                InfoRow(label: "Rendered", value: displayDateTime(kit.renderedAt ?? kit.createdAt))
                InfoRow(label: "Campaign", value: kit.campaignName ?? "Not linked")
                InfoRow(label: "Views", value: formatCount(kit.clipViewCount))
                InfoRow(label: "Duration", value: formatDuration(kit.clipDuration))
                InfoRow(label: "Platform", value: displayStatus(kit.clipSourcePlatform ?? "Unknown"))
            }

            HStack(alignment: .firstTextBaseline) {
                Text("Source")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(width: 150, alignment: .leading)
                if let source = kit.clipSourceURL, let url = URL(string: source) {
                    Link(shortText(source, limit: 90), destination: url)
                        .font(.callout)
                } else {
                    Text("Not set")
                        .font(.callout)
                }
                Spacer(minLength: 0)
            }

            if !kit.approvedAt.isEmpty {
                InfoRow(label: "Approved", value: displayDateTime(kit.approvedAt))
            }
            if let campaignURL = kit.campaignURL, let url = URL(string: campaignURL) {
                HStack(alignment: .firstTextBaseline) {
                    Text("Campaign")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .frame(width: 150, alignment: .leading)
                    Link("Open campaign brief", destination: url)
                        .font(.callout)
                    Spacer(minLength: 0)
                }
            }
        }
        .padding(16)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
        .accessibilityIdentifier("review-kit-clip-details")
    }

    private func technicalArtifactsPanel(kit: RenderKit) -> some View {
        DisclosureGroup {
            VStack(alignment: .leading, spacing: 12) {
                InfoRow(label: "Kit ID", value: kit.id)
                InfoRow(label: "Nomination", value: kit.nominationID)
                InfoRow(label: "Video file", value: kit.reviewVideoPath)
                if !kit.rejectionNotes.isEmpty {
                    InfoRow(label: "Revision note", value: kit.rejectionNotes)
                }
                ArtifactText(title: "Caption", path: kit.captionPath)
                ArtifactText(title: "Transcript", path: kit.transcriptPath)
                ArtifactText(title: "Checklist", path: kit.checklistPath)
                ArtifactText(title: "Risk", path: kit.riskPath)
                ArtifactText(title: "Source", path: kit.sourcePath)
            }
            .padding(.top, 10)
        } label: {
            Label("Technical Artifacts", systemImage: "shippingbox")
                .font(.headline)
        }
        .padding(16)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
        .accessibilityIdentifier("review-kit-technical-artifacts")
    }

    private func keepSelectionValid() {
        guard !visibleKits.isEmpty else {
            selectedKitID = nil
            return
        }
        if let selectedKitID, visibleKits.contains(where: { $0.id == selectedKitID }) {
            return
        }
        selectedKitID = visibleKits.first?.id
    }

    private func canMove(by delta: Int) -> Bool {
        guard let selectedKitID, let index = visibleKits.firstIndex(where: { $0.id == selectedKitID }) else {
            return false
        }
        let target = index + delta
        return target >= 0 && target < visibleKits.count
    }

    private func moveSelection(by delta: Int) {
        guard !visibleKits.isEmpty else { return }
        guard let selectedKitID, let index = visibleKits.firstIndex(where: { $0.id == selectedKitID }) else {
            self.selectedKitID = visibleKits.first?.id
            return
        }
        let target = min(max(index + delta, 0), visibleKits.count - 1)
        self.selectedKitID = visibleKits[target].id
    }
}

private enum ReviewKitFilter: String, CaseIterable, Identifiable, Hashable {
    case needsReview
    case approved
    case rejected
    case all

    var id: String { rawValue }

    var title: String {
        switch self {
        case .needsReview: "Needs Review"
        case .approved: "Approved"
        case .rejected: "Rejected"
        case .all: "All"
        }
    }

    func matches(_ kit: RenderKit) -> Bool {
        let status = kit.reviewStatus.lowercased()
        switch self {
        case .needsReview:
            return status.contains("review") || status.contains("pending")
        case .approved:
            return status.contains("approved")
        case .rejected:
            return status.contains("reject")
        case .all:
            return true
        }
    }
}

private enum ReviewKitSort: String, CaseIterable, Identifiable, Hashable {
    case rendered
    case created
    case clipTime
    case views

    var id: String { rawValue }

    var title: String {
        switch self {
        case .rendered: "Rendered"
        case .created: "Created"
        case .clipTime: "Clip Time"
        case .views: "Views"
        }
    }

    func isOrderedBefore(_ lhs: RenderKit, _ rhs: RenderKit) -> Bool {
        switch self {
        case .rendered:
            return newer(lhs.renderedAt ?? lhs.createdAt, rhs.renderedAt ?? rhs.createdAt, fallbackLHS: lhs.createdAt, fallbackRHS: rhs.createdAt)
        case .created:
            return newer(lhs.createdAt, rhs.createdAt)
        case .clipTime:
            return newer(lhs.clipCreatedAt ?? lhs.clipDiscoveredAt, rhs.clipCreatedAt ?? rhs.clipDiscoveredAt, fallbackLHS: lhs.createdAt, fallbackRHS: rhs.createdAt)
        case .views:
            let left = lhs.clipViewCount ?? 0
            let right = rhs.clipViewCount ?? 0
            if left != right { return left > right }
            return newer(lhs.renderedAt ?? lhs.createdAt, rhs.renderedAt ?? rhs.createdAt, fallbackLHS: lhs.createdAt, fallbackRHS: rhs.createdAt)
        }
    }

    private func newer(_ lhs: String?, _ rhs: String?, fallbackLHS: String? = nil, fallbackRHS: String? = nil) -> Bool {
        let left = parseDate(lhs) ?? parseDate(fallbackLHS) ?? .distantPast
        let right = parseDate(rhs) ?? parseDate(fallbackRHS) ?? .distantPast
        if left != right { return left > right }
        return (lhs ?? "") > (rhs ?? "")
    }
}

private struct ReviewKitRow: View {
    var kit: RenderKit

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(kit.title)
                    .font(.headline)
                    .lineLimit(2)
                Spacer()
                StatusPill(text: displayUserStatus(kit.reviewStatus))
            }

            VStack(alignment: .leading, spacing: 4) {
                Label("Broadcast \(compactDateTime(kit.clipCreatedAt ?? kit.clipDiscoveredAt))", systemImage: "clock")
                Label("Created \(compactDateTime(kit.createdAt))", systemImage: "plus.circle")
                Label("Rendered \(compactDateTime(kit.renderedAt ?? kit.createdAt))", systemImage: "wand.and.stars")
            }
            .font(.caption2)
            .foregroundStyle(.secondary)

            HStack(spacing: 10) {
                if let campaign = kit.campaignName, !campaign.isEmpty {
                    Label(campaign, systemImage: "rectangle.3.group")
                }
                if let platform = kit.clipSourcePlatform, !platform.isEmpty {
                    Label(displayStatus(platform), systemImage: platform.lowercased() == "twitch" ? "play.tv" : "bolt.circle")
                }
                Label(formatDuration(kit.clipDuration), systemImage: "timer")
                Label(formatCount(kit.clipViewCount), systemImage: "eye")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding(.vertical, 6)
    }
}

private struct PublishPanel: View {
    @ObservedObject var store: OpsStore
    var kit: RenderKit

    @State private var selectedPlatforms: Set<String> = ["tiktok", "instagram", "youtube"]
    @State private var package: PublishPackage?
    @State private var latestJob: PublishJob?
    @State private var publishTitle = ""
    @State private var publishCaption = ""
    @State private var scheduleEnabled = false
    @State private var scheduledDate = Date().addingTimeInterval(60 * 60)
    @State private var showingPostConfirmation = false
    @State private var showingScheduleConfirmation = false

    private var approvedForPrep: Bool {
        kit.reviewStatus == "approved_manual_prep"
    }

    private var provider: PublishProviderState? {
        store.publishStatus?.provider
    }

    private var liveReady: Bool {
        provider?.liveReady ?? false
    }

    private var sortedPlatforms: [String] {
        (store.publishStatus?.supportedPlatforms.isEmpty == false ? store.publishStatus?.supportedPlatforms : ["tiktok", "instagram", "youtube"]) ?? ["tiktok", "instagram", "youtube"]
    }

    private var platformList: [String] {
        sortedPlatforms.filter { selectedPlatforms.contains($0) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline) {
                Text("Publish")
                    .font(.headline)
                Spacer()
                StatusPill(text: liveReady ? "live ready" : "dry-run locked")
            }

            if !approvedForPrep {
                Label("Approve this review before preparing posts.", systemImage: "lock.fill")
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier("publish-locked-message")
            } else {
                publishControls
                if let latestJob {
                    publishJobStatus(latestJob)
                } else if let provider, !provider.blockers.isEmpty {
                    Text(provider.blockers.joined(separator: " "))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
            }
        }
        .padding(16)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
        .task {
            await store.refreshPublishStatus()
        }
        .onChange(of: kit.id) { _, _ in
            package = nil
            latestJob = nil
            publishTitle = ""
            publishCaption = ""
            selectedPlatforms = Set(store.publishStatus?.defaultPlatforms ?? ["tiktok", "instagram", "youtube"])
        }
        .confirmationDialog("Post this approved kit now?", isPresented: $showingPostConfirmation) {
            Button("Confirm Live Post", role: .destructive) {
                Task { await queueAndConfirmLive(scheduledAt: "") }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will queue a live Upload-Post job through Hermes. It does not touch payouts or account settings.")
        }
        .confirmationDialog("Schedule this approved kit?", isPresented: $showingScheduleConfirmation) {
            Button("Confirm Schedule", role: .destructive) {
                Task { await queueAndConfirmLive(scheduledAt: isoString(scheduledDate)) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This queues a confirmed live job with the selected schedule time.")
        }
        .accessibilityIdentifier("review-kit-publish-panel")
    }

    private var publishControls: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                ForEach(sortedPlatforms, id: \.self) { platform in
                    Toggle(platform.uppercased(), isOn: Binding(
                        get: { selectedPlatforms.contains(platform) },
                        set: { enabled in
                            if enabled {
                                selectedPlatforms.insert(platform)
                            } else {
                                selectedPlatforms.remove(platform)
                            }
                        }
                    ))
                    .toggleStyle(.button)
                    .controlSize(.small)
                    .accessibilityIdentifier("publish-platform-\(platform)")
                }
                Spacer()
            }

            TextField("Post title", text: $publishTitle)
                .textFieldStyle(.roundedBorder)
                .accessibilityIdentifier("publish-title")

            TextField("Caption", text: $publishCaption, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(2...5)
                .accessibilityIdentifier("publish-caption")

            HStack(spacing: 10) {
                Toggle("Schedule", isOn: $scheduleEnabled)
                    .accessibilityIdentifier("publish-schedule-toggle")
                DatePicker("", selection: $scheduledDate, displayedComponents: [.date, .hourAndMinute])
                    .labelsHidden()
                    .disabled(!scheduleEnabled)
                    .accessibilityIdentifier("publish-schedule-date")
                Spacer()
            }

            HStack(spacing: 10) {
                Button {
                    Task { await preparePackage() }
                } label: {
                    Label("Prepare Post", systemImage: "shippingbox")
                }
                .disabled(platformList.isEmpty)
                .accessibilityIdentifier("publish-prepare")

                Button {
                    Task { await dryRun() }
                } label: {
                    Label("Dry Run", systemImage: "checkmark.shield")
                }
                .disabled(platformList.isEmpty)
                .accessibilityIdentifier("publish-dry-run")

                Button {
                    showingScheduleConfirmation = true
                } label: {
                    Label("Schedule", systemImage: "calendar.badge.clock")
                }
                .disabled(!liveReady || platformList.isEmpty || !scheduleEnabled)
                .accessibilityIdentifier("publish-schedule")

                Button(role: .destructive) {
                    showingPostConfirmation = true
                } label: {
                    Label("Post Now", systemImage: "paperplane.fill")
                }
                .disabled(!liveReady || platformList.isEmpty)
                .accessibilityIdentifier("publish-post-now")
            }

            if let provider {
                HStack(spacing: 10) {
                    Label(provider.apiKey == "configured" ? "Key configured" : "Key missing", systemImage: provider.apiKey == "configured" ? "key.fill" : "key.slash")
                    Label(provider.warmupComplete ? "Warm-up done" : "Warm-up pending", systemImage: provider.warmupComplete ? "flame.fill" : "hourglass")
                    Label(provider.mode == "live" ? "Live mode" : "Dry-run mode", systemImage: provider.mode == "live" ? "bolt.fill" : "testtube.2")
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
        }
    }

    private func publishJobStatus(_ job: PublishJob) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                StatusPill(text: job.status)
                Text(job.mode == "live" ? "Upload-Post live" : "Upload-Post dry run")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if !job.error.isEmpty {
                Text(job.error)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
            }
            if !job.postUrls.isEmpty {
                ForEach(job.postUrls.keys.sorted(), id: \.self) { key in
                    if let value = job.postUrls[key], let url = URL(string: value) {
                        Link("\(key): \(value)", destination: url)
                            .font(.caption)
                    }
                }
            }
        }
        .accessibilityIdentifier("publish-latest-job")
    }

    @MainActor
    private func preparePackage() async {
        guard !platformList.isEmpty else { return }
        if let prepared = await store.preparePublishPackage(
            kit: kit,
            platforms: platformList,
            title: publishTitle,
            caption: publishCaption
        ) {
            package = prepared
            publishTitle = prepared.title
            publishCaption = prepared.caption
        }
    }

    @MainActor
    private func preparedPackage() async -> PublishPackage? {
        if let package { return package }
        await preparePackage()
        return package
    }

    @MainActor
    private func dryRun() async {
        guard let package = await preparedPackage() else { return }
        latestJob = await store.queuePublishJob(
            package: package,
            mode: "dry_run",
            platforms: platformList,
            title: publishTitle,
            caption: publishCaption
        )
    }

    @MainActor
    private func queueAndConfirmLive(scheduledAt: String) async {
        guard let package = await preparedPackage() else { return }
        guard let job = await store.queuePublishJob(
            package: package,
            mode: "live",
            platforms: platformList,
            title: publishTitle,
            caption: publishCaption,
            scheduledAt: scheduledAt
        ) else {
            return
        }
        latestJob = await store.confirmLivePublish(job: job) ?? job
    }

    private func isoString(_ date: Date) -> String {
        ISO8601DateFormatter().string(from: date)
    }
}

private struct ReviewVideoPanel: View {
    var kitID: String
    var url: URL
    var path: String

    @State private var playerReady = false
    @State private var platformOverlay: PlatformUIOverlay = .none
    @State private var thumbnail: NSImage?
    @State private var thumbnailFailed = false
    @StateObject private var playback = ReviewVideoPlaybackController()

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            overlayControls

            PortraitReviewPreviewStage {
                ZStack {
                    CrashSafeVideoPreview(url: url, isReady: $playerReady, playback: playback)

                    if !playerReady {
                        thumbnailBackground
                        VStack(spacing: 12) {
                            ProgressView()
                                .controlSize(.large)
                            Text(thumbnailFailed ? "Starting Preview" : "Preparing Preview")
                                .font(.headline)
                        }
                        .foregroundStyle(.white)
                        .padding(28)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(.black.opacity(0.22))
                    }

                    SocialPlatformChromeOverlay(platform: platformOverlay)
                        .accessibilityIdentifier("review-kit-platform-overlay-\(platformOverlay.rawValue)")

                    if playerReady && platformOverlay == .none {
                        StatusPill(
                            text: playback.isPlaying ? "autoplaying" : "paused",
                            systemImage: playback.isPlaying ? "play.circle" : "pause.circle"
                        )
                            .padding(12)
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    }
                }
                .id(kitID)
            }

            ReviewPlaybackControls(playback: playback)
                .accessibilityIdentifier("review-kit-playback-controls")
        }
        .onChange(of: kitID) { _, _ in
            playerReady = false
            thumbnail = nil
            thumbnailFailed = false
        }
        .onDisappear {
            playerReady = false
            playback.detach()
        }
        .task(id: kitID) {
            await loadThumbnail()
        }
        .accessibilityIdentifier("review-kit-video-autoplay")
    }

    private var overlayControls: some View {
        HStack(spacing: 10) {
            Label("Platform UI", systemImage: "rectangle.on.rectangle")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)

            Picker("Platform UI", selection: $platformOverlay) {
                ForEach(PlatformUIOverlay.allCases) { overlay in
                    Text(overlay.shortTitle).tag(overlay)
                }
            }
            .labelsHidden()
            .pickerStyle(.segmented)
            .frame(width: 210)
            .accessibilityIdentifier("review-kit-platform-overlay-picker")

            Text(platformOverlay.title)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)

            Spacer()

            if platformOverlay != .none {
                Label("Preview only", systemImage: "eye")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 2)
    }

    @ViewBuilder
    private var thumbnailBackground: some View {
        if let thumbnail {
            Image(nsImage: thumbnail)
                .resizable()
                .scaledToFit()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(.black)
                .overlay(.black.opacity(0.34))
        } else {
            Color.black
        }
    }

    @MainActor
    private func loadThumbnail() async {
        guard thumbnail == nil, !thumbnailFailed else { return }
        let asset = AVURLAsset(url: url)
        let generator = AVAssetImageGenerator(asset: asset)
        generator.appliesPreferredTrackTransform = true
        generator.maximumSize = CGSize(width: 720, height: 1280)
        do {
            let image = try generator.copyCGImage(at: CMTime(seconds: 1.0, preferredTimescale: 600), actualTime: nil)
            thumbnail = NSImage(cgImage: image, size: NSSize(width: image.width, height: image.height))
        } catch {
            thumbnailFailed = true
        }
    }
}

private struct ReviewPlaybackControls: View {
    @ObservedObject var playback: ReviewVideoPlaybackController
    @State private var scrubValue = 0.0
    @State private var isScrubbing = false

    var body: some View {
        HStack(spacing: 10) {
            Button {
                playback.restart()
            } label: {
                Label("Start", systemImage: "backward.end.fill")
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .help("Restart preview")
            .accessibilityLabel("Restart preview")
            .accessibilityIdentifier("review-kit-playback-restart")

            Button {
                playback.skip(-5)
            } label: {
                Label("5s", systemImage: "gobackward.5")
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .help("Back 5 seconds")
            .accessibilityLabel("Back 5 seconds")
            .accessibilityIdentifier("review-kit-playback-back")

            Button {
                playback.togglePlayback()
            } label: {
                Label(playback.isPlaying ? "Pause" : "Play", systemImage: playback.isPlaying ? "pause.fill" : "play.fill")
                    .frame(minWidth: 74)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.small)
            .help(playback.isPlaying ? "Pause preview" : "Play preview")
            .accessibilityLabel(playback.isPlaying ? "Pause preview" : "Play preview")
            .accessibilityIdentifier("review-kit-playback-toggle")

            Button {
                playback.skip(5)
            } label: {
                Label("5s", systemImage: "goforward.5")
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .help("Forward 5 seconds")
            .accessibilityLabel("Forward 5 seconds")
            .accessibilityIdentifier("review-kit-playback-forward")

            Text(currentTimecode)
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
                .frame(width: 44, alignment: .trailing)
                .accessibilityLabel("Preview current time")
                .accessibilityValue(currentTimecode)
                .accessibilityIdentifier("review-kit-playback-current-time")

            Slider(
                value: Binding(
                    get: { isScrubbing ? scrubValue : playback.currentTime },
                    set: { scrubValue = $0 }
                ),
                in: playback.progressRange,
                onEditingChanged: { editing in
                    if editing {
                        isScrubbing = true
                        scrubValue = playback.currentTime
                    } else {
                        playback.seek(to: scrubValue)
                        isScrubbing = false
                    }
                }
            )
            .disabled(playback.duration <= 0)
            .accessibilityLabel("Preview scrubber")
            .accessibilityIdentifier("review-kit-playback-scrubber")

            Text(durationTimecode)
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
                .frame(width: 44, alignment: .leading)
                .accessibilityLabel("Preview duration")
                .accessibilityValue(durationTimecode)
                .accessibilityIdentifier("review-kit-playback-duration")

            Button {
                playback.toggleMuted()
            } label: {
                Image(systemName: playback.isMuted ? "speaker.slash.fill" : "speaker.wave.2.fill")
                    .frame(width: 22)
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .help(playback.isMuted ? "Unmute preview" : "Mute preview")
            .accessibilityLabel(playback.isMuted ? "Unmute preview" : "Mute preview")
            .accessibilityIdentifier("review-kit-playback-mute")
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 8))
        .onAppear {
            scrubValue = playback.currentTime
        }
        .onChange(of: playback.currentTime) { _, value in
            if !isScrubbing {
                scrubValue = value
            }
        }
    }

    private var currentTimecode: String {
        timecode(isScrubbing ? scrubValue : playback.currentTime)
    }

    private var durationTimecode: String {
        timecode(playback.duration)
    }

    private func timecode(_ seconds: Double) -> String {
        guard seconds.isFinite && seconds > 0 else { return "0:00" }
        let rounded = Int(seconds.rounded())
        return "\(rounded / 60):\(String(format: "%02d", rounded % 60))"
    }
}

private struct ArtifactText: View {
    var title: String
    var path: String

    var body: some View {
        DisclosureGroup(title) {
            VStack(alignment: .leading, spacing: 8) {
                Text(path)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                Text(readSmallTextFile(path))
                    .font(.system(.callout, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                    .background(.background.opacity(0.55), in: RoundedRectangle(cornerRadius: 8))
            }
            .padding(.top, 8)
        }
    }
}

private func formatDuration(_ duration: Double?) -> String {
    guard let duration else { return "Unknown" }
    if duration >= 60 {
        return String(format: "%.0fm %.0fs", floor(duration / 60), duration.truncatingRemainder(dividingBy: 60))
    }
    return String(format: "%.1fs", duration)
}

private func formatCount(_ count: Int?) -> String {
    guard let count else { return "Unknown" }
    if count >= 1_000_000 {
        return String(format: "%.1fM", Double(count) / 1_000_000)
    }
    if count >= 1_000 {
        return String(format: "%.1fK", Double(count) / 1_000)
    }
    return "\(count)"
}
