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
    @Published var campaignProjects: [CampaignProject] = []
    @Published var campaignEvidence: [CampaignEvidence] = []
    @Published var platformState: PlatformState?
    @Published var readiness: ReadinessReport?
    @Published var workspaceProfile: WorkspaceProfile?
    @Published var publishStatus: PublishStatus?
    @Published var agents: AgentsResponse?
    @Published var auditEvents: [AuditEvent] = []
    @Published var isLoading = false
    @Published var lastError: String?
    @Published var lastActionMessage: String?

    private let client = BackendClient()

    private func queueHermesJob(intent: String, campaignSlug: String = "", payload: [String: Any] = [:], success: String) async {
        isLoading = true
        defer { isLoading = false }
        do {
            var body: [String: Any] = [
                "intent": intent,
                "requested_by": "gui",
                "payload": payload
            ]
            if !campaignSlug.isEmpty {
                body["campaign_slug"] = campaignSlug
            }
            let job: JobRun = try await client.post("jobs", body: EncodableBody(value: body))
            let owner = job.hermesProfile.isEmpty ? "Hermes" : "Hermes \(job.hermesProfile)"
            lastActionMessage = "\(success) \(owner) job \(job.status == "queued" ? "queued" : job.status)."
            await refreshAll()
        } catch {
            lastError = error.localizedDescription
        }
    }

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
            async let projects: [CampaignProject] = client.get("campaign-projects")
            async let evidence: [CampaignEvidence] = client.get("campaign-evidence")
            async let platformState: PlatformState = client.get("platforms")
            async let readiness: ReadinessReport = client.get("readiness")
            async let workspaceProfile: WorkspaceProfile = client.get("workspace-profile")
            async let publishStatus: PublishStatus = client.get("publish/status")
            async let agents: AgentsResponse = client.get("agents")
            async let audit: [AuditEvent] = client.get("audit")

            self.health = try await health
            self.summary = try await summary
            self.campaignGate = try await campaignGate
            self.clips = try await clips
            self.nominations = try await nominations
            self.renderQueue = try await queue
            self.reviewKits = try await kits
            self.campaignProjects = try await projects
            self.campaignEvidence = try await evidence
            self.platformState = try await platformState
            self.readiness = try await readiness
            self.workspaceProfile = try await workspaceProfile
            self.publishStatus = try await publishStatus
            self.agents = try await agents
            self.auditEvents = try await audit
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    func refreshReviewSurface() async {
        isLoading = true
        defer { isLoading = false }
        do {
            async let kits: [RenderKit] = client.get("review-kits", timeout: 8)
            async let projects: [CampaignProject] = client.get("campaign-projects", timeout: 8)
            async let publishStatus: PublishStatus = client.get("publish/status", timeout: 8)
            self.reviewKits = try await kits
            self.campaignProjects = try await projects
            self.publishStatus = try await publishStatus
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    func refreshForSection(_ section: AppSection) async {
        switch section {
        case .reviewKits:
            await refreshReviewSurface()
        default:
            await refreshAll()
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
        await queueHermesJob(intent: "refresh_campaigns", success: "Refresh Campaigns")
    }

    func runPlatformSmoke(twitchLogin: String, kickSlug: String) async {
        await queueHermesJob(
            intent: "platform_smoke",
            payload: [
                "twitch_login": twitchLogin.trimmingCharacters(in: .whitespacesAndNewlines),
                "kick_slug": kickSlug.trimmingCharacters(in: .whitespacesAndNewlines)
            ],
            success: "Platform check"
        )
    }

    func runSelectedFeederSweep() async {
        await queueHermesJob(intent: "selected_feeder_sweep", success: "Creator check")
    }

    func renderSelectedFeederKits() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let activeProjects = campaignProjects.filter { project in
                project.sourceReady || project.renderedCount > 0 || project.needsReviewCount > 0
            }
            let projects = activeProjects.isEmpty
                ? [
                    CampaignProject.placeholder(slug: "yourrage", name: "YourRAGE")
                ]
                : activeProjects
            var queued = 0
            for project in projects {
                let _: JobRun = try await client.post(
                    "jobs",
                    body: EncodableBody(
                        value: [
                            "intent": "build_campaign_reviews",
                            "campaign_slug": project.slug,
                            "requested_by": "gui",
                            "payload": ["limit": 5, "style": "campaign_short_final_v1", "campaign_slug": project.slug]
                        ]
                    )
                )
                queued += 1
            }
            lastActionMessage = "Queued \(queued) campaign review job(s) for Hermes."
            await refreshAll()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func refreshCampaignProject(_ project: CampaignProject) async {
        await queueHermesJob(
            intent: "refresh_campaign_project",
            campaignSlug: project.slug,
            payload: ["campaign_slug": project.slug],
            success: "\(project.name) brief refresh"
        )
    }

    func discoverCampaignSources(_ project: CampaignProject) async {
        await queueHermesJob(
            intent: "discover_campaign_sources",
            campaignSlug: project.slug,
            payload: ["campaign_slug": project.slug],
            success: "\(project.name) source discovery"
        )
    }

    func buildCampaignReviews(_ project: CampaignProject) async {
        await queueHermesJob(
            intent: "build_campaign_reviews",
            campaignSlug: project.slug,
            payload: ["limit": 5, "style": "campaign_short_final_v1", "campaign_slug": project.slug],
            success: "\(project.name) review build"
        )
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

    func refreshPublishStatus() async {
        do {
            publishStatus = try await client.get("publish/status", timeout: 8)
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    func updatePublishSettings(warmupComplete: Bool, mode: String, user: String) async {
        do {
            let status: PublishStatus = try await client.post(
                "publish/settings",
                body: EncodableBody(
                    value: [
                        "warmup_complete": warmupComplete,
                        "mode": mode,
                        "user": user
                    ]
                )
            )
            publishStatus = status
            lastActionMessage = "Publish settings saved."
        } catch {
            lastError = error.localizedDescription
        }
    }

    func preparePublishPackage(kit: RenderKit, platforms: [String], title: String = "", caption: String = "") async -> PublishPackage? {
        do {
            let package: PublishPackage = try await client.post(
                "review-kits/\(kit.id)/publish-prep",
                body: EncodableBody(
                    value: [
                        "platforms": platforms,
                        "title": title,
                        "caption": caption
                    ]
                ),
                timeout: 20
            )
            lastActionMessage = "Publish package prepared."
            await refreshPublishStatus()
            return package
        } catch {
            lastError = error.localizedDescription
            return nil
        }
    }

    func queuePublishJob(
        package: PublishPackage,
        mode: String,
        platforms: [String],
        title: String,
        caption: String,
        scheduledAt: String = ""
    ) async -> PublishJob? {
        do {
            let job: PublishJob = try await client.post(
                "publish/jobs",
                body: EncodableBody(
                    value: [
                        "package_id": package.id,
                        "mode": mode,
                        "provider": "uploadpost",
                        "platforms": platforms,
                        "title": title,
                        "caption": caption,
                        "scheduled_at": scheduledAt,
                        "requested_by": "gui"
                    ]
                ),
                timeout: 20
            )
            lastActionMessage = mode == "live" ? "Live publish job is awaiting final confirmation." : "Publish dry run queued."
            await refreshPublishStatus()
            return job
        } catch {
            lastError = error.localizedDescription
            return nil
        }
    }

    func confirmLivePublish(job: PublishJob) async -> PublishJob? {
        do {
            let confirmed: PublishJob = try await client.post("publish/jobs/\(job.id)/confirm-live", timeout: 20)
            lastActionMessage = "Live publish confirmed and queued for Hermes."
            await refreshPublishStatus()
            return confirmed
        } catch {
            lastError = error.localizedDescription
            return nil
        }
    }

    func cancelPublishJob(_ job: PublishJob) async {
        do {
            let _: PublishJob = try await client.post("publish/jobs/\(job.id)/cancel", timeout: 12)
            lastActionMessage = "Publish job cancelled."
            await refreshPublishStatus()
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
