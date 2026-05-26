import Foundation

@MainActor
final class OpsStore: ObservableObject {
    @Published var health: HealthResponse?
    @Published var summary: SummaryResponse?
    @Published var campaignGate: CampaignGate?
    @Published var clips: [ClipCandidate] = []
    @Published var nominations: [RenderNomination] = []
    @Published var renderQueue: [JobRun] = []
    @Published var reviewKits: [RenderKit] = []
    @Published var campaignEvidence: [CampaignEvidence] = []
    @Published var platformState: PlatformState?
    @Published var readiness: ReadinessReport?
    @Published var workspaceProfile: WorkspaceProfile?
    @Published var agents: AgentsResponse?
    @Published var auditEvents: [AuditEvent] = []
    @Published var isLoading = false
    @Published var lastError: String?
    @Published var lastActionMessage: String?

    private let client = BackendClient()

    func refreshAll() async {
        isLoading = true
        defer { isLoading = false }
        do {
            async let health: HealthResponse = client.get("health")
            async let summary: SummaryResponse = client.get("summary")
            async let campaignGate: CampaignGate = client.get("campaign-gate")
            async let clips: [ClipCandidate] = client.get("clips")
            async let nominations: [RenderNomination] = client.get("nominations")
            async let queue: [JobRun] = client.get("render-queue")
            async let kits: [RenderKit] = client.get("review-kits")
            async let evidence: [CampaignEvidence] = client.get("campaign-evidence")
            async let platformState: PlatformState = client.get("platforms")
            async let readiness: ReadinessReport = client.get("readiness")
            async let workspaceProfile: WorkspaceProfile = client.get("workspace-profile")
            async let agents: AgentsResponse = client.get("agents")
            async let audit: [AuditEvent] = client.get("audit")

            self.health = try await health
            self.summary = try await summary
            self.campaignGate = try await campaignGate
            self.clips = try await clips
            self.nominations = try await nominations
            self.renderQueue = try await queue
            self.reviewKits = try await kits
            self.campaignEvidence = try await evidence
            self.platformState = try await platformState
            self.readiness = try await readiness
            self.workspaceProfile = try await workspaceProfile
            self.agents = try await agents
            self.auditEvents = try await audit
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    func renderDemoKits() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response: DemoRenderResponse = try await client.post("demo/render")
            if response.status == "succeeded" {
                lastActionMessage = "Created \(response.created.count) demo review kit(s)."
            } else {
                lastActionMessage = response.blocker ?? "Demo render did not complete."
            }
            await refreshAll()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func runCampaignGate() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let gate: CampaignGate = try await client.post("campaign-gate/run")
            campaignGate = gate
            lastActionMessage = gate.blocker
            await refreshAll()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func runPlatformSmoke(twitchLogin: String, kickSlug: String) async {
        isLoading = true
        defer { isLoading = false }
        do {
            if !twitchLogin.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                let _: GenericJSONResponse = try await client.get("platforms/twitch/smoke?login=\(twitchLogin.urlQueryEscaped)")
            }
            if !kickSlug.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                let _: GenericJSONResponse = try await client.get("platforms/kick/smoke?slug=\(kickSlug.urlQueryEscaped)")
            }
            lastActionMessage = "Platform smoke check recorded."
            await refreshAll()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func runSelectedFeederSweep() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let _: GenericJSONResponse = try await client.get("sweeps/selected-feeders")
            lastActionMessage = "Creator check recorded for YourRAGE and Lacy."
            await refreshAll()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func renderSelectedFeederKits() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response: DemoRenderResponse = try await client.post(
                "render/selected-feeders",
                body: EncodableBody(value: ["limit": 2, "style": "selected_feeder_final_v1"])
            )
            lastActionMessage = response.status == "succeeded"
                ? "Built \(response.created.count) latest review kit(s)."
                : (response.blocker ?? "Latest review build did not complete.")
            await refreshAll()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func approve(kit: RenderKit) async {
        do {
            let _: RenderKit = try await client.post("review-kits/\(kit.id)/approve")
            lastActionMessage = "\(kit.title) approved for manual prep."
            await refreshAll()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func reject(kit: RenderKit, notes: String) async {
        do {
            let _: RenderKit = try await client.post("review-kits/\(kit.id)/reject", body: EncodableBody(value: ["notes": notes]))
            lastActionMessage = "\(kit.title) returned for revision."
            await refreshAll()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func exportDiagnostics() async {
        do {
            let result: DiagnosticsExport = try await client.post("diagnostics/export")
            lastActionMessage = "Diagnostics exported: \(result.path)"
            await refreshAll()
        } catch {
            lastError = error.localizedDescription
        }
    }
}

private extension String {
    var urlQueryEscaped: String {
        addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? self
    }
}
