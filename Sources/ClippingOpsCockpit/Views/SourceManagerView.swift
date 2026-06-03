import SwiftUI

struct SourceManagerView: View {
    @ObservedObject var store: OpsStore
    @State private var twitchLogin = ""
    @State private var kickSlug = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                SectionHeader(
                    title: "Sources",
                    subtitle: "Advanced creator and platform checks for the agent workbench."
                )

                smokePanel

                if let state = store.platformState {
                    routesPanel(state.routes)
                    checksPanel(state.checks)
                } else {
                    EmptyStateView(title: "No Platform Evidence", message: "Run a smoke check or refresh backend state.", systemImage: "antenna.radiowaves.left.and.right")
                        .frame(height: 320)
                }
            }
            .padding(22)
        }
    }

    private var smokePanel: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Source Checks")
                    .font(.headline)
                Spacer()
                Button {
                    Task { await store.runPlatformSmoke(twitchLogin: twitchLogin, kickSlug: kickSlug) }
                } label: {
                    Label("Run", systemImage: "play.fill")
                }
                .disabled(twitchLogin.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && kickSlug.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .accessibilityIdentifier("sources-run-smoke")
                Button {
                    Task { await store.runSelectedFeederSweep() }
                } label: {
                    Label("Check Creators", systemImage: "scope")
                }
                .accessibilityIdentifier("sources-sweep-feeders")
                Button {
                    Task { await store.renderSelectedFeederKits() }
                } label: {
                    Label("Build Latest Reviews", systemImage: "wand.and.stars")
                }
                .accessibilityIdentifier("sources-render-feeders")
            }

            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 10) {
                GridRow {
                    Text("Twitch login")
                        .foregroundStyle(.secondary)
                    TextField("creator_login", text: $twitchLogin)
                        .textFieldStyle(.roundedBorder)
                        .accessibilityIdentifier("sources-twitch-login")
                }
                GridRow {
                    Text("Kick slug")
                        .foregroundStyle(.secondary)
                    TextField("creator-slug", text: $kickSlug)
                        .textFieldStyle(.roundedBorder)
                        .accessibilityIdentifier("sources-kick-slug")
                }
            }
            .font(.callout)

            Text("Campaign sources drive review builds. Twitch and Kick checks stay here for future creator campaigns; Kick remains monitor-only until clip capture is proven.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
        }
        .padding(16)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
        .accessibilityIdentifier("sources-smoke-panel")
    }

    private func routesPanel(_ routes: [SourceRoute]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Creator Routes")
                .font(.headline)
            if routes.isEmpty {
                Text("No verified source routes yet.")
                    .foregroundStyle(.secondary)
            } else {
                ForEach(routes) { route in
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Label(route.creatorHandle, systemImage: route.platform == "twitch" ? "play.tv" : "bolt.circle")
                                .font(.headline)
                            Spacer()
                            StatusPill(text: route.availabilityStatus)
                        }
                        InfoRow(label: "Platform", value: route.platform)
                        InfoRow(label: "Route", value: route.routeType)
                        InfoRow(label: "Auth", value: route.authState)
                        InfoRow(label: "URL", value: route.sourceURL)
                        if !route.notes.isEmpty {
                            Text(route.notes)
                                .font(.callout)
                                .foregroundStyle(.secondary)
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
    }

    private func checksPanel(_ checks: [PlatformAPICheck]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("API Checks")
                .font(.headline)
            if checks.isEmpty {
                Text("No API check records yet.")
                    .foregroundStyle(.secondary)
            } else {
                ForEach(checks) { check in
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Text("\(check.provider) \(check.endpoint)")
                                .font(.headline)
                            Spacer()
                            StatusPill(text: check.status)
                        }
                        InfoRow(label: "HTTP", value: "\(check.httpStatus)")
                        InfoRow(label: "Rate remaining", value: check.rateLimitRemaining)
                        if !check.error.isEmpty {
                            Text(check.error)
                                .foregroundStyle(.red)
                                .textSelection(.enabled)
                        }
                        if !check.responseExcerpt.isEmpty {
                            Text(check.responseExcerpt)
                                .font(.caption.monospaced())
                                .foregroundStyle(.secondary)
                                .lineLimit(6)
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
    }
}
