import SwiftUI

struct SettingsView: View {
    @ObservedObject var store: OpsStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                SectionHeader(title: "Settings", subtitle: "System health, diagnostics, notifications, and buddy install tools.")

                if let health = store.health {
                    workspacePanel
                    healthPanel(health)
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
}
