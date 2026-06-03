import SwiftUI

struct AgentsJobsView: View {
    @ObservedObject var store: OpsStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                SectionHeader(title: "Agents / Jobs", subtitle: "Hermes roles write through the backend only. Campaign-specific memory stays blocked until feeder qualification.")
                if let agents = store.agents {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack(spacing: 10) {
                            StatusPill(text: agents.status, systemImage: "point.3.connected.trianglepath.dotted")
                            StatusPill(text: agents.hermesAvailable ? "hermes available" : "hermes missing")
                            StatusPill(text: agents.gatewayRunning ? "gateway running" : "gateway blocked")
                            StatusPill(text: agents.authDegraded ? "auth degraded" : "auth ok")
                        }
                        InfoRow(label: "Selected profile", value: agents.selectedProfile)
                        InfoRow(label: "Detected profile", value: agents.detectedProfile)
                        InfoRow(label: "Normal path", value: agents.normalPath)
                        InfoRow(label: "Advanced fallback", value: agents.fallbackPath)
                        InfoRow(label: "Latest Hermes proof", value: agents.latestExecutionProof.detail)
                    }
                    .padding(16)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))

                    ForEach(agents.profiles) { profile in
                        VStack(alignment: .leading, spacing: 10) {
                            HStack {
                                Text(profile.name)
                                    .font(.headline)
                                Spacer()
                                StatusPill(text: profile.status)
                            }
                            Text(profile.role)
                                .foregroundStyle(.secondary)
                            InfoRow(label: "Can write", value: profile.canWrite)
                            InfoRow(label: "Cannot do", value: profile.cannotDo)
                        }
                        .padding(16)
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
                    }

                    VStack(alignment: .leading, spacing: 8) {
                        Text("Hermes Schedules")
                            .font(.headline)
                        ForEach(agents.schedules, id: \.self) { schedule in
                            Label(schedule, systemImage: "clock")
                                .foregroundStyle(.secondary)
                        }
                        if !agents.cronJobs.isEmpty {
                            Divider()
                            ForEach(agents.cronJobs, id: \.self) { schedule in
                                Label(schedule, systemImage: "terminal")
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    .padding(16)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
                } else {
                    EmptyStateView(title: "No Agent State", message: "The backend has not returned Hermes status yet.", systemImage: "person.2.wave.2")
                        .frame(height: 360)
                }
            }
            .padding(22)
        }
    }
}
