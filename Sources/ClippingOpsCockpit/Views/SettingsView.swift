import SwiftUI

struct SettingsView: View {
    @ObservedObject var store: OpsStore
    @State private var publishWarmupComplete = false
    @State private var publishMode = "dry_run"
    @State private var uploadPostUser = "local-operator"

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                SectionHeader(title: "Settings", subtitle: "System health, diagnostics, notifications, and buddy install tools.")

                if let health = store.health {
                    workspacePanel
                    healthPanel(health)
                    publishPanel
                    discordPanel(health.discord)
                    installerPanel(health)
                } else {
                    EmptyStateView(title: "No Health State", message: "Refresh to read backend health.", systemImage: "gearshape")
                        .frame(height: 320)
                }
            }
            .padding(22)
        }
        .task {
            if store.health == nil {
                await store.refreshAll()
            }
            syncPublishSettings()
        }
        .onChange(of: store.publishStatus?.provider.mode) { _, _ in
            syncPublishSettings()
        }
    }

    private var workspacePanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                    Text("Workspace")
                    .font(.headline)
                Spacer()
                Button {
                    Task { await store.exportDiagnostics() }
                } label: {
                    Label("Export Diagnostics", systemImage: "square.and.arrow.up")
                }
                .help("Create a no-secret diagnostics zip")
                .accessibilityIdentifier("settings-export-diagnostics")
            }
            if let profile = store.workspaceProfile {
                InfoRow(label: "Name", value: profile.name)
                InfoRow(label: "Customer", value: profile.customerID)
                InfoRow(label: "License mode", value: profile.licenseMode)
                InfoRow(label: "Billing", value: profile.billingEnabled ? "Enabled" : "Disabled")
                Text(profile.notes)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            } else {
                Text("No workspace profile loaded.")
                    .foregroundStyle(.secondary)
            }
        }
        .padding(16)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
        .accessibilityIdentifier("settings-workspace-panel")
    }

    private func healthPanel(_ health: HealthResponse) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("System Health")
                    .font(.headline)
                Spacer()
                StatusPill(text: health.status)
            }
            InfoRow(label: "Local media pipeline", value: health.localDemoStatus ?? health.status)
            InfoRow(label: "Campaign", value: health.campaignStatus ?? "blocked")
            InfoRow(label: "Review system", value: (health.productionGreen ?? false) ? "Ready" : "Waiting on review/source gates")
            DisclosureGroup("Advanced Paths and Checks") {
                VStack(alignment: .leading, spacing: 10) {
                    InfoRow(label: "App support", value: health.appSupport)
                    InfoRow(label: "Render root", value: health.renderRoot)
                    Divider()
                    ForEach(health.checks.keys.sorted(), id: \.self) { key in
                        if let check = health.checks[key] {
                            HStack(alignment: .top) {
                                Label(key.replacingOccurrences(of: "_", with: " "), systemImage: check.ok ? "checkmark.circle.fill" : "xmark.octagon.fill")
                                    .foregroundStyle(check.ok ? .green : .red)
                                    .frame(width: 190, alignment: .leading)
                                Text(check.detail)
                                    .foregroundStyle(.secondary)
                                    .textSelection(.enabled)
                                Spacer()
                            }
                            .font(.callout)
                        }
                    }
                }
                .padding(.top, 8)
            }
        }
        .padding(16)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
    }

    private func discordPanel(_ discord: DiscordState) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Discord Notifications")
                    .font(.headline)
                Spacer()
                StatusPill(text: discord.gatewayRunning ? "gateway running" : "gateway blocked")
            }
            InfoRow(label: "Category", value: discord.category)
            InfoRow(label: "Channel limit", value: "\(discord.channelLimit)")
            Text("Required channels")
                .font(.caption)
                .foregroundStyle(.secondary)
            ForEach(discord.requiredChannels, id: \.self) { channel in
                Label(channel, systemImage: discord.missingChannels.contains(channel) ? "circle.dashed" : "checkmark.circle")
                    .foregroundStyle(discord.missingChannels.contains(channel) ? .orange : .green)
            }
            Text(discord.notes)
                .font(.callout)
                .foregroundStyle(.secondary)
        }
        .padding(16)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
    }

    private var publishPanel: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Upload-Post Publishing")
                    .font(.headline)
                Spacer()
                StatusPill(text: store.publishStatus?.provider.liveReady == true ? "live ready" : "dry-run locked")
            }

            Text("Live posting stays locked until the API key is installed outside the repo, account warm-up is complete, live mode is selected, and each post is confirmed from Review Kits.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)

            if let provider = store.publishStatus?.provider {
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 8) {
                    InfoRow(label: "Provider", value: provider.name)
                    InfoRow(label: "API key", value: provider.apiKey)
                    InfoRow(label: "Mode", value: provider.mode == "live" ? "Live" : "Dry Run")
                    InfoRow(label: "Warm-up", value: provider.warmupComplete ? "Complete" : "Pending")
                    InfoRow(label: "Upload user", value: provider.user)
                    InfoRow(label: "Base URL", value: provider.baseURL)
                }

                if !provider.blockers.isEmpty {
                    Text(provider.blockers.joined(separator: " "))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
            }

            Divider()

            Toggle("Account warm-up complete", isOn: $publishWarmupComplete)
                .accessibilityIdentifier("settings-publish-warmup")

            Picker("Provider mode", selection: $publishMode) {
                Text("Dry Run").tag("dry_run")
                Text("Live").tag("live")
            }
            .pickerStyle(.segmented)
            .frame(width: 220)
            .accessibilityIdentifier("settings-publish-mode")

            TextField("Upload-Post user", text: $uploadPostUser)
                .textFieldStyle(.roundedBorder)
                .accessibilityIdentifier("settings-publish-user")

            HStack {
                Button {
                    Task {
                        await store.updatePublishSettings(
                            warmupComplete: publishWarmupComplete,
                            mode: publishMode,
                            user: uploadPostUser
                        )
                    }
                } label: {
                    Label("Save Publish Settings", systemImage: "checkmark.circle")
                }
                .accessibilityIdentifier("settings-publish-save")

                Spacer()

                Text("Install key as Keychain account `uploadpost.api_key` or private `UPLOAD_POST_API_KEY` runtime env.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
        }
        .padding(16)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
        .accessibilityIdentifier("settings-publish-panel")
    }

    private func installerPanel(_ health: HealthResponse) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Buddy Installer")
                .font(.headline)
            Text("The buddy installer opens the app in no-key demo mode and does not move secrets, API keys, Hermes auth, Discord tokens, browser sessions, or Keychain items.")
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
            HStack {
                StatusPill(text: health.safety.autopublish == "blocked" ? "autopublish blocked" : health.safety.autopublish)
                StatusPill(text: health.safety.accountConnection == "blocked" ? "account connect blocked" : health.safety.accountConnection)
                StatusPill(text: health.safety.payoutSubmission == "blocked" ? "payout blocked" : health.safety.payoutSubmission)
            }
        }
        .padding(16)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
    }

    private func syncPublishSettings() {
        guard let provider = store.publishStatus?.provider else { return }
        publishWarmupComplete = provider.warmupComplete
        publishMode = provider.mode
        uploadPostUser = provider.user
    }
}
